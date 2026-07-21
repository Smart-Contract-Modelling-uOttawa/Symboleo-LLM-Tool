# Suite Concurrency & Cancellation — Design Sketch

> Status: **implemented** — phases 1 & 2 shipped. Retained for the design
> rationale.

## 1. Goal & scope

Run a suite faster by executing independent work concurrently along two axes:

- **Candidates** within a single `pipeline.run` (the `num_candidates` loop).
- **Experiments** within a `run_suite` (each experiment is an independent `pipeline.run`).

Out of scope (cannot parallelize): the **correction loop** inside a candidate —
iteration *N+1*'s prompt is built from iteration *N*'s validator errors, so it is
intrinsically sequential.

Hard requirements:

- Bounded resource use (don't oversubscribe an average dev machine).
- Cooperative **cancellation** for `stop_on_first_convergence` and (carefully) for
  dropped SSE connections.
- Preserve the architecture: **sync** pipeline core, **thread**-based (no async
  rewrite), SSE transport untouched, and the *compose-don't-modify* altitude
  discipline between `run_suite` and `pipeline.run`.
- **Opt-in**: default behavior stays exactly sequential (back-compat for the CLI
  and existing tests).

## 2. Starting point (pre-implementation)

- `pipeline.run` runs candidates sequentially; `run_suite` runs experiments
  sequentially (`experiments/runner.py`).
- The API already runs the sync pipeline off the event loop via
  `run_in_threadpool` and posts progress with `loop.call_soon_threadsafe`
  (`api/routes.py`). That call is **thread-safe**, and `ProgressEvent` already
  carries `experiment_index` + `candidate_id`, so **the SSE transport is already
  concurrency-ready** — interleaved progress multiplexes onto one queue and the
  client demuxes by tag. No SSE change is needed for concurrency itself.
- Threads give *real* parallelism here because the blocking work is I/O-bound:
  `litellm.completion()` (socket) and the JAR `subprocess.run` (child process)
  both release the GIL while waiting.

## 3. Key insight: the candidate is the unit of concurrency

A candidate is the smallest thing that does heavy work (a generation call, then a
sequential correction loop of LLM calls + JAR validations). Experiments are just
*groupings* of candidates. So:

> Bound the number of **concurrently-running candidates** with a single global
> cap `K`, and both axes are throttled by one knob.

This avoids the nested-explosion trap (see §4.1) and gives one number to reason
about for feasibility (see §4.4).

## 4. Concurrency design

### 4.1 Iteration 0 (naive) — two independent pools ❌

A `ThreadPoolExecutor(E)` for experiments and a nested
`ThreadPoolExecutor(C)` for candidates inside each. Rejected:

- **Explosion.** Up to `E × C` candidates (hence up to `E × C` JVMs) run at once —
  unbounded by any single number. A 12-experiment × 3-candidate suite could try 36
  concurrent JVMs.
- **Two knobs** to tune with non-obvious interaction.

### 4.2 The deadlock constraint — why two pools, with distinct roles

Tempting fix: one bounded pool, submit everything to it. But an **experiment
driver** (a `pipeline.run` call) must *submit its candidates and then block
waiting for them*. If drivers and candidates share one bounded pool, drivers
occupy workers while waiting for candidates that need those same workers →
**classic thread-pool deadlock** (nested submission to a bounded pool).

So we need **two pools with different jobs**:

| Pool | Size | Role | Weight |
|---|---|---|---|
| `experiment_pool` | `min(num_experiments, K)` | drives each experiment's `pipeline.run`; mostly **blocked** on candidate futures | light (idle threads) |
| `candidate_pool` | `K` (the global cap) | runs candidate pipelines — the only place LLM/JVM work happens | **heavy** (throttled) |

Drivers submit candidates to a *different* pool than the one running drivers →
no deadlock. The `experiment_pool` is pure orchestration (blocked threads are
cheap); `K` on `candidate_pool` is the real throttle. For a **single run** (no
suite) there are no drivers — `pipeline.run` runs on the caller's thread and
submits its candidates to its `candidate_pool`.

### 4.3 The model

```
run_suite (1 thread, from run_in_threadpool)
 ├─ candidate_pool = ThreadPoolExecutor(max_workers=K)   # shared throttle
 ├─ experiment_pool = ThreadPoolExecutor(min(E, K))      # light drivers
 └─ for each experiment: experiment_pool.submit(pipeline.run, ..., coordinator)
        └─ pipeline.run: for each candidate:
               candidate_pool.submit(_run_candidate, ...)   # heavy work, ≤K live
```

All candidates across all experiments share the one `candidate_pool`, so at most
`K` candidate pipelines are live regardless of how many experiments/candidates
exist. That is the whole feasibility story in one variable.

### 4.4 Feasibility budget — choosing `K`

The binding constraint is **not CPU**, it's **JVM memory + provider rate limits**:

- Each headless SymboleoAC validation spawns a JVM. Estimate ~150–300 MB resident
  + a CPU spike at startup (should be *measured*, but order-of-magnitude). Within a
  candidate, the LLM call and the JVM don't run at the same instant, but worst case
  all `K` candidates hit the JVM step together → `K` concurrent JVMs.
- Provider rate limits (RPM/TPM) also favor a small cap; `K` concurrent
  correction chains is `K` concurrent request streams.

For an average dev machine (~8–16 GB RAM, 4–8 logical cores):

> **`K = 2` default.** ≈ 0.3–0.6 GB of JVMs worst-case and two concurrent request
> streams — gentle on both memory and rate limits, a safe out-of-the-box default.
> Configurable; **clamped to `[1, 8]`** (the clamp stops a typo like
> `max_concurrency: 64` from melting the machine).

**On `K = 1` (the sequential floor).** `K = 1` is *exactly* the current
implementation, by design — not a degenerate "pool of size 1". `run_suite`
detects it and takes the literal sequential path with **no executor, no
coordinator** spun up (the request-scoped cancel token still flows through, so
Stop/disconnect cancellation works sequentially too). It's a valid value so a user can
force deterministic, one-at-a-time execution (debugging, or a rate-limited API
key) — the explicit opt-out from concurrency.

### 4.5 Threading it through the layers (compose, don't modify)

A single small, frozen bundle is passed down — no wide signatures, no reaching
through nested objects (LoD):

```python
@dataclass(frozen=True)
class RunCoordinator:
    candidate_pool: ThreadPoolExecutor   # the shared, bounded work pool
    cancel: CancellationToken            # this run's cancellation view (see §5)
```

`max_concurrency` is a **suite-level** knob (`SuiteConfig.max_concurrency`), so
`pipeline.run` stays config-agnostic about concurrency — it's driven *only* by
whether a coordinator is passed:

- `pipeline.run(contract, config, on_progress=None, coordinator=None, cancel=None)`:
  - `coordinator is None` → the **existing sequential loop**. This is the path
    for **single runs** (CLI, `POST /generate`) and for a `K = 1` suite; it is
    behaviorally unchanged unless a `cancel` token is tripped (the loop only
    gains cooperative checkpoints).
  - `coordinator` given → submit candidates to `coordinator.candidate_pool`.
- `run_suite` reads `suite.max_concurrency`: `K == 1` → call `pipeline.run` with no
  coordinator (today's sequential suite); `K > 1` → build the shared
  `candidate_pool(K)` + `experiment_pool` + request token, make a per-experiment
  child token (§5.2), and hand each `pipeline.run` a
  `RunCoordinator(shared_candidate_pool, child_token)`.

`run_suite` still *composes* `pipeline.run` — it doesn't reach inside it. The new
dependency is one explicit, optional parameter, so it's additive (Open/Closed).
Defaulting suites to `K = 2` makes the *default suite path concurrent*; single
runs are unaffected.

### 4.6 Result ordering

Futures complete out of order; `CandidateResult.candidate_id` and
`ExperimentResult` order are reconstructed by sorting on the known indices before
building `PipelineResult` / `SuiteResult`. Results are deterministic w.r.t.
content (each unit is independent); only wall-clock timing changes.

## 5. Cancellation strategy

### 5.1 Cooperative only (the thread limitation)

Python threads can't be force-killed, and we cannot interrupt an in-flight
`litellm.completion()` or `subprocess.run`. So cancellation is **cooperative**: we
set a flag and check it at **safe checkpoints**:

- **before a candidate starts** (task entry) — a not-yet-started candidate
  short-circuits to a cheap "skipped" outcome;
- **between correction iterations** — stop the loop and return what converged so
  far.

We never check mid-call. The bounded cost: when cancellation fires, at most the
**currently in-flight iteration per live candidate** is wasted (≤ `K` iterations),
then discarded. That waste is acceptable and capped by `K`.

### 5.2 `CancellationToken` with linked children (DRY, one abstraction)

```python
class CancellationToken:
    """Cooperative cancellation. A child is cancelled if it OR any ancestor is."""
    def __init__(self, parent: "CancellationToken | None" = None) -> None:
        self._event = threading.Event()
        self._parent = parent

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set() or (self._parent is not None and self._parent.cancelled)

    def child(self) -> "CancellationToken":
        return CancellationToken(parent=self)
```

One type serves both triggers via a hierarchy:

```
request_token            # cancelled on client disconnect (§5.4)
 └─ experiment_token = request_token.child()   # cancelled on stop_on_first_convergence (§5.3)
```

A candidate checks its `experiment_token.cancelled`, which is `True` if *either*
its experiment converged *or* the whole request was cancelled. No bespoke flags,
no boolean plumbing — one `cancelled` read at each checkpoint.

### 5.3 Trigger 1 — `stop_on_first_convergence` (the clean win)

Sequentially this is just `break`. Concurrently: each experiment owns a child
token; when one of its candidates converges, the experiment driver calls
`experiment_token.cancel()`. The experiment's other candidates short-circuit at
their next checkpoint. Self-contained, no reconnect interaction — **this is the
high-value, low-risk half** and should ship first.

### 5.4 Trigger 2 — client disconnect (the subtle one)

Naively wiring "disconnect → `request_token.cancel()`" collides with
**EventSource auto-reconnect**: a transient network blip drops the connection, the
browser immediately reconnects with a *new* request, but we'd have already
cancelled the run. We'd kill runs on every hiccup.

Resolution — **two layers: explicit cancel (primary) + detached-with-grace (fallback).**

*Explicit — the common case.* A **Stop button** and a `pagehide`
`navigator.sendBeacon` both `POST /runs/{id}/cancel`, which trips `request_token`
**immediately**. A voluntary leave (Stop, tab close) is self-reported, so there's
no grace to wait out. This is what makes cancellation effective for *short* runs:
a 30 s grace can never catch a 15 s run, but an explicit signal can.

*Fallback — involuntary drops.* For a crash / dead network where no beacon
arrives, `_stream_job` marks the job *detached* on `request.is_disconnected()` —
it does **not** cancel immediately, or EventSource auto-reconnect would trip on
every blip. A reconnect clears *detached*; a background sweep cancels a job
detached longer than `DETACH_GRACE` (**10 s** — only needs to be reconnect-safe,
since the explicit path covers voluntary leaves). The sweep rides the cleanup
loop at a **5 s** interval, so the fallback fires in ~10–15 s.

**Propagation is already wired by phase 1.** Tripping `request_token` cancels
every experiment child token and coordinator, so the cooperative checkpoints stop
all *future* LLM calls. The only tail is the in-flight ≤ `K` calls — a blocking
call can't be interrupted without abandoning the thread model.

### 5.5 Exceptions

A raising candidate propagates out of `pipeline.run` (`future.result()`
re-raises; the gather aborts). Suite
level keeps today's semantics (a hard failure surfaces as an `ErrorEvent`).
**Decided: fail-fast** on an unexpected exception — `request_token.cancel()` to
stop siblings and surface the error — while **continuing** on ordinary
non-convergence (that's a result, not an error). Fail-fast avoids paying for `K-1`
more doomed experiments after a config/credential/JAR error that will hit them all.

### 5.6 Pool lifecycle

Pools are owned for exactly one top-level request and closed via context managers
so threads are always reclaimed:

```python
with ThreadPoolExecutor(max_workers=K) as candidate_pool, \
     ThreadPoolExecutor(max_workers=min(E, K)) as experiment_pool:
    ...
# __exit__ → shutdown(wait=True): in-flight candidates drain (cooperative cancel
# has already short-circuited the rest), then threads are freed.
```

Not-yet-started candidates short-circuit at the token's entry checkpoint
(returning `None`); started ones rely on the cooperative checkpoint to exit
promptly.

## 6. Code-quality mapping

- **SoC.** `pipeline.run` owns candidate orchestration; `run_suite` owns
  experiment orchestration; a new `concurrency.py` owns the reusable primitives
  (`CancellationToken`, `RunCoordinator`); the API owns only
  disconnect→cancel wiring. Each concern stays in one place.
- **DRY.** One `CancellationToken` for both triggers (linked children); one shared
  `candidate_pool`; the sequential and concurrent paths share the *same*
  `_run_candidate` body (only the *scheduling* differs).
- **LoD.** A single frozen `RunCoordinator` is passed; callers read
  `coordinator.cancel.cancelled` / submit to `coordinator.candidate_pool` — no
  reaching through nested config. Mirrors the existing flat `_RunContext`.
- **Open/Closed / compose-don't-modify.** Concurrency is an additive, optional
  branch. `coordinator=None` + `max_concurrency=1` ⇒ the sequential behavior,
  unchanged unless a cancel token is tripped. `run_suite` composes
  `pipeline.run` as before.
- **Naming.** `RunCoordinator`, `CancellationToken.child()/cancelled/cancel()`,
  `candidate_pool` / `experiment_pool`, `max_concurrency` — say what they are.

## 7. What changed, file by file

| File | Change |
|---|---|
| `concurrency.py` (new) | `CancellationToken`, `RunCoordinator`. No domain knowledge — pure primitives (pools are plain `ThreadPoolExecutor` context managers in `runner.py`). |
| `config/models.py` | `SuiteConfig.max_concurrency: int = 2`, clamped `[1, 8]` by a validator. Suite-level (decision #2) — `RunConfig`/`pipeline.run` stay concurrency-agnostic. |
| `pipeline/pipeline.py` | optional `coordinator` param; a concurrent candidate branch alongside the existing sequential one; cooperative checkpoints in the correction loop. `_run_candidate` body unchanged. |
| `experiments/runner.py` | read `max_concurrency`; `K==1` → today's sequential path; `K>1` → build the two pools + request token, per-experiment child tokens, submit experiments to `experiment_pool`, gather + regroup, fail-fast on exceptions. Still composes `pipeline.run`. |
| `api/routes.py` + `api/jobs.py` + `api/app.py` | `Job` holds a request-scoped `cancel` token + `detached_at`; `_stream_job` marks attached/detached; `POST /runs/{id}/cancel` trips the token (Stop button + `pagehide` beacon); the cleanup loop (5 s) cancels jobs detached past the 10 s grace. `pipeline.run` gains a `cancel` param so single runs honor it too. |
| tests | `CancellationToken` (linked semantics), bounded-pool throttle, candidate/experiment concurrency vs. a fake pipeline, `stop_on_first_convergence` cancellation, ordering, fail-fast. Existing `test_suite_runner.py` order/call-sequence assertions pin `max_concurrency=1` (the default is concurrent). No live LLM needed. |

## 8. Limiting factors → handling

| Factor | Handling |
|---|---|
| Threads can't be force-killed | Cooperative checkpoints; in-flight call finishes then discarded (≤ `K` wasted iterations). |
| Nested submission deadlock | Two pools with distinct roles (§4.2). |
| JVM memory / rate limits | Single global `K` (default 2, clamped `[1,8]`); `K` bounds concurrent JVMs and request streams. |
| Amdahl (sequential correction loop) | Accepted; concurrency helps across *many similar-cost* units, not one dominant chain. |
| Dropped SSE + auto-reconnect | Explicit cancel (Stop / beacon) is immediate; detached-with-grace (10 s, 5 s sweep) is the fallback so a blip doesn't kill a run (§5.4). |
| No cost reduction | Documented; concurrency cuts wall-clock only, not tokens/cost. |
| Reproducibility | Results content-deterministic; default `max_concurrency=1` keeps runs identical unless opted in. |
| `stop_on_first_convergence` saves less under concurrency | Up to `K` candidates may already be in flight when one converges; they run to their next checkpoint before the cancel lands, so >1 may converge. Harmless (`success = any converged`), but the token-cancel saving is partial, not the clean sequential `break`. |
| Frontend live counter assumes one active unit | The single "Experiment N — Candidate M — Iteration I" label (`lib/progress.ts`) flickers between concurrently-running experiments. Cosmetic only; follow-up = a per-experiment progress list or an "N running" summary. Not a blocker (progress events already carry `experiment_index`). |

## 9. Phasing (both shipped)

- **Phase 1:** candidate + experiment concurrency via the
  suite-level `max_concurrency` (default 2), with `stop_on_first_convergence`
  cooperative cancellation (§5.3) and fail-fast on errors (§5.5). Disconnect stays
  fire-and-forget. No API change. Single runs are untouched (concurrency is
  suite-only).
- **Phase 2:** explicit cancellation — a Stop button + `pagehide`
  beacon → `POST /runs/{id}/cancel` (primary, immediate) — with
  detached-with-grace (10 s grace, 5 s sweep) as the fallback for involuntary
  drops (§5.4). Touches `routes.py`/`jobs.py`/`app.py`, adds a `cancel` param to
  `pipeline.run` (single-run path), and the two results pages.

## 10. Decisions (resolved)

1. **`K` default = 2**, clamped `[1, 8]`. `K = 1` is the sequential floor / opt-out
   (§4.4), not redundant.
2. **`max_concurrency` is suite-level** (`SuiteConfig`). `pipeline.run` stays
   concurrency-agnostic; single runs (CLI, `/generate`) are untouched (§4.5).
3. **Cancellation is two-layer** (§5.4): explicit Stop button + `pagehide` beacon
   (immediate, the common case) backed by detached-with-grace (10 s grace, 5 s
   sweep) for involuntary drops. Propagation reuses phase 1's token hierarchy.
4. **Fail-fast** on an unexpected exception; continue on ordinary non-convergence
   (§5.5).

Consequence accepted: with the default `K = 2`, the *default suite path is
concurrent*, so progress/call ordering is non-deterministic and a few
order-sensitive `test_suite_runner.py` assertions pin `max_concurrency=1`.
