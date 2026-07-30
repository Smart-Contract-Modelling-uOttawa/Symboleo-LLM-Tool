# Symboleo LLM Tool — Project Reference

## What This Tool Does

A Python CLI and FastAPI web service that:
1. Takes a `.txt` legal contract in English
2. Uses an LLM to generate one or more SymboleoAC contract(s)
3. Runs the SymboleoAC headless CLI to extract syntax **and validation** errors (Xtext parser + `@Check` rules, including the access-control layer — e.g. roles must declare `name/org/dept`, events a Role-typed `performer`)
4. Feeds errors back to an LLM for correction (bounded loop)
5. Outputs the final corrected Symboleo file(s) and a run report

---

## Stack

| Concern | Tool |
|---|---|
| Language | Python 3.11+ |
| Package manager | uv |
| Project file | pyproject.toml |
| CLI framework | Typer |
| Config format | YAML + Pydantic v2 |
| LLM abstraction | LiteLLM |
| Observability | LangSmith (opt-in) |
| Prompt templating | Jinja2 |
| Web framework | FastAPI + uvicorn |
| Linting/formatting | Ruff |
| Type checking | mypy |
| Testing | pytest + pytest-mock + httpx + pytest-cov |
| Frontend | React 19 + Vite 6 + Tailwind v4 + shadcn/ui + TypeScript |
| Frontend testing | Vitest + React Testing Library + MSW v2 |
| Type generation | openapi-typescript |

---

## Architecture

### Module Structure

```
symboleo_llm_tool/
├── cli/            # Typer entry point — thin layer only, no business logic
├── api/            # FastAPI adapter layer: routes, config_builder, job store, SSE events, request/response models, _paths.py (deployment path constants)
├── pipeline/       # Orchestration: generation stage + correction loop
├── experiments/    # Suite orchestration: run_suite() composes pipeline.run() over N configs
├── llm/            # LiteLLM-backed adapters (abstract base + concrete implementations)
├── prompts/        # PromptStrategy ABC + concrete strategies; PromptContext Pydantic model; examples.py (few-shot corpus); grammar.py (grammar resource + reserved-names derivation)
├── symboleo/       # Subprocess wrapper around the SymboleoAC headless CLI JAR
├── config/         # Pydantic config models + YAML loader (incl. SuiteConfig/Experiment)
├── output/         # Result models (PipelineResult/CandidateResult/IterationRecord/SuiteResult) + metrics.py (computed-rollup derivation) + writer.py
├── concurrency.py  # CancellationToken (linked children) + RunCoordinator — shared cancellation/pool primitives
└── resources/      # Bundled assets: Symboleo.xtext grammar file
```

### Pipeline Flow

```
Input .txt
    ↓
[Generation] LLM + PromptStrategy → N SymboleoAC candidate(s)
    ↓
[Correction loop] per candidate:
    symboleo/ wrapper → structured errors
    if no ERROR-severity issues or max_iterations reached → done
      (WARNINGs are recorded and surfaced, never fed to correction)
    else → LLM + PromptStrategy → corrected code → repeat
    ↓
[Output] timestamped directory: report.json, config.yaml, final .symboleo, optional intermediates
```

---

## Key Design Decisions

### LLM Abstraction
- **LiteLLM** handles all provider abstraction — adding a new provider is a config change, not a code change
- Do NOT use MCP for provider switching — MCP is for tool use, not provider abstraction
- API keys always via environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.), never in config files
- Every completion call is bounded by `_REQUEST_TIMEOUT_SECONDS` in `llm/litellm_adapter.py` — a total wall-clock bound, not per-attempt, replacing LiteLLM's effectively-unbounded 6000s default. A run that outlives it fails mid-loop rather than hanging

### Prompt Strategies
- `PromptStrategy` ABC with two methods: `build_generation_prompt(context)` and `build_correction_prompt(context)`
- All strategies receive a `PromptContext` parameter object — strategies read only what they need
- Strategy-specific data comes from `strategy_params` in config, passed to the strategy constructor
- Prompt text lives in Jinja2 `.j2` templates, separate from Python logic
- Grammar is baseline for all strategies — `include_grammar` is a per-stage flag, not a strategy characteristic
- Adding a new strategy: add templates to `prompts/templates/`, add a strategy class in `prompts/strategies/`, declare its `_allowed_params` if it reads any `strategy_params`, then import it and add it to the `_STRATEGIES` dict in `prompts/strategies/__init__.py`

**Available strategies:**
| Strategy | Key `strategy_params` | Notes |
|---|---|---|
| `zero_shot` | none | Baseline — grammar + contract, no examples |
| `few_shot` | `example_files: [list of names]` | Loads `contract_text`/`symboleo_code` pairs by name from the corpus (see Example Corpus) |
| `cot` | none | Adds step-by-step reasoning instructions before generation; output is still code-only (Option A) |

**CoT Option B (future flag):** Currently CoT uses Option A — the model reasons internally but outputs only code. Option B would add a `post_process_response()` hook to `PromptStrategy` so strategies can extract code from a mixed reasoning+code response, preserving reasoning in `report.json`. Deferred until research value is confirmed.

**Prompt template structure — LangGPT conventions:** All `.j2` generation and correction templates follow [LangGPT](https://arxiv.org/abs/2402.16929) module conventions. LangGPT structures prompts as labeled semantic sections analogous to OOP class definitions; empirical research shows this reduces model ambiguity about what each part of the prompt is asking and measurably improves accuracy on downstream tasks compared to unstructured prose.

Standard module order for **generation** templates:
```
# Role
## Goals
## Constraints
## Workflow        ← CoT only; omitted in zero_shot and few_shot
## Output Format   ← {% include '_output_format.j2' %}; the SymboleoAC contract structure + structural rules
## Reserved Names  ← {% include '_reserved_names.j2' %}; grammar-derived, always emitted
## Grammar         ← conditional on include_grammar flag; {% include '_grammar_section.j2' %}
## Examples        ← few_shot only
## Input
{{ contract_text }}
```
`## Output Format` carries the contract skeleton plus the structural rules (domain types defined before use, `O`-vs-`Obligation`, the reversed creditor/debtor order in `Power`, inline propositions, the `Date.add(date, amount, timeUnit)` date-arithmetic form), and is included in **both generation and correction** templates. Behavioral rules ("follow the grammar," "code only, no fences") stay in `## Constraints`; the structural shape lives in `## Output Format`. It sits after `## Workflow` and before `## Grammar`.

Our templates are a domain adaptation of LangGPT, not a literal copy: `## Output Format`, `## Grammar`, and `## Input` are custom modules a code generator needs, and the persona-bot modules (`## Profile`, `### Skills`, `## Initialization`) are dropped. The rule when editing templates: preserve the relative order of the shared modules (Role → Goals → Constraints → Workflow → terminal input) and insert custom modules between Workflow and the terminal input.

**Why correction also carries `## Output Format` (and not just generation):** a feedback-only correction prompt — raw grammar + error list without the structural task spec — caused the model to over-edit valid lines that had no listed error. Two coordinated fixes: include `## Output Format` in correction for the same structural grounding generation has, and harden the first `## Constraints` bullet to forbid editing any line without a listed error. The grounding must be re-included each call because `LLMAdapter.generate(prompt: str)` is stateless single-shot, not conversational.

Standard module order for **correction** templates:
```
# Role
## Goals
## Constraints
## Workflow        ← CoT only; omitted in zero_shot and few_shot
## Output Format   ← {% include '_output_format.j2' %}; same structural grounding as generation
## Reserved Names  ← {% include '_reserved_names.j2' %}; adds the rename-is-a-required-fix clause
## Grammar         ← conditional on include_grammar flag; {% include '_grammar_section.j2' %}
## Current Contract
{{ current_code }}
## Errors to Fix
{{ errors }}
```

Shared partials are `{% include %}`d at the appropriate position within this structure: `_system_header.j2` provides the `# Role` line, `_grammar_section.j2` provides the `## SymboleoAC Grammar Reference` block (with its own heading), `_output_format.j2` provides the `## Output Format` section (with its own heading) in both generation and correction templates, `_reserved_names.j2` provides the `## Reserved Names` section (with its own heading, also in both), and `_placeholder_guidance.j2` provides the placeholder constraint bullet within `## Constraints`. The `## Workflow` section is intentionally placed before `## Grammar` — consistent with the progression above (the `## Workflow` LangGPT module precedes the custom reference modules), even though it means zero_shot and CoT correction templates have different static prefixes before the grammar (relevant only if prompt caching is added; see Known Issues).

**Partial loading — the `_`-prefix is load-bearing:** `build_jinja_env(*template_names)` in `prompts/base.py` automatically loads *every* `_`-prefixed `.j2` file in `templates/` into the env, then adds the strategy-specific templates named in the call. A strategy file therefore lists only its own templates (e.g. `build_jinja_env("zero_shot_generation.j2", "zero_shot_correction.j2")`) and never re-lists partials. Adding a new shared partial is a single file drop in `templates/` — no strategy file changes. Which partials a strategy *uses* is controlled solely by the `{% include %}` directives in its own templates; a partial that is loaded but not included renders nothing, so per-strategy partial selection lives in the templates, not in the env. Partials are shared, strategy-invariant content by design — anything that varies by strategy (CoT's `## Workflow`, few_shot's `## Examples`) belongs in the strategy template, not a partial.

**Why LangGPT over DSPy now:** DSPy automatically optimizes prompt text but requires labeled (contract_text → correct Symboleo) training data. LangGPT provides a principled hand-crafted baseline while that dataset accumulates from successful runs. See Future Directions — DSPy.

### Example Corpus (few-shot)
- **`example_files` holds example *names*, never paths** — one contract across every entry point (CLI config, suite file, API request). A config means the same thing on any machine and survives a round trip through a suite file.
- **Resolution happens at point of use** (`prompts/examples.py`), not in the config loader. Resolving during load would leave the in-memory model holding machine-specific paths, so everything that dumps a config — the run record, `suite.yaml`, the export — would emit them again. That is self-defeating for a file whose purpose is to be portable.
- `examples.py` owns both directions: `load_example(name)` for `FewShotStrategy`, `list_example_names()` for `GET /options`. Two consumers is why this is a module rather than a private helper inside `few_shot.py` — the alternative strands the directory constant in `api/_paths.py` for the options route, splitting ownership of the corpus across two modules. The directory itself is private (`_examples_dir`): the module's contract is the two public functions, and exposing the directory invites a third consumer to `glob` it and re-create the split.
- The corpus root defaults to a CWD-relative `examples/` (matching Docker's `WORKDIR /app` + `./examples:/app/examples:ro` mount) and is overridable with `SYMBOLEO_EXAMPLES_DIR`, so the CLI works outside the repo root. Read per call, not captured at import: import-time capture pins a long-running API process to its startup value and lands before the CLI's `load_dotenv()`, so a `.env` entry would never apply.
- **Env var, not a config field** — even though `symboleo.jar_path` and `output.directory` *are* paths in the config schema. Those are a per-run choice and a fixed default respectively; the corpus root is neither. A config field would be dumped into `report.json`/`suite.yaml`/the export, putting a machine-specific path into the artifact whose whole purpose is portability, and a corresponding `StageRequest` field would let any browser client repoint the server's corpus. The repo therefore has two conventions for "filesystem location" — knowingly, on the secrets-and-deployment-facts → env, research-variables → YAML line (cf. `CORS_ORIGINS`).
- A path-shaped entry (contains a separator, or ends `.yaml`) is rejected with a message naming the bare name to use. Rejecting separators is also the **containment boundary**: `example_files` reaches `load_example` unfiltered from an HTTP body, and `<corpus>/../secret.yaml` would otherwise read an outside file into the prompt — so supporting subdirectories later needs a containment check, not just a wider enumeration. Deliberately **no** dual-accepting shim: accepting both names and paths would reinstate two contracts for one field.
- **Corpus content teaches SymboleoAC idiom, not text→Symboleo fidelity.** The curated example models pass the JAR, but a blind audit failed all four against their source texts — see Known Issues, *Convergence ≠ fidelity*. Do not treat an example as a gold semantic mapping.

### Config Schema
- Generation and correction each have their own `StageConfig` (independent LLM + strategy per stage)
- **Config input is closed.** Every config model inherits `_StrictModel` (`extra="forbid"`) in `config/models.py`, so an unknown or misspelled key fails the load at whatever level it appears rather than falling back to the default. This is a research data-integrity rule, not a UX nit: `report.json` records the config *as loaded*, so a silently-ignored `temprature` would leave no trace in the durable artifact either. Stated on the shared base so a new config model cannot opt out by omission. **Scoped to config files** — the API request models (`api/models.py`) stay `extra="ignore"` deliberately, because there a strict model turns frontend/backend version skew into a 422, a different risk profile from a hand-edited research config.
- `strategy_params: {}` dict on each stage — `dict[str, Any]`, so `extra="forbid"` cannot see inside it. Each `PromptStrategy` therefore declares `_allowed_params` and `PromptStrategy.__init__` rejects unknown keys; a strategy's own semantic checks (e.g. `few_shot`'s list/emptiness rules) stay in that strategy
- `include_grammar` is a per-stage research flag (not a strategy characteristic). It gates the grammar **text**, not grammar-*derived* guidance: `## Output Format` and `## Reserved Names` both ship regardless, because with the grammar omitted the model knows less about the language and needs that grounding more, not less
- `output.save_intermediates` saves each iteration's `.symboleo` output — off by default
- `stop_on_first_convergence` flag — default `false` (full research data), flip to `true` to save tokens
- Input file is a CLI argument, not a config concern
- CLI override support (`--set key=value`) for quick experiments — deferred (see Known Issues)

### Convergence Semantics (ERROR-gated; warnings surface but never block)
`converged` means the final code has zero **ERROR-severity** issues. WARNINGs (e.g. the AC validator's liberal W13 unused-declaration class) are recorded unchanged in `report.json`/`error_history` and surfaced to the user, but **never fed to the correction prompt**. `_blocking()` in `pipeline.py` filters at the pipeline — not in `wrapper.validate()`, so no research data is lost — and `SymboleoIssue.is_error` is the single home for the severity predicate.

**Surfacing:** the CLI progress line prints both counts and the `run` summary table has a Warnings column (the `suite` table does not — warnings are per-candidate); `CandidateResult.final_warning_count` (a `@computed_field` delegating to `metrics.py`, counting non-ERROR issues in the final iteration) backs the frontend's warnings chip; `ProgressEvent.error_count` counts blocking errors only.

**Evidence:** settled empirically by an archive census of 82 candidates (2026-07). At matched difficulty, warning-laden correction prompts eliminated remaining errors at 16% vs 62% for error-only prompts, and blew up (error count increased) 37% vs 0%. Warnings were fixed incidentally alongside errors 85% of the time, so not prompting on them does not produce warning-swamped output.

### Multi-Candidate Behavior
- Success = any candidate converges (one correct output is sufficient — see Convergence Semantics above)
- Candidates run sequentially on the standalone path (CLI, single-run API); within a suite with `max_concurrency > 1` they run concurrently on the shared pool, with sibling cancellation on first convergence
- `stop_on_first_convergence: false` by default to preserve full research data

### Output Format
- Timestamped run directories (e.g., `output/run_20260526_143022/`) — prevents experiment overwrites
- Each run directory contains: `report.json`, `config.yaml` (copy), `contract_final.symboleo`, optionally `intermediates/`
- Multi-candidate runs use a `_candidate_N` suffix consistently: `contract_candidate_0_final.symboleo`, `intermediates_candidate_0/`
- `report.json` captures: success, iterations per candidate, full error history per iteration
- Console prints a human-readable summary; full detail is in `report.json`

### N×M Problem (Strategy × Provider)
- LLM adapters and prompt strategies are **two independent hierarchies** — they compose, not inherit
- Never let prompt strategies become provider-aware — that creates N×M classes
- Prompt strategies produce text; LLM adapters handle provider-specific formatting

### Entry Point Architecture
- The pipeline core is I/O-agnostic: `pipeline.run(contract_text: str, config: PipelineConfig) → PipelineResult`
- The CLI is a thin adapter: parse args → read file → call pipeline → format output
- The API is a thin adapter: parse request body → call pipeline → stream SSE events
- Both entry points call the same core with no core-layer changes
- Config as Pydantic models means the same object can be populated from YAML or a JSON request body
- **`ProgressCallback` type:** `Callable[[int, int, list[SymboleoIssue], int, int], None]` — args are `(candidate_id, iteration, errors, total_candidates, total_iterations)`. The pipeline passes `total_candidates` and `total_iterations` so callers (CLI, API) do not need to reach into config themselves.
- **`api/config_builder.py`** separates config construction (provider resolution, `StageConfig` assembly) from routing logic. Functions raise `ValueError`; `routes.py` converts these to `HTTPException(422)` in a single `try/except` block alongside strategy validation. It passes `strategy_params` through untouched — see Example Corpus for why resolution does not belong here.
- **`api/_paths.py`** holds the deployment path constants. All modules in `api/` that reference filesystem paths import from here — never inline `Path("configs/ui_config.yaml")` elsewhere. Scoped to paths the *deployment* owns; a path that belongs to a domain concept lives with that concept.

### Experiment Suites (Multi-Config Comparison)
- A **suite** runs one contract against N named configurations (`Experiment` = name + full `PipelineConfig`) and compares them; convergence/metrics are per-experiment.
- **`experiments/runner.py` composes `pipeline.run()` — it does not modify it.** `run_suite` runs experiments sequentially at `max_concurrency: 1`, concurrently otherwise (default 2, clamped `[1, 8]`): an experiment driver pool plus one shared bounded candidate pool, with cooperative cancellation via `concurrency.py`'s `CancellationToken`/`RunCoordinator` (rationale in [docs/suite-concurrency-design.md](docs/suite-concurrency-design.md)); a per-cell callback adapter prepends `experiment_index` so the pipeline's `ProgressCallback` signature stays untouched. Same altitude discipline as the CLI/API → `pipeline.run` relationship — if you find yourself editing `pipeline.py` for suite logic, it's at the wrong altitude.
- **Single-contract by design (v1).** One contract because config comparison is only apples-to-apples with the contract held as the control variable.
- **Comparison rollups are `@computed_field`s on the result models, not stored state.** The stored atomic facts are per-iteration `usage`/`errors` and per-candidate `converged`/`iterations_used`/`final_code`. Token/cost totals (`total_tokens`/`total_cost_usd` at candidate → pipeline → suite) and `iterations_to_convergence` are `@computed_field`s on the models that delegate to `output/metrics.py` (the derivation lives there so `models.py` stays data-shape declarations; `metrics.py` imports the model types only under `TYPE_CHECKING` to avoid a runtime import cycle). They serialize into `report.json`, the API response, and the generated `schema.d.ts` from a single definition — every consumer (durable artifact, CLI, frontend) reads the same numbers, and adding a rollup never requires re-running a suite or storing redundant state. `total_cost_usd` is `None` (not `0.0`) when no iteration reported a cost, so the UI can show "unknown" as a dash. The frontend only *formats* the rollups (`lib/tokens.ts`). Config/result models live in their concern packages (`config/models.py`, `output/models.py`), not a feature package — only the orchestrator gets the new `experiments/` package.
- **API & shared machinery:** `POST /suites` + `GET /suites/{id}/stream` (one **multiplexed** SSE stream — `ProgressEvent` carries `experiment_index`, new `SuiteCompleteEvent` embeds `SuiteResult`). The multiplexing (N→1) is server-side; the client demultiplexes by the tag. The single-run and suite endpoints share `build_pipeline_config` and `_stream_job`; `Job` is generic over its result type; `RunSettings` is the shared base of `GenerateRequest`/`ExperimentRequest`; `ContractText` is a reusable validated type.
- **CLI suite command:** `symboleo-tool suite <contract.txt> --config suite.yaml` — a second Typer subcommand alongside `run` (`run` must be named explicitly). It's a thin adapter, same altitude as the API: `load_suite_config(path, contract_text)` (in `config/loader.py`) parses the file and binds the CLI-supplied contract, then it calls the **unchanged** `run_suite`. The suite **file schema is the nested/explicit `SuiteConfig`** (each experiment carries a full `PipelineConfig` with explicit provider — same lineage as the single-run config; DRY with YAML anchors), **minus `contract_text`**, which is a CLI arg and is *rejected* if present in the file (never ambiguous). `write_suite_results` (in `output/writer.py`) persists a `suite_*/` dir: `suite_report.json`, a reloadable `suite.yaml` (contract stripped), a `summary.csv` mirroring the frontend's `buildSummaryCsv` columns, and one index-prefixed, name-slugged subdirectory per experiment via the shared `_write_run` helper (extracted from `write_results` so both writers emit the identical single-run layout). Concurrency stays entirely inside `run_suite`; the CLI's only concurrency contact is its progress callback, which fires from worker threads when `max_concurrency > 1` — kept a thin, thread-safe append print (interleaving accepted; no buffering/reordering, which would re-coordinate concurrency at the wrong altitude).
- **Suite export (`POST /suites/export`)** emits that same file format, so a comparison built on `/experiments` can be re-run headlessly with the CLI. **Server-side, not a TypeScript builder**, because our own `load_suite_config` re-parses the result — when one system both writes and reads a format, the producer must derive from the models that parse it, or the schema lives twice in two languages. (`buildSummaryCsv` is client-side and is *not* a precedent: nothing parses that CSV back.) It returns JSON `{filename, content, warnings}` rather than `text/yaml` so the route types cleanly in the OpenAPI schema; the frontend hands `content` to the existing `triggerDownload`. `warnings` carries the same param advisories `POST /suites` returns — an export that emits a temperature the model rejects must not be quieter than a run that would.
- **Both suite endpoints share `build_suite_config`** (`api/config_builder.py`), so an export is built through the same validated path as a run and cannot emit a config *this server* would reject. Not a guarantee for every host: `few_shot` example names resolve against this server's corpus, so a CLI machine lacking them still rejects the file.
- **One serializer, two policies: `config/loader.py::dump_suite_file(suite, *, minimal)`.** It lives beside `load_suite_config` because "which keys the file carries" is one fact — the contract is dropped here precisely because the loader rejects it. `minimal=False` (the run record in `output/suite_*/suite.yaml`) keeps every value the run used, since omitting `max_iterations: 3` merely for matching today's default would make the artifact replay a *different* run after a default change. `minimal=True` (the export) emits only what was configured, which is also what drops the server's `jar_path`/`output.directory` and makes the file portable. Share the serializer; never unify the policies.
- **Deferred (future stages):** multiple contracts, a server-side suite archive, sweep-axis *config-file* expansion (the frontend axis expander covers the UI case). Per-experiment and summary-CSV downloads are built client-side, matching the single-run page — the API is a live view, not an archive. Concurrency & cancellation are implemented — see [docs/suite-concurrency-design.md](docs/suite-concurrency-design.md).

### Java Dependency (Packaging)
- **Tier 1 (dev):** Bundle JAR inside the package, require Java 17+ as a system prerequisite (JAR compiled with class file version 61.0). Check for Java at startup and fail with a clear, actionable error message.
- **Tier 2 (release):** Docker image bundling JRE + JAR + Python tool — eliminates the Java prerequisite **for the API only**. `Dockerfile` and `docker-compose.yml` are in the project root. The CLI is intentionally not containerized: mounting a contract file, config, and output directory as volumes for a one-shot command is more friction than simply requiring Java 17 of a technical user. CLI users run `uv run symboleo-tool` directly with Java 17 on their PATH.
- **Running the API from Docker:** Preferred: `docker compose up symboleo-api` (handles build, volumes, and env automatically). Standalone: `docker build -t symboleo-llm-tool .` then `docker run -p 8000:8000 --env-file .env -v ./configs:/app/configs:ro symboleo-llm-tool`. API keys must be passed via `--env-file .env` or `-e ANTHROPIC_API_KEY=...`. `configs/` is intentionally not baked into the image — `ui_config.yaml` must be mountable at runtime so model lists can be updated without a rebuild. On startup, the lifespan handler logs a friendly `http://localhost:8000` URL alongside uvicorn's own `0.0.0.0:8000` message (which reflects the internal bind address, not the host-accessible URL).
- **JAR naming convention:** The JAR is stored as `lib/symboleo-cli.jar` (no version in the filename). When updating the JAR, replace the file in place — the version lives in the file content and git history, not the filename. This keeps the default `jar_path` in `SymboleoConfig` stable across releases.
- **JAR/grammar coupling:** `lib/symboleo-cli.jar` and `symboleo_llm_tool/resources/Symboleo.xtext` must always be updated together in the same commit. If the SymboleoAC language evolves and only the JAR is replaced, the LLM generates code against the old grammar while the validator enforces new rules — the correction loop will spin through all iterations without converging. Treat them as a single atomic change.
- **JAR provenance & rebuild:** The jar is a fat/executable build of the `cli/` Maven module in [SymboleoAC-IDE](https://github.com/Smart-Contract-Modelling-uOttawa/SymboleoAC-IDE) — the **access-control** Symboleo, distinct from the non-AC [Symboleo-IDE](https://github.com/Smart-Contract-Modelling-uOttawa/Symboleo-IDE) (both ship a `Symboleo.xtext` and a generically-named `symboleo-cli` jar, so provenance is the *repo*, not the filename). To refresh it against the current validator: clone `SymboleoAC-IDE` at `main`, then `cd cli && JAVA_HOME=$(/usr/libexec/java_home -v 17) mvn -B clean package` → `cli/target/symboleo-cli-*-all.jar`, and copy it over `lib/symboleo-cli.jar`. Requires **JDK 17 + Maven 3.8+; no Eclipse** — the Xtext-generated `src-gen`/`xtend-gen` are committed upstream and the Maven build consumes them directly (the `cli/README` Eclipse/MWE2 bootstrap is only needed when those generated sources are absent or the grammar itself changed). Because "converged" means "passes the AC validator," refreshing the jar changes what every run converges to — do it on a branch and re-verify the integration fixtures.

### Frontend Architecture
- Four-route SPA with React Router: `/` (single-run config) + `/runs/:id` (single-run results), and `/experiments` (suite config — one contract + N experiment cards) + `/suites/:id` (suite comparison results).
- **Shared config/results/stream modules:** `components/config/` (`ContractUpload`, `StageSection`, `AdvancedSection`, `stageForm.ts`) is the one pipeline-config form, used by both `ConfigPage` and each experiment card. The suite page also has an **axis expander** (`AxisExpander.tsx` + the pure `axisExpand.ts`): it bulk-generates experiment cards by enumerating one categorical generation axis (strategy or model) over selected values — auto-named, everything else cloned from the first card — producing the same `ExperimentFormValues` the manual Add/Duplicate flow does, so the submit path is untouched. It's purely a frontend authoring convenience (no API/backend change); `few_shot` is excluded from the strategy axis since it needs per-card example files. `hooks/useEventStream.ts` is the shared SSE lifecycle; `useStream` and `useSuiteStream` are thin wrappers differing only in URL + result type. `components/results/` (`CandidateItem` + `download.ts`) renders per-candidate detail on both results pages. `lib/progress.ts` (`formatProgressLabel`) is the single place interpreting the pipeline's `iteration` field for the live counter — iteration 0 is the generation pass, 1..max are corrections (never add `+1`). `lib/tokens.ts` is formatting-only (`formatTokens`/`formatCost`) — the numeric token/cost rollups are `@computed_field`s on the backend models (see Experiment Suites), not derived client-side.
- **Generated types:** `openapi-typescript` generates `frontend/src/api/schema.d.ts` from the live OpenAPI schema. `frontend/src/api/types.ts` re-exports all frontend-relevant types from this generated file — never hand-write interfaces that mirror backend Pydantic models. Run `npm run generate-types` from `frontend/` whenever backend Pydantic models change; requires the API server running at `localhost:8000`. **`schema.d.ts` is committed (tracked), not gitignored** — the frontend CI typecheck job runs `tsc` in a Node-only checkout and can't regenerate it from the backend, so a missing file fails with `TS2307`; after changing backend models, regenerate **and commit** it in the same change (a stale schema fails `tsc` as soon as the frontend uses a new field). The SSE endpoint's `response_model` hack (see Known Issues) is what makes the SSE event types appear in the schema.
- **`StreamStatus` type union:** `'connecting' | 'running' | 'reconnecting' | 'complete' | 'error'` is defined as a TypeScript string union in `useEventStream.ts`. Do not extract these values into a constants object — the union type itself provides compile-time exhaustiveness checking, making a separate constants file a second source of truth with no safety benefit.
- **`makeNullableUpdater<T>` factory:** module-level generic in `components/config/stageForm.ts` that captures the `prev => prev ? updater(prev) : prev` null-guard pattern. Use it whenever a top-level state type is `T | null` and child handlers only need to update non-null state.
- **Naming convention — UI vs API layer:** API-layer functions in `api/client.ts` use domain vocabulary (`generate`, not `submitGenerate`). Page-level types that hold raw form input values use a `*FormValues` suffix (`StageFormValues`, `AdvancedFormValues`) to distinguish them from API contract types (`StageRequest`). `buildStageRequest(StageFormValues): StageRequest` is the explicit translation point between the two layers — it parses strings to typed values and handles conditional fields.
- **SSE error discrimination in `useEventStream`:** `hasEverConnected` flag distinguishes a never-connected failure (fail immediately — likely a 404 or server down) from a mid-stream drop (retry up to `MAX_RETRIES=3`). The browser handles reconnect timing automatically via `EventSource`; the hook only tracks retry count and sets `'reconnecting'` status between attempts.
- **Frontend type checking and linting:** mypy and ruff do not cover `frontend/`. TypeScript (`tsc`, run as part of `npm run build`) handles type safety; ESLint handles linting (`npm run lint`). Both are separate from the Python CI checks.

### Testing Strategy
- **Unit tests:** Mock both LLM adapter and CLI subprocess wrapper. Focus on pipeline loop logic (iteration bounds, early stopping, error passing).
- **Integration tests:** Run the real JAR against known fixture files (valid `.symboleo`, invalid `.symboleo` with known errors). `test_valid_contract_returns_no_errors` asserts no **ERROR-severity** issues (benign unused-declaration WARNINGs are allowed — a valid AC contract can still emit them). Live LLM adapter tests optional/skippable in CI (`pytest -m "not live"`).
- **No full e2e in CI** — manual smoke test before releases.
- **CI pins the formatter but keeps the type-checker live — deliberately split.** `ruff` is a locked dev dependency (`pyproject.toml` floor, one exact version in `uv.lock`), and every Python job runs `uv sync --extra dev --locked` — `--locked` fails the job if `uv.lock` drifts from `pyproject.toml` rather than silently re-resolving to a newer `ruff` whose version-dependent `format` output could redden an unrelated PR. A `ruff` bump is then a reviewable `uv.lock` diff, never an ambient CI event. The frontend gets the same guarantee for free from `npm ci`. **`mypy` is intentionally *not* in the lock:** the typecheck job runs `uv run --no-sync --with mypy mypy symboleo_llm_tool`, overlaying the latest `mypy` on the locked project env (so imports and `types-*` stubs still resolve). Rationale: a formatter's drift only reflows untouched code, but a type-checker's drift usually surfaces a real bug worth adopting — pin the noise-generator, keep the bug-finder live. Consequence: run mypy locally the same way (`uv run --with mypy mypy …`), and a new `mypy` release can red an untouched PR — that is the intended signal, not a regression. Regenerate the lock (`uv lock`) alongside any `pyproject` dependency edit, or `--locked` reds the PR.
- `tests/fixtures/` contains: sample `.txt` contract, known-valid `.symboleo` (the canonical AC `MeatSale` — roles declare `name/org/dept`, events a Role-typed `performer`, plus an `ACPolicy` with `Grant`/`Revoke` rules), known-invalid `.symboleo` (the same contract with one deliberate `endContrct` typo). A fixture that omits the access-control attributes will fail the validator's `@Check` rules — keep new "valid" fixtures AC-complete.
- **`tests/helpers.py`** — shared `make_issue()` / `make_usage()` / `make_generation()` factories with keyword-only defaults. Unit tests that need issue/usage/generation factories import from here; no per-file `_make_error()` helpers.
- **API layer tests** — `tests/unit/api/` contains `conftest.py` (fixtures), `test_routes.py` (single-run endpoints, the `_stream_job` attach/detach stamping, and the `_run_pipeline` cancel-token bridge), `test_suites.py` (suite endpoints + the `_run_suite` async bridge), `test_export.py` (the suite-file export, round-tripped through `load_suite_config` rather than against a golden file), `test_jobs.py` (`cleanup_expired()` and `cancel_abandoned()`), and `test_config_builder.py`. Uses `fastapi.testclient.TestClient` (sync) with a bare `FastAPI` app including `routes.router` directly (bypassing the lifespan). `conftest.py` `autouse` fixture calls `init_router(TEST_UI_CONFIG)` and `reset_store()` to isolate shared global state between tests. Happy-path POST tests patch `_run_pipeline` with `AsyncMock` to avoid real pipeline execution — which is exactly why the request→`PipelineConfig` translation is tested directly in `test_config_builder.py` rather than through the endpoints, where it is invisible behind a 200.
- **`tests/unit/test_writer.py`** — covers `write_results()` (timestamped directory naming, `report.json`/`config.yaml` content, single vs. multi-candidate filename suffixes, `save_intermediates` layout) and `write_suite_results()` (suite dir layout, per-experiment subdirs, reloadable `suite.yaml`, summary-CSV columns).
- **`tests/unit/test_result_metrics.py`** — covers the `@computed_field` rollups on the result models (token/cost totals at candidate/pipeline/suite level, the `None`-cost-vs-`$0.00` distinction, `iterations_to_convergence`, `final_warning_count`, and that they serialize into the dump).
- **Coverage:** run with `uv run pytest --cov=symboleo_llm_tool --cov-report=term-missing`. Suite layer: `tests/unit/test_suite_runner.py` covers `run_suite()` against a mocked `pipeline.run`; `tests/unit/test_concurrency.py` covers the `CancellationToken`/`RunCoordinator` primitives. Intentionally untested: `app.py` lifespan (integration-level) and `litellm_adapter.py` live LLM calls — `test_litellm_usage.py` covers the rest of that adapter against a fake response (token/cost extraction, the omit-temperature-when-unset guard, the always-sent request timeout, and the empty-response error).
- **Frontend tests (Vitest + RTL + MSW):** Vitest is configured in `frontend/vite.config.ts` (`test` block with `environment: happy-dom`) — shares the Vite config and alias resolution. React Testing Library for component rendering/interaction. MSW v2 (`msw/node`) stubs the API endpoints at the network level; default handlers in `frontend/src/test/handlers.ts`, server instance in `frontend/src/test/server.ts`, global setup (jest-dom matchers + MSW lifecycle) in `frontend/src/test/setup.ts`. Test files are co-located with source files (`*.test.tsx` / `*.test.ts`). Run with `npm run test` or `npm run test:coverage` from `frontend/`. Test files: `App.test.tsx`, `ConfigPage.test.tsx`, `ResultsPage.test.tsx`, `ExperimentsPage.test.tsx`, `SuiteResultsPage.test.tsx`, `hooks/useEventStream.test.ts`, `hooks/useStream.test.ts`, `hooks/useRunCancel.test.ts`, `hooks/useOptions.test.ts`, `lib/progress.test.ts`, `lib/tokens.test.ts`, `components/config/axisExpand.test.ts`, `components/config/stageForm.test.ts`, `components/results/download.test.ts`. `SuiteResultsPage` mocks `useSuiteStream` the same way `ResultsPage` mocks `useStream`.
- **Frontend test fixtures:** `frontend/src/test/handlers.ts` exports `TEST_RUN_ID` and `MOCK_OPTIONS` as named constants — shared test plumbing values used across multiple test files. Concrete assertion values (UI strings, strategy names) are intentionally repeated as literals in each test file, not imported from shared constants, so that a typo or rename in production code causes a test failure rather than silently passing.
- **Frontend test gotchas:** RTL does not auto-cleanup in Vitest (unlike Jest) — `cleanup()` must be called explicitly in `afterEach` (done in `setup.ts`). `setup.ts`'s `afterEach` also calls `resetOptionsCache()` — without it the `useOptions` module cache leaks across tests, so a test overriding `GET /api/options` would be served an earlier test's payload. `userEvent.click()` on `type="submit"` buttons does not trigger form submission in happy-dom — use `fireEvent.submit(form)` instead. happy-dom has no `EventSource`, which is handled at two levels: page tests mock the wrapper hook (`vi.mock('@/hooks/useStream')` in `ResultsPage.test.tsx`), while the stream lifecycle itself is tested in `useEventStream.test.ts` by installing a stub class with `vi.stubGlobal('EventSource', ...)` — reach for the stub rather than adding another wholesale mock. `vi.hoisted()` is required to declare mock functions (e.g. `mockNavigate`) before the hoisted `vi.mock()` factory runs. MSW `server.use()` handler overrides work reliably in `render`-based component tests but not in `renderHook` tests, so hook-level tests stub the dependency directly (the global `EventSource`, or `vi.mock('@/api/client')`) instead of going through MSW.
- **Frontend E2E (future):** If a regression suite for the full generate→stream→display flow becomes valuable, add **Playwright** — native SSE support via `page.route()` and first-class Vite integration. Not in CI for now; manual smoke test before releases. No LLM API costs required — Playwright can mock the backend entirely.

### Observability
- LangSmith is opt-in via `observability.langsmith.enabled: false` default
- Tracing applied conditionally at adapter construction time — `tracing_enabled` flows from `pipeline.run()` → `create_adapter()` → `LiteLLMAdapter.__init__()`. Only `LiteLLMAdapter` is traced; mock adapter is not.
- `observability.langsmith.project` controls the LangSmith project — the CLI sets `LANGSMITH_PROJECT` and `LANGCHAIN_TRACING_V2` env vars from config at runtime. `.env` only needs `LANGSMITH_API_KEY`.
- **Optional dependency pattern in CLI:** `langsmith` is guarded by a module-level `try/except ImportError`. A missing package causes a fatal error only if `observability.langsmith.enabled: true` is set — separating "package not installed" (config error) from runtime flush failures (warn and continue). Do not use deferred imports inside `except Exception` — that conflates both failure modes.
- **Data model consistency rule:** data passed between layers uses Pydantic `BaseModel`; internal service-object bundles (e.g., `_RunContext` in `pipeline.py`) use `@dataclass(frozen=True)`. `_RunContext` is intentionally flat (individual scalar fields, not a nested `PipelineConfig`) — `run()` is the translation site from nested config to flat execution bundle, eliminating LoD chain access through the context in downstream functions.

---

## Known Issues / Future Flags

### Run records predating the ERROR-gated convergence fix are not comparable
`report.json` carries no schema version, and runs recorded before convergence became ERROR-gated (see Convergence Semantics) used all-issues convergence — a pre-change `converged=false` may be a warnings-only, ERROR-free contract. Do not compare convergence rates across that boundary.

### `jar_path`/`output.directory` serialize with Windows backslashes (run records not cross-platform)
`SymboleoConfig.jar_path` and `OutputConfig.directory` in `config/models.py` are plain `Path` fields with no custom serializer, so `model_dump(mode="json")` renders them via `str()` — on Windows that yields `lib\symboleo-cli.jar`. A backslash path in YAML is **not portable**: it reloads as a literal one-segment filename on POSIX. It reloads fine on Windows, which is why the bug stays latent.

It manifests only in the **full-dump run records**: `output/run_*/config.yaml` and the per-experiment `config.yaml` inside a suite dir (via `_write_run` in `output/writer.py`), plus `output/suite_*/suite.yaml` (via `dump_suite_file(suite)` at the default `minimal=False`). **The suite export is already immune** — it calls `dump_suite_file(minimal=True)` → `exclude_defaults=True`, which drops `jar_path` (a default value) entirely. So a run recorded on Windows cannot be replayed on Linux/Mac; an export can.

**Planned fix (deferred; own PR):** add a Pydantic `field_serializer` returning `Path.as_posix()` on the two `Path` fields, so *every* dump is portable regardless of which writer calls it (rather than patching each writer). Verified by probe that `as_posix()` yields `lib/symboleo-cli.jar` and round-trips correctly on Windows. A round-trip test (dump on the current platform → `load_config`/`load_suite_config` → assert the path reloads) is the fence.

### CLI suite validation is late — tokens can be spent before a bad experiment is caught
In a CLI suite, an invalid strategy name or `strategy_params` key in experiment N surfaces only when that experiment *starts* running — after experiments 1..N-1 have already spent LLM tokens. The API does not have this gap: `build_pipeline_config` (in `api/config_builder.py`) instantiates each stage's strategy up front for every experiment before any job starts, so a bad one is a 422 before the first token. **Planned fix (deferred):** extract a `validate_experiments(config)` the CLI `suite` command calls right after `load_suite_config`, mirroring the API's fail-fast. This is a pre-existing *class* of late detection (an unknown strategy name and a missing few-shot example already behave this way), so the fix should cover the class, not just `strategy_params`.

### Grammar Context Size
The full Xtext grammar may push against LLM context window limits or significantly increase token costs across many iterations. Starting point is full grammar injection; selective/relevant excerpt injection is a future optimization.

`## Reserved Names` adds a further **~300 tokens to every call**, both stages, unconditionally (measured: a zero-shot generation prompt goes ~4,600 → ~4,900 tokens with the grammar on, ~1,000 → ~1,300 with it off). That is a modest surcharge on a grammar-on prompt but ~30% on a grammar-off one, which is the arm to watch if the `include_grammar: false` comparison starts looking token-bound.

### Xtext Meta-Notation Leakage
We inject the raw `Symboleo.xtext` grammar verbatim ([_grammar_section.j2](symboleo_llm_tool/prompts/templates/_grammar_section.j2) renders it). Xtext is a parser-**generator** notation, and the model cannot reliably separate its meta-notation from the object-level SymboleoAC it should produce — so the notation *leaks into the output* (e.g. `'days'` instead of bare `days`, `Obligation('O')` reproduced from the `('O' | 'Obligation')` alternation, grammar rule names used as surface constructs). This is distinct from **Grammar Context Size** above (a token-budget concern); this is *format confusion*.

**Fixes in place:**
- A scoped Xtext-notation explainer in `_grammar_section.j2` supplies the translation rules (single-quoted literals → emit unquoted, the `STRING` terminal → a quoted value, `ID` → a bare name, `CapitalizedNames` → rule names, etc.). Scoped to **notation** (Xtext-level, grammar-agnostic, ~150 tokens), not grammar-specific rules; in the shared partial so generation and correction both inherit it.
- A positive form anchor for `Date.add(date, amount, timeUnit)` in `_output_format.j2`, covering a *leaf construct* the structural rules didn't otherwise specify (the model had improvised wrong forms like `Date(effDate) + delDueDateDays days`). Leaf-construct forms are grammar-specific *rules*, so they belong in `## Output Format`, not the notation explainer.

**Leaf-construct policy (altitude tripwire).** The `Date.add` anchor is a targeted n=1 fix. Rule of three: one broken leaf construct → a targeted bullet; a second/third → generalize. Do **not** let `## Output Format` become a hand-maintained grammar mirror. The generic escalation is a grammar-derived construct-signature reference (auto-derived from the grammar, zero-drift) or few-shot (deepest, but a strategy-level lever kept out of the shared baseline). A related but separate failure — reserved keywords used as *identifiers* — is tracked under *Reserved grammar keywords used as domain type names* below; it prescribes the same grammar-derived escalation but does not increment this counter.

**Deferred — message enrichment.** The JAR's cryptic error messages (`"no viable alternative at input ''days''"`, validator crashes) are a plausible limiter for errors the notation explainer doesn't ground. If pursued, the better fix is **upstream** in SymboleoAC-IDE (Xtext `ISyntaxErrorMessageProvider`, `@Check` messages) than a downstream enrichment layer, since we consume the JAR as a black box.

**Methodology — compare prompts at low temperature.** An earlier temp-0.7 default produced run-to-run generations too variable to attribute prompt effects; temp 0.2 (the form seed and [configs/openai.yaml](configs/openai.yaml)) collapsed the variance. High-temperature single samples measure sampling noise, not the prompt.

### Reserved grammar keywords used as domain type names (unrecoverable plateau)
Models name domain types after words the grammar reserves — `Asset`, `Event`, `Role`, `Contract`, `DataTransfer` (the base types, from the `OntologyType` rule) and the state literals `Suspension`, `Active`, `InEffect`, `Violation`, … (the `PowerStateName`/`ObligationStateName`/`ContractStateName` rules). Xtext lexes those as keyword tokens everywhere, so `Asset isAn Asset with …` cannot parse.

The damage is not the mistake but the **irrecoverability**: it surfaces as `mismatched input 'Asset' expecting 'endDomain'`, which names neither the offending identifier nor the rule, so the model rewrites structure instead of renaming the type and the correction loop plateaus at 1 ERROR until `max_iterations`. Observed on both Cohere models against `tests/fixtures/sample_contract.txt` (2026-07-28) — `command-r-08-2024` on `Suspension`, `command-a-03-2025` on `Asset` — each stuck for all 3 iterations. Not model-specific: two models, two different tokens, one rule.

**The contrast that identifies the fix:** the AC validator's own `@Check` for reserved-word collisions produces an actionable message (`Domain type name 'Party' collides with a JavaScript/Java reserved word…`), and `command-a` fixed *that* in a single iteration by renaming. Same class of error, different message quality, opposite outcome — so this is a message/prompting gap, not a model-capability limit.

**Prevention (implemented):** the `## Reserved Names` module (`_reserved_names.j2`) states the prohibition — a name you *invent* may not be a reserved word — and lists them. `prompts/grammar.py::reserved_names()` derives the list from `Symboleo.xtext` (every identifier-shaped quoted literal, **both quote styles** — `Asset` is double-quoted, `Suspension` single-quoted, so a single-style scan silently drops the whole base-type category) rather than hand-listing it, which is the grammar-derived, zero-drift escalation the leaf-construct policy above names. It ships in generation *and* correction, and is deliberately **not** gated on `include_grammar` (see Config Schema).

Two things the wording has to get right, both fenced by tests: the list contains words the model *must* still emit (`Domain`, `endDomain`, `isA`, `Contract`, `Happens`), so the rule is about invented names rather than forbidden words; and correction's "do not edit lines with no listed error" constraint would otherwise forbid the very rename that fixes this, so the correction rendering adds an explicit permission clause.

**Still open — recovery, as opposed to prevention:** upstream message enrichment in SymboleoAC-IDE (an `ISyntaxErrorMessageProvider` naming *which* identifier is reserved). That would help every consumer of the JAR and would repair contracts that arrive with a collision already in them, which prompting cannot.

### Convergence ≠ fidelity — the few-shot corpus is syntax-gold, not semantics-gold (scope decision)
`converged` is step 1 of a two-step problem: **(1)** pass the JAR (Xtext parse + AC `@Check` rules), **(2)** faithfully model the source contract text. **This project's success metric is step 1 only** — a 2026-07 scope decision — and every step-2 flaw is validator-clean, so semantic infidelity is invisible to every number the pipeline reports.

The gap is measured, not hypothetical. A blind fidelity audit (2026-07-29; one independent reviewer per contract/text pair) failed **all four** validator-clean models feeding the example corpus: `MeatSale` (payment obligation gated on an invented inspection event; the text's 10-day termination grace absent; roughly half the file is unsourced AC/IoT demo machinery), `VaccineProcurement` (the Government invoices itself where the text says the Manufacturer invoices; a discretionary "may request" modeled as a buy-until-exhaustion obligation; Stop-Work terminates the contract instead of halting work), `TransactiveEnergy` (the 30-day cure and 90-day notice windows exist only in event *names* — no temporal predicate enforces either; invoice issuance sits inside the debtor's consequent, so a party can be violated by its counterparty's inaction), `DataProcessingAgreement` (closest to faithful — role mapping, performers, and O/P directions all verified; but termination drops the text's payments-paid conjunct and a mandatory "shall suspend" is modeled as a discretionary power). Two recurring anti-patterns to recognize in LLM output as well, since few-shot examples will teach them: **inventing machinery absent from the text**, and **encoding temporal constraints in identifier names instead of temporal predicates**.

**Deferred repairs, sized by the audit:** `DataProcessingAgreement` ≈ two conjuncts + domain typos; `TransactiveEnergy` = temporal predicates for the two windows, invoice issuance moved into the triggers, one `<=` direction flipped; `MeatSale`/`VaccineProcurement` are AC-feature demos at heart — rewrite, not repair. **Revisit before:** (a) any claim or comparison about the *semantic* quality of generated contracts, and (b) assembling the DSPy training set — "every converged run is a training example" is a step-1 criterion, and outputs of few-shot runs additionally inherit the corpus's step-2 flaws.

### Reasoning-Model Parameter & Cost Compatibility
Adding thinking-capable models beyond `gpt-4o-mini` (Claude Opus 4.8/4.7, Fable 5; OpenAI o-series/GPT-5) raises three concerns. The first (sampling-param rejection) is **handled**; the other two are still latent.

- **Sampling params 400 — handled.** Opus 4.8/4.7, Fable 5, and the OpenAI reasoning models **reject** `temperature`/`top_p`/`top_k` (and `budget_tokens`) with a 400. The fix is layered:
  1. **Primary (version-independent):** `LLMConfig.temperature` is `float | None` and [litellm_adapter.py](symboleo_llm_tool/llm/litellm_adapter.py) only sends it when set. A reasoning-model config simply omits temperature, so we never send a param the model rejects — this does **not** depend on any compatibility table being correct. This is the load-bearing guard.
  2. **Safety net:** `drop_params=True` on the `litellm.completion` call drops provider-unsupported params *where LiteLLM's table is right* (OpenAI reasoning). It is a **no-op for Anthropic reasoning models** — LiteLLM still lists `temperature` as supported there ([BerriAI/litellm#26444](https://github.com/BerriAI/litellm/issues/26444)) — which is exactly why (1), not this, is the real fix. Contributing #26444 upstream is the root fix for the drop path.
  3. **Advisory warning:** [llm/compatibility.py](symboleo_llm_tool/llm/compatibility.py) flags a temperature set on a reasoning model so a silently-dropped/ignored param doesn't mislead — `reasoning_param_warnings()` and `temperature_range_warnings()` are the per-`LLMConfig` primitives, composed by `llm_param_warnings()`; `pipeline_param_warnings()` is the per-`PipelineConfig` aggregator that labels each stage (`generation:`/`correction:`) and is the single-run entry point; `suite_param_warnings()` wraps it per-experiment (name-labeled) for suites — the CLI and API call one of these two. It uses `litellm.supports_reasoning` — empirically the right signal (correct for the modern reasoning models *including* the #26444 Opus cases, with zero false alarms), **not** `get_supported_openai_params` (wrong for current reasoning models in pinned LiteLLM versions, and false-alarms on Sonnet 3.5). Best-effort and never fatal — an unknown model yields no warning rather than a false alarm. Surfaced by the CLI (printed) and the API (`warnings` on `RunCreatedResponse`). `max_tokens` is intentionally not warned/dropped — LiteLLM translates it to `max_completion_tokens` for reasoning models.

  **`compatibility.py` is the single home for provider/model-specific param knowledge** (not only reasoning concerns — e.g. Anthropic's temperature cap applies to every Claude model). The dividing line: universal invariants (the cross-provider 0–2 temperature envelope, `max_tokens >= 1`) are hard validators on the config models; anything keyed on *which* provider or model is in play is an advisory here. `temperature_range_warnings()` checks a set temperature against a small hand-maintained per-provider range table (OpenAI 0–2, Anthropic 0–1; unknown provider → no warning) — hand-maintained because LiteLLM's model map carries no param ranges, and acceptable because a missing row costs a missed advisory and a stale row at worst a spurious one — never a blocked run. A provider earns a row only when its API documents a hard cap, so an absence can be deliberate rather than an oversight (Cohere documents no upper bound; a test pins its omission). Fence tests pin every table row inside the hard envelope and check the shipped `ui_config.yaml`.

  **Model-compatibility data source & maintenance.** Both signals derive from LiteLLM's `model_prices_and_context_window.json` (per-model `litellm_provider`/`supports_reasoning`/`supported_openai_params`/pricing; 600+ entries). LiteLLM **fetches it from GitHub `main` over HTTP at import by default**, falling back to a package-bundled copy on any failure — so the data is normally *fresher than the pinned package* but **non-deterministic** (depends on network + upstream `main` at startup, with a 5 s blocking GET). Because drop/warn affects correctness and research wants reproducibility, we **pin to the bundled copy**: `symboleo_llm_tool/__init__.py` sets `LITELLM_LOCAL_MODEL_COST_MAP=True` via `os.environ.setdefault` **before any litellm import** (the package root is the earliest guaranteed point; a `.env` line loads too late for the CLI, which imports litellm before `load_dotenv()`), and the Dockerfile sets it as an `ENV`. **Maintenance is then explicit and reviewable: bump the `litellm` version in `pyproject`/`uv.lock` to refresh the model list** (the bundled JSON ships with the package; the change shows up as a lockfile diff gated by tests). To opt back into the live remote fetch, set `LITELLM_LOCAL_MODEL_COST_MAP=False` as a real OS env var (export it for the CLI; `.env`/`env_file` works for the Docker API).
- **Reasoning tokens are billed as output.** Thinking tokens price at the output rate (Opus 4.8: $5/1M in, **$25/1M out**) and count toward `max_tokens`. Thinking is opt-in (`thinking: {type: "adaptive"}`); depth is controlled by `output_config.effort` (`low`…`max`, default `high`), not a token budget. So the per-run cost model stops being linear — reasoning is variable, output-priced, and multiplied by the correction loop. For a near-deterministic syntax task, low/medium effort (or thinking off) is likely sufficient; reasoning models are selectable in `ui_config.yaml`, but `LLMConfig` does not yet expose per-stage `effort` — an open TODO.
- **Caching interaction (benign).** Toggling thinking on/off invalidates only the *messages* cache tier, not tools/system — so a planned grammar-prefix cache survives a thinking on/off change.

### Malformed LLM Responses
The LLM may return markdown code blocks, explanations, or partial output instead of valid Symboleo. `_clean_response()` in `pipeline.py` handles markdown code fences, but more exotic malformed output (partial contracts, explanatory prose, mixed content) is not yet handled. A more robust pre-validation step may be needed as strategies are developed.

### CLI `--set` Override
Handling nested key paths (`correction.llm.model=gpt-4o`) with type coercion and YAML merging is non-trivial. **Deferred — low priority given the API provides a more ergonomic interface for per-run config.**

### Frontend — Options Cache Staleness
`useOptions` caches `GET /api/options` in a module-level variable for the lifetime of the browser tab. If `configs/ui_config.yaml` is changed and the server restarted while a user has the tab open, the frontend will continue showing the old model/parameter list until the user does a hard refresh. The failure mode is benign: submitting a model that no longer exists returns a 422 from the backend, which the frontend already surfaces as an error. Alternatives considered: React Context above the router (more boilerplate, same semantics) and React Query with `staleTime: Infinity` (adds a dependency for a single static endpoint). Neither is warranted for a single-user research tool where config changes are infrequent.

### Frontend — SSE Schema via `response_model` Semantic Hack
`GET /api/runs/{run_id}/stream` carries `response_model=ProgressEvent | CompleteEvent | ErrorEvent` on its route decorator solely to force FastAPI to include those Pydantic models in `components/schemas`, which lets `openapi-typescript` generate them into `schema.d.ts`. The endpoint actually returns a `StreamingResponse` (`text/event-stream`), not the JSON body the spec implies. The return type annotation is intentionally omitted from the function signature — adding `-> StreamingResponse` causes FastAPI to skip `response_model` during schema generation. Accurate documentation would require a custom `app.openapi()` override; the hack is acceptable for a single-consumer research tool where the spec is only read by `openapi-typescript`. Run `npm run generate-types` from `frontend/` after any change to the SSE event models or their nested types.

### Frontend — No Run History
The frontend has no persistent run history. Once a job's 5-minute TTL expires, it is gone from the in-memory store and the run URL returns 404. Full run data (contract, config, errors, final output) is always available in the timestamped `output/` directory written by the pipeline — the UI is a live view only, not an archive. Migrate job storage to Redis and add a `GET /runs` list endpoint before adding a history page.

---

## Future Directions

### DSPy — Prompt Optimization

[DSPy](https://dspy.ai/) ([paper](https://arxiv.org/pdf/2310.03714)) is the planned long-term replacement for hand-authored prompt templates. Instead of writing prompt text, you declare a `Signature` (typed input/output fields) and a `Module` (prompting strategy: `dspy.Predict`, `dspy.ChainOfThought`, etc.); DSPy's optimizer automatically searches for the best prompt by evaluating candidates against a labeled dataset. Demonstrated gains of 33% → 82% accuracy on GPT-3.5 in the original paper without any hand-crafted prompts.

**What it replaces:** The `prompts/` layer only — `.j2` templates and `PromptStrategy` subclasses become DSPy `Module` classes; `PromptContext` fields become `Signature` input fields. The pipeline, correction loop, JAR validator, LLM adapter, config system, API, CLI, and frontend are all untouched.

**The `PromptStrategy` ABC is the natural migration seam:** `pipeline.run()` calls `strategy.build_generation_prompt(context)` without knowing what's behind it. A DSPy-backed strategy implements the same interface — internally calling a DSPy module prediction instead of rendering a Jinja2 template. LangGPT and DSPy strategies can coexist as implementations of the same ABC and be compared directly in the same experiment.

**Prerequisite — labeled training data:** Every run that converges to a valid `.symboleo` file is a training example. DSPy is viable once enough (contract_text → correct Symboleo) pairs have accumulated from LangGPT-baseline experiments to train and evaluate an optimizer. LangGPT experiments are building this dataset. Caveat before assembling it: "converges" is a syntax-only criterion — see Known Issues, *Convergence ≠ fidelity* — so accumulated pairs are gold for the *language*, not for the text→Symboleo *mapping*.

**Do not adopt DSPy prematurely:** DSPy optimization runs consume significant API tokens and require a stable evaluation metric. Both require a meaningful dataset first.

### FastAPI Web Service — Implementation Notes

The web service is fully implemented (CLI-parity routes, async-bridged SSE, React frontend, Docker). The notes below document the API contract and the decisions behind it.

The key constraint that keeps this cheap: `pipeline.run()` accepts a `str` and returns a `PipelineResult` — no file I/O, no CLI concerns, no stdout. Any entry point (CLI, API, test) can call it the same way.

**Endpoint design (decided):**
- `POST /generate` — body: `GenerateRequest` (see below) → returns `{ run_id, warnings }`
- `GET /runs/{run_id}/stream` — SSE stream of typed events (see below)
- `POST /suites` — body: `SuiteRequest` (one contract + N `ExperimentRequest` + optional `max_concurrency`) → returns `{ run_id, warnings }` (warnings labeled per experiment name)
- `GET /suites/{run_id}/stream` — multiplexed SSE stream of the same event types; `ProgressEvent` tagged with `experiment_index`, terminal `SuiteCompleteEvent`
- `POST /runs/{run_id}/cancel` — trips the job's `CancellationToken` (runs and suites share the store) → 204; the pipeline stops at its next cooperative checkpoint
- `GET /options` — returns everything the frontend needs at page load (see below)

**SSE event schema:**
- `ProgressEvent` — fired after each generation/correction iteration; contains `candidate_id`, `iteration`, `error_count` (ERROR-severity issues only — the count that gates convergence), and `experiment_index` (null for a single run; set within a suite so the client demultiplexes one stream into per-experiment state)
- `CompleteEvent` — final event for a single run; embeds the full `PipelineResult`
- `SuiteCompleteEvent` — final event for a suite; embeds the full `SuiteResult`
- `ErrorEvent` — fatal pipeline error; contains `message`
- Reconnect behavior: if job complete → send `CompleteEvent` immediately; if still running → resume live stream; if TTL expired → 404
- Event type discrimination uses `EventType(str, Enum)` — serializes to lowercase string values (`"progress"`, `"complete"`, `"error"`) without `Literal["x"] = "x"` repetition. Note: this generates the enum as a shared type across the event schemas, which prevents TypeScript discriminated-union narrowing. The frontend adapts via the literal-typed `StreamEvent<TResult>` union local to `hooks/useEventStream.ts` — do not change the backend to fix a frontend type concern.

**Async bridge (sync pipeline → async SSE):**
- `asyncio.Queue` + `loop.call_soon_threadsafe(queue.put_nowait, event)` — the `on_progress` callback, created in async context before thread launch, posts events thread-safely onto the queue
- `run_in_threadpool` (Starlette) runs `pipeline.run()` in a thread pool without blocking the event loop
- `asyncio.create_task` fires the pipeline task as fire-and-forget; the SSE generator independently drains the queue
- Disconnect detection: `asyncio.wait_for(queue.get(), timeout=1.0)` + `await request.is_disconnected()` — the timeout (~1–2 s) is required so the generator can poll for disconnect between events
- Exception handling: pipeline task must catch all exceptions and push an `ErrorEvent` onto the queue to avoid silent failures

**`GenerateRequest` shape:**
```
contract_text: str                          # required
generation: StageRequest                    # required
  model: str                                # e.g. "gpt-4o-mini"
  strategy: str                             # e.g. "zero_shot"
  temperature: float | None                 # omitted/None = unset — param never sent (model default); per-stage
  include_grammar: bool | None              # defaults from Pydantic
  strategy_params: dict                     # e.g. {"example_files": ["sale_contract"]}
correction: StageRequest | None             # defaults to generation if omitted
num_candidates: int | None                  # defaults from Pydantic
max_iterations: int | None                  # defaults from Pydantic
save_intermediates: bool | None             # defaults from Pydantic
stop_on_first_convergence: bool | None      # defaults from Pydantic
```
Provider is derived from model name via `configs/ui_config.yaml`. For `few_shot`, `strategy_params.example_files` takes example names, which reach `StageConfig` unchanged and are resolved by `prompts/examples.py` at point of use. Early validation happens in `build_pipeline_config` (`api/config_builder.py`), which instantiates each stage's strategy via `get_strategy()` before the job thread starts; `routes.py` converts the resulting `ValueError` (unknown strategy name, missing example file) to `HTTPException(422)`, so errors surface as HTTP 422 rather than an `ErrorEvent` on the SSE stream.

**`GET /options` response:**
```
strategies: list[str]          # from registry
models: dict[str, list[str]]   # from configs/ui_config.yaml
parameters: dict               # type + min/max from ui_config.yaml; defaults from Pydantic models
examples: list[str]            # names of .yaml files in examples/ (without extension)
```

**`configs/ui_config.yaml`** — lives alongside pipeline run configs (same Docker volume mount). Holds model lists and parameter constraints (min/max/type — the form inputs read the bounds via `getParamConstraint`, with local fallbacks — or attribute omission, for the advanced counts' `max` — when a bound is absent, so editing one here reaches the UI). The temperature max is the cross-provider 0–2 envelope; per-provider caps are `compatibility.py` advisories, not UI bounds. Defaults come from Pydantic, not this file. Update without a code or frontend deploy — but **append** providers rather than prepending: the first model of the first provider seeds the UI form's default. Both that ordering and the block's shape (provider → non-empty list of names) are pinned by tests in `tests/unit/test_compatibility.py`.

**Job storage:** in-memory dict with TTL (~5 min after completion). Each `Job` carries a request-scoped `CancellationToken` (tripped by `POST /runs/{id}/cancel` — the Stop button / `pagehide` beacon) and a `detached_at` stamp; the lifespan cleanup loop (5 s sweep) cancels incomplete jobs whose stream stays detached past a 10 s grace, and expires completed ones past TTL. Migrate to Redis before any public deployment (see [[project_fastapi_architecture]]).

**Frontend UI — Page Design (decided):** (routes enumerated in Frontend Architecture above)

**Page 1 — Config (`/`):**
- Contract upload: `.txt` only; file input tooling chosen for future format flexibility; contract text preview rendered after upload
- Generation section (collapsible): model dropdown, strategy dropdown, temperature, include_grammar; `few_shot` disabled when `examples/` is empty; example files multi-select appears when `few_shot` selected (options from `GET /api/options`)
- Correction section (collapsible): same fields as generation, pre-populated with generation values; user edits only what differs
- Advanced options (behind toggle): `num_candidates`, `max_iterations`, `stop_on_first_convergence`, `save_intermediates`
- Submit navigates immediately to `/runs/:id`

**Page 2 — Results (`/runs/:id`):**
- While running: single spinner + "Candidate X — Iteration Y" counter updated from `ProgressEvent` stream; candidate accordion not rendered until `CompleteEvent` arrives
- On complete: accordion of candidates, each with: convergence badge (Converged / Failed to converge) plus a muted warnings chip when `final_warning_count > 0`, plain-text Symboleo code block, Download `.symboleo` button, Download `report.json` button (contains full error history per iteration)
- On fatal error: red error card displaying `ErrorEvent.message`
- "New Run" button → `/` with form reset to defaults

**Syntax highlighting:** plain `<pre><code>` block for now — no Symboleo-specific grammar. Revisit if needed.
