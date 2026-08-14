# Plan — fidelity inventory extractor (preliminary, analysis-side)

**Lifecycle:** working plan artifact, the hand-off contract for `/implement`
(invoke as `/implement docs/plans/inventory-extractor.md`). Not durable
documentation — the implementation change deletes this file (absorbing anything
still load-bearing into CLAUDE.md).

**Branch:** `feat/inventory-extractor` (this file's branch; implementation
stacks on it). **Classification: ARCHITECTURAL** — see §7.
**Written:** 2026-08-12, validated against the code at `cf5bcfa`.
**Revised:** 2026-08-12 (design-review pass — added the pre-committed
calibration exit bar (§6a), the verdict-stability and draw-stability probes,
the metadata stamp conventions, and the optional-`clause` decision).

---

## 1. Problem and decided constraints (do not re-open)

The fidelity instrument scores a generated contract against a curated clause
inventory (`contracts/inventories/*.yaml`). The judge prompt is
contract-agnostic; all contract-specific knowledge is the checklist, and only
the six benchmark contracts have one — so fidelity is unscorable on any new
contract. The **inventory extractor** is an LLM step that reads *only a source
contract `.txt`* and emits an inventory in the same shape.

Decided in discussion (2026-08-12):

- **Extractor seat: `gpt-5.6-luna`.** Extraction errors are *answer-key*
  errors — they corrupt every score against that contract (the energy.yaml
  incident is the quantified exhibit) — so the strongest model takes the seat
  with the highest cost per mistake. The backup judge (`gpt-4.1-mini`) is
  disqualified for key-writing by its calibration record (misses
  `HappensAssign`-style encodings; over-flags).
- **Residual bias channel, and its detector.** The extractor never sees a
  candidate, so judge-style self-preference doesn't apply; the only channel is
  a *shared blind spot* — clause types luna both fails to extract and fails to
  generate, which would inflate luna's own coverage. The calibration run below
  doubles as the probe: the six curated inventories are hand-written gold, so
  a blind spot surfaces as a recall pattern. No separate bias study.
- **Preliminary, analysis-side cut only.** No pipeline/API/frontend changes,
  no result-model changes, no schema regen, no `fidelity_sweep.py` changes.
- **First use of the built code is the calibration run** (§6): extract the six
  inventoried contracts, compare against curated on recall / precision /
  granularity / draw-stability, and run the verdict-stability probe.
  "Passes" means the pre-committed bar in §6a — fixed before any extraction
  runs, so the verdict cannot bend toward the data. Until it passes, coverage
  computed from an extracted checklist is **provisional** — the judge was
  calibrated against the curated `expects` register, and an extracted register
  may steer verdicts differently (the curated `expects` embed
  calibration-derived judge tolerances no extractor can recover from the
  source text alone; the verdict-stability probe is the direct measurement,
  which item-level alignment cannot see). Surfacing covers denominator
  *visibility*, not this.
- **An extracted checklist is always surfaced** — written to a visible file
  and printed, never silently consumed. A wrong denominator is invisible
  inside a coverage number.

## 2. Chosen approach (summary)

Mirror the judge's split exactly. `output/fidelity.py` gains the pure pieces:
an (uncalibrated, clearly marked) `EXTRACTION_INSTRUCTIONS`, a payload
builder, a structural parse, and a single inventory well-formedness validator
shared with the curated-fixture fence. `scripts/inventory_extract.py` is the
thin consumer: one LLM call per contract, output to
`output/inventories_extracted/` (gitignored, structurally incapable of
shadowing `contracts/inventories/` — the sweep reads only its hardcoded
`INVENTORY_DIR`), always printed, with a `--compare` mode that renders
curated-vs-extracted item lists for the manual calibration alignment.

## 3. Design decisions

**D1 — Extend `output/fidelity.py`; no new module.** The file is ~91 lines and
the extractor is the other half of the same instrument — it emits exactly the
item shape `build_payload` serializes and `test_fidelity.py` fences. A
`output/inventory.py` would be a structural mirror splitting "what an
inventory is" across two homes. Accommodation required: the module docstring's
"editing `INSTRUCTIONS` invalidates the judge calibration" warning must be
**scoped to the judge string**, with one sentence marking
`EXTRACTION_INSTRUCTIONS` as not-yet-calibrated.

**D2 — LLM emits JSON; the script stamps metadata and writes YAML.** The model
returns `{"items": [{"id", "kind", "clause", "expects"}]}` only. The metadata
is stamped by `assemble_inventory(items, source)` in `output/fidelity.py`
(pure, no LLM — the stamp conventions are part of "what an inventory is" per
D1, and putting them in the package makes them testable) — the script knows
the real path, and the sweep keys inventories by
`Path(inventory["source"]).stem.lower()`, so a model-guessed path is a wrong
join key. **The stamp values are load-bearing conventions:** `contract` =
`stem.lower()` and the output file is `<stem.lower()>.yaml` — curated files
are lowercase (`energy.yaml`, `contract: energy`) while four of the six
contract files are capitalized (`Energy.txt`), so an un-lowered stem breaks
the `--compare` join on four of six contracts. `source` is stamped
**repo-relative** when the input lies under the CWD (the sweep resolves
`source` bare from the repo root, and an absolute path makes the file
non-portable — same reasoning as `PortablePath`); an input outside it gets
its absolute path plus a header-comment warning that the file cannot feed the
sweep as-is. Rejected: YAML directly from the LLM (fragile multiline scalars;
bypasses the existing tested parse tolerance); model-emitted
`contract`/`source`.

**D3 — Parse/validate split, one home for item semantics.**
`parse_extraction(text)` is *structure only* — reuse `parse_judge_json`
internally (it is content-generic: fence-strip + outermost-brace +
`json.loads`; do **not** rename it, its tests are pinned) and check just the
envelope shape: a dict whose `items` is a list of dicts. It knows nothing
about field names — a field check there would define the item schema twice
and let the two definitions drift. `inventory_errors(inventory)` is the
**single semantic validator** and owns *all* field rules — top-level keys
present; items non-empty; per-item `id`, `kind`, `expects` non-empty strings;
`clause` optional but a non-empty string when present (unnumbered contracts
have nothing honest to put there — see §5); ids unique — with each failure
naming its item, so an error file says which item is wrong instead of only
dumping the raw response. Used by *both* the curated-fixture fence
(refactored onto it; the fence keeps two curated-only assertions beside it —
every curated item carries `clause`, and `source` exists on disk, the latter
also covered by the Counter fence) and the script before writing. Script
flow: parse → assemble (D2) → validate → write (deleting any stale
`<stem>.error.txt` from a prior failed run — a success/failure pair must
never sit side by side), or on any failure write `<stem>.error.txt` carrying
the per-item errors and the raw response — never silent. Id uniqueness is
load-bearing beyond hygiene: the judge joins verdicts to items by `id`, so
collisions corrupt verdict matching.

**D4 — Kind vocabulary: guide, don't hard-validate.** The instructions list
the observed vocabulary (`obligation`, `power`, `state`, `access_grant`) but
`inventory_errors` checks only *presence* of `kind` — parity with the existing
fixture fence, and hard-closing the set pre-calibration would silently bias
extraction toward the current taxonomy.

**D5 — Calibration alignment is manual, supported by a shipped renderer.**
Total curated volume is 50 items across 6 contracts (6–13 each): manual
alignment is about an hour, and the human reading *is* the calibration —
split/merge granularity judgment is the finding, not an obstacle to automate.
What ships is `--compare`: for each contract with a curated inventory, render
both item lists (id / kind / clause / **full** `expects` text — truncation
would hide exactly what alignment judges) plus counts. No matching is
attempted in code. Rejected: **LLM-assisted alignment** — puts luna inside the
loop that measures luna's blind spots (correlated error in the bias probe) and
adds a prompt surface needing its own trust story; **programmatic fuzzy
matching** — prose similarity cannot see split/merge, the dominant divergence
mode, and mis-pairs silently corrupt recall/precision.

**D6 — One script, flags not subcommands** (matching `fidelity_sweep.py`):
positional `contracts` (`.txt` paths; a directory arg expands to its `*.txt` —
PowerShell doesn't glob, keep the sweep's docstring caveat), `--model`
default `gpt-5.6-luna`, `--provider` default `openai`, `--temperature` default
`None` (reasoning-model omission note, verbatim from the sweep), `--max-tokens`
default 16000, `--out` default `output/inventories_extracted/`, `--force`
(default skip-if-exists — the output file *is* the cache; no separate cache
dir), `--compare`. Sequential, no retry (one failure costs one contract,
printed + error file — same philosophy as the pipeline's failed-call rule).
Written files carry a header comment: extracted by `<model>` on `<date>`, not
curated, do not move into `contracts/inventories/` without review. Always
print the checklist table and the file path, including on cache hit.

**D7 — Promote nothing into the package for the LLM call.** The sweep's
"wrapper" is already just package API (`create_adapter(LLMConfig(...))` +
`.generate(payload).generated_text`, ~6 lines) — copy the idiom.
`output/fidelity.py`'s purity contract ("Nothing here calls an LLM") keeps it
importable/testable without spending calls; an LLM helper there would break
it. A `scripts/_common.py` is not warranted at ~10 duplicated lines — flag
only if a third LLM-calling script appears.

**D8 — Unknown-contract placement policy.** The Counter fence
(`test_every_contract_has_exactly_one_inventory`) makes `contracts/` mean
*curated benchmark membership*: any `.txt` there without an inventory reds the
suite. Policy: **experimental contracts live outside `contracts/`** (the
extractor takes explicit paths, so location is free); joining `contracts/`
requires a reviewed inventory in the same change — the existing fence *is* the
promotion gate, untouched. Copying an extracted file beside a curated one also
reds it (duplicate `source`), so shadowing is double-fenced.

## 4. Touch-list

- `symboleo_llm_tool/output/fidelity.py` (edit):
  - `EXTRACTION_INSTRUCTIONS: str` — draft per §5, explicitly marked
    uncalibrated;
  - `build_extraction_payload(source_text: str) -> str`;
  - `parse_extraction(text: str) -> list[dict[str, Any]] | None` (per D3);
  - `assemble_inventory(items: list[dict[str, Any]], source: Path) ->
    dict[str, Any]` — the stamp conventions of D2 (pure, no LLM);
  - `inventory_errors(inventory: dict[str, Any]) -> list[str]` (per D3/D4);
  - docstring: scope the calibration warning to the judge `INSTRUCTIONS`.
- `scripts/inventory_extract.py` (new): `main()` per D6; helpers approx.
  `extract_one(path, adapter, out_dir, force) -> dict | None`,
  `write_inventory(inventory, out_path)` (header comment +
  `yaml.safe_dump(..., sort_keys=False)`), `print_checklist(inventory)`,
  `print_comparison(curated, extracted)`. `--compare` loads curated YAMLs
  directly (a ~5-line loader; do not imitate the sweep's private
  `_source_text` injection).
- `tests/unit/test_fidelity.py` (edit): fences per §8; refactor
  `test_inventories_are_well_formed` onto `inventory_errors` so curated
  fixtures and extracted output share one well-formedness definition —
  keeping the curated-only assertions (`clause` present on every item,
  `source` exists — D3).
- CLAUDE.md (edit, same change): update the *Convergence ≠ fidelity* open-path
  paragraph — extractor built, seat = luna with the shared-blind-spot channel
  and its calibration-recall detector, extracted-checklist coverage
  provisional pending calibration against the pre-committed §6a bar.
- Delete this plan file.
- **No changes:** `scripts/fidelity_sweep.py`, `contracts/inventories/*`,
  pipeline/API/frontend, config/result models, generated schemas (⇒ no
  `schema.d.ts` regen obligation).

## 5. `EXTRACTION_INSTRUCTIONS` drafting requirements (high-tier work)

Contract-agnostic; task = enumerate **every normative clause**: obligations,
powers/discretions, state/lifecycle rules, access grants — each with parties,
direction (who owes whom), deontic modality (shall / may / must-not), trigger,
and deadline/temporal constraint. The `expects` prose must match the
**curated register** — naming parties, direction, modality, trigger, deadline,
and enforcement expectations where the text demands them (e.g. "the deadline
must be enforced by a temporal predicate, not merely named in an identifier")
— because the judge was calibrated against that register (see §1,
provisional-coverage constraint). `id`: unique snake_case slug. `clause`: the
source clause/section reference where the text numbers one; otherwise a
paragraph ordinal (`"para 3"`) or a ≤10-word anchoring quote — never invented
numbering, and omission is legal (the validator treats `clause` as optional,
D3), so the model is never forced to fabricate metadata to satisfy a schema.
Output: the JSON envelope of D2 only, no prose (parse tolerates fences/prose
anyway). The file-wide E501
ignore already covers long instruction lines. **No phrase pins yet** (§8).

## 6. Calibration protocol (session work, after the code lands)

1. Run the extractor over the six curated contracts
   (`uv run python scripts/inventory_extract.py contracts --compare`).
2. **Draw-stability check:** extract each contract a second time (`--out` to
   a sibling dir, or `--force` after archiving the first draw) and diff the
   two item lists. One draw is a hypothesis, not a measurement (Prompt-Probe
   Harness: two draws of one identical config disagreed completely), and the
   skip-if-exists cache would otherwise hide instability forever. An
   extractor whose item list is not stable across draws makes every
   downstream score irreproducible regardless of register quality.
3. Manually align extracted↔curated per contract from the `--compare` output.
   Record per contract: **recall** (curated items with no extracted
   counterpart — each missed item silently inflates every candidate's
   coverage), **precision** (extracted items with no textual basis — these
   deflate it), **granularity** (split/merge divergences — these shift the
   denominator, so extracted-inventory scores are comparable only against
   scores from the *same* inventory).
4. **Verdict-stability probe:** judge a handful of already-archived
   candidates per contract against the curated *and* the extracted inventory
   and compare per-item verdicts. Item-level alignment cannot see register
   divergence, and the curated `expects` embed calibration-derived judge
   tolerances (energy.yaml's `payment_timing` carries "must not be marked
   wrong-direction") that no extractor can recover from the source text —
   this probe is the only direct measurement of the §1 provisional-coverage
   risk. The curated side is already cached; the extracted side MUST use a
   separate `--cache` dir — the sweep's cache key
   (`{parent}_{arm}_{candidate_id}`) carries no inventory identity, so
   reusing the default dir silently serves curated-judged results.
5. Read the bias probe: are missed items disproportionately the clause types
   luna-generated contracts also fumble (temporal predicates,
   direction-sensitive payment/consequence clauses)?
6. Iterate wording if needed (the instructions are unpinned precisely so this
   loop is cheap), re-extract with `--force`, re-align, and re-read against
   the **same** §6a bar. **Few-shot rule, pre-committed:** if an iteration
   adds a worked example to the instructions, the example must be
   out-of-corpus, or its contract drops out of the calibration metrics — a
   curated inventory used as the example is the answer key for that
   contract's cell (the same leave-one-out discipline as `few_shot`).

## 6a. Exit criterion (pre-committed — fixed before any extraction runs)

"Calibrated" is a manual verdict read against this bar and recorded in
CLAUDE.md (§9.2). The bar is written now so the decision cannot bend toward
the data after the fact (the same discipline as the reserved-words
two-round exit condition). The human alignment reading stays — someone still
decides what counts as a miss versus a granularity split — but not the
freedom to decide post hoc that the misses were fine.

- **Recall:** at most 1 missed curated item per contract (the judge's own ±1
  noise floor is the natural width), and zero misses concentrated in the
  bias-probe classes — a temporal-predicate or direction-sensitive clause
  missed on ≥2 contracts fails regardless of totals (that is the
  shared-blind-spot channel, §1).
- **Precision:** at most 1 extracted item per contract with no textual basis.
- **Draw stability:** the two draws' item lists agree up to granularity —
  split/merge of the same content is tolerated; clauses appearing in one
  draw and not the other are not.
- **Verdict stability:** per-item verdict agreement between curated- and
  extracted-checklist judgments at or above the judge's own calibration rate
  (39/42 ≈ 93%).
- **Granularity:** recorded, not gated — divergence doesn't make an inventory
  wrong, it makes its scores non-comparable with curated-inventory scores (a
  caveat that travels with the numbers).

Consequences: **pass** → provisional status lifts; numbers + verdict recorded
per §9.2. **Fail** → one §6.6 wording iteration, re-run, re-read against this
same bar. **Fail twice** → provisional stays and the standing policy becomes
"extracted inventories require human review before use" — a recorded
decision, not indefinite limbo.

## 7. Classification: ARCHITECTURAL

The script and validator are recipe work, but the risk concentrates exactly
where a cheap fresh context does damage: `EXTRACTION_INSTRUCTIONS` is
judge-adjacent prose whose quality decides the calibration outcome and is
**not fenceable by tests pre-calibration**, and the edit sits beside a
calibrated artifact whose phrase pins must not be disturbed (the D1 docstring
accommodation). Implement high-tier; do not tier down.

## 8. Tests

Ship with the implementation (all in `tests/unit/test_fidelity.py`):

- `inventory_errors`: happy path against a minimal valid inventory; missing
  top-level key; missing/empty item field; `clause` absent is legal while
  `clause` present-but-empty is not; duplicate id; empty items list; error
  strings name the offending item.
- Curated-fixture fence refactored to assert `inventory_errors(inv) == []`,
  plus the curated-only assertions (every item carries `clause`; `source`
  exists on disk — D3).
- `parse_extraction`: fenced/prose-wrapped envelope parses; garbage → `None`;
  valid envelope → items; non-list `items` / non-dict item → structural
  rejection. Field-level cases live with `inventory_errors`, not here (D3:
  one home for item semantics).
- `assemble_inventory`: `contract` and filename stem lowercased (pin against
  a capitalized-stem input like `Energy.txt`); `source` repo-relative for an
  input under the CWD; absolute + flagged for one outside it (D2).
- Existing judge pins untouched.

**Deferred to the post-calibration change, deliberately:** phrase pins on
`EXTRACTION_INSTRUCTIONS` *and* a payload-layout pin for
`build_extraction_payload` — the judge's layout pin exists because the layout
was part of what was calibrated; pinning pre-calibration wording would fence
prose the calibration loop (§6.6) is expected to rewrite.

## 9. Post-calibration obligations (recorded here so they survive the session)

1. Add the extraction phrase pins + payload-layout pin in the same change that
   records the calibration outcome (mirroring how the judge's pins landed).
2. CLAUDE.md: the calibration record — per-contract recall/precision/
   granularity, draw-stability, the verdict-stability numbers, the bias-probe
   reading, and the §6a verdict (lift / iterate / human-review policy).
   `output/` is gitignored, so the durable home for the numbers is CLAUDE.md,
   not the artifacts — record them the same session they are read.
3. Only then consider follow-ons: feeding extracted inventories to
   `fidelity_sweep.py` — which needs a correct `source` for stem keying *and*
   an inventory-aware cache: the cache key carries no inventory identity
   (§6.4), so mixing registers in one cache dir silently serves stale
   judgments; extending the tag with an inventory hash is the durable fix if
   this follow-on lands. Then promotion of reviewed extractions into
   `contracts/inventories/`, and the product surface (the UI coverage chip),
   each a separate decision.

## 10. Considered and rejected (roll-up)

New `output/inventory.py` module (D1); YAML or metadata from the LLM (D2);
LLM-assisted or fuzzy-matched calibration alignment (D5); two scripts, or a
subcommand interface (D6); any extracted-output location under `contracts/`
(one `mv` from masquerading as curated — D8 makes `output/` structurally safe
instead); promoting an LLM-call helper into `output/fidelity.py` (breaks its
purity contract — D7); retry/concurrency in the script (six sequential calls;
failure philosophy per D6); closed kind vocabulary (D4); phrase-pinning the
uncalibrated instructions (§8); a required `clause` field (forces fabricated
metadata on unnumbered contracts — D3/§5); an automated calibration pass/fail
(the human alignment reading *is* the calibration — §6a pre-commits the bar
instead, which is the part that keeps the manual verdict honest); a holistic
single-scalar judge replacing the checklist (uncalibratable — no per-item gold
to measure a judge against, no fixed denominator, folds coverage and
inventions into one number; the Cohere disqualification was only visible
because verdicts are per-item).
