# Symboleo LLM Tool — Project Reference

## What This Tool Does

A Python CLI tool that:
1. Takes a `.txt` legal contract in English
2. Uses an LLM to generate one or more SymboleoAC contract(s)
3. Runs the SymboleoAC headless CLI to extract syntax errors
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
| Linting/formatting | Ruff |
| Type checking | mypy |
| Testing | pytest + pytest-mock |

---

## Architecture

### Module Structure

```
symboleo_llm_tool/
├── cli/            # Typer entry point — thin layer only, no business logic
├── pipeline/       # Orchestration: generation stage + correction loop
├── llm/            # LiteLLM-backed adapters (abstract base + concrete implementations)
├── prompts/        # PromptStrategy ABC + concrete strategies; PromptContext Pydantic model
├── symboleo/       # Subprocess wrapper around the SymboleoAC headless CLI JAR
├── config/         # Pydantic config models + YAML loader
├── output/         # PipelineResult, CandidateResult, IterationRecord models
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
    if no errors or max_iterations reached → done
    else → LLM + PromptStrategy → corrected code → repeat
    ↓
[Output] timestamped directory: report.json, config.yaml, final .sl, optional intermediates
```

---

## Key Design Decisions

### LLM Abstraction
- **LiteLLM** handles all provider abstraction — adding a new provider is a config change, not a code change
- Do NOT use MCP for provider switching — MCP is for tool use, not provider abstraction
- API keys always via environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.), never in config files

### Prompt Strategies
- `PromptStrategy` ABC with two methods: `build_generation_prompt(context)` and `build_correction_prompt(context)`
- All strategies receive a `PromptContext` parameter object — strategies read only what they need
- Strategy-specific data comes from `strategy_params` in config, passed to the strategy constructor
- Prompt text lives in Jinja2 `.j2` templates, separate from Python logic
- Grammar is baseline for all strategies — `include_grammar` is a per-stage flag, not a strategy characteristic
- Adding a new strategy: add templates to `prompts/templates/`, add a strategy class decorated with `@registry.register("name")` in `prompts/strategies/`, import it in `prompts/strategies/__init__.py`

**Available strategies:**
| Strategy | Key `strategy_params` | Notes |
|---|---|---|
| `zero_shot` | none | Baseline — grammar + contract, no examples |
| `few_shot` | `example_files: [list of paths]` | Loads `contract_text`/`symboleo_code` pairs from external YAML files in `examples/` |
| `cot` | none | Adds step-by-step reasoning instructions before generation; output is still code-only (Option A) |

**CoT Option B (future flag):** Currently CoT uses Option A — the model reasons internally but outputs only code. Option B would add a `post_process_response()` hook to `PromptStrategy` so strategies can extract code from a mixed reasoning+code response, preserving reasoning in `report.json`. Deferred until research value is confirmed.

### Config Schema
- Generation and correction each have their own `StageConfig` (independent LLM + strategy per stage)
- `strategy_params: {}` dict on each stage — strategies validate their own params internally
- `include_grammar` is a per-stage research flag (not a strategy characteristic)
- `output.save_intermediates` saves each iteration's `.sl` output — off by default
- `stop_on_first_convergence` flag — default `false` (full research data), flip to `true` to save tokens
- Input file is a CLI argument, not a config concern
- CLI override support (`--set key=value`) for quick experiments — **deferred until core pipeline is stable**

### Multi-Candidate Behavior
- Success = any candidate converges (one correct output is sufficient)
- Candidates run **sequentially** — parallel execution deferred (requires cancellation logic)
- `stop_on_first_convergence: false` by default to preserve full research data

### Output Format
- Timestamped run directories (e.g., `output/run_20260526_143022/`) — prevents experiment overwrites
- Each run directory contains: `report.json`, `config.yaml` (copy), `contract_final.sl`, optionally `intermediates/`
- Multi-candidate runs use a `_candidate_N` suffix consistently: `contract_candidate_0_final.sl`, `intermediates_candidate_0/`
- `report.json` captures: success, iterations per candidate, full error history per iteration
- Console prints a human-readable summary; full detail is in `report.json`

### N×M Problem (Strategy × Provider)
- LLM adapters and prompt strategies are **two independent hierarchies** — they compose, not inherit
- Never let prompt strategies become provider-aware — that creates N×M classes
- Prompt strategies produce text; LLM adapters handle provider-specific formatting

### Option A → Option B Migration Path
- The pipeline core must be I/O-agnostic: `pipeline.run(contract_text: str, config: PipelineConfig) → PipelineResult`
- The CLI is a thin adapter: parse args → read file → call pipeline → format output
- Adding FastAPI later means adding an `api/` directory calling the same core — no core changes
- Config as Pydantic models means the same object can be populated from YAML or a JSON request body

### Java Dependency (Packaging)
- **Tier 1 (dev):** Bundle JAR inside the package, require Java 11+ as a system prerequisite. Check for Java at startup and fail with a clear, actionable error message.
- **Tier 2 (release):** Docker image bundling JRE + JAR + Python tool — eliminates Java prerequisite for end users. `Dockerfile` and `docker-compose.yml` are in the project root.
- **JAR naming convention:** The JAR is stored as `lib/symboleo-cli.jar` (no version in the filename). When updating the JAR, replace the file in place — the version lives in the file content and git history, not the filename. This keeps the default `jar_path` in `SymboleoConfig` stable across releases.

### Testing Strategy
- **Unit tests:** Mock both LLM adapter and CLI subprocess wrapper. Focus on pipeline loop logic (iteration bounds, early stopping, error passing).
- **Integration tests:** Run the real JAR against known fixture files (valid `.sl`, invalid `.sl` with known errors). Live LLM adapter tests optional/skippable in CI (`pytest -m "not live"`).
- **No full e2e in CI** — manual smoke test before releases.
- `tests/fixtures/` contains: sample `.txt` contract, known-valid `.sl`, known-invalid `.sl`

### Observability
- LangSmith is opt-in via `observability.langsmith.enabled: false` default
- Tracing applied conditionally at adapter construction time — `tracing_enabled` flows from `pipeline.run()` → `create_adapter()` → `LiteLLMAdapter.__init__()`. Only `LiteLLMAdapter` is traced; mock adapter is not.
- `observability.langsmith.project` controls the LangSmith project — the CLI sets `LANGSMITH_PROJECT` and `LANGCHAIN_TRACING_V2` env vars from config at runtime. `.env` only needs `LANGSMITH_API_KEY`.
- **Data model consistency rule:** data passed between layers uses Pydantic `BaseModel`; internal service-object bundles (e.g., `_RunContext` in `pipeline.py`) use `@dataclass(frozen=True)`.

---

## Known Issues / Future Flags

### Privacy — LangSmith
LangSmith sends prompt data (including contract text) to LangChain's servers. Currently acceptable because contracts are synthetic/fake for research. **Must be migrated to self-hosted LangFuse before use with real legal contracts.**

LangFuse is the planned replacement: open source, Docker-based, near-identical feature set to LangSmith, and LiteLLM has native integration — the migration is a config change, not a code change.

### Grammar Context Size
The full Xtext grammar may push against LLM context window limits or significantly increase token costs across many iterations. Starting point is full grammar injection; selective/relevant excerpt injection is a future optimization.

### Malformed LLM Responses
The LLM may return markdown code blocks, explanations, or partial output instead of valid Symboleo. `_clean_response()` in `pipeline.py` handles markdown code fences, but more exotic malformed output (partial contracts, explanatory prose, mixed content) is not yet handled. A more robust pre-validation step may be needed as strategies are developed.

### CLI `--set` Override
Handling nested key paths (`correction.llm.model=gpt-4o`) with type coercion and YAML merging is non-trivial. **Deferred until core pipeline is stable.**

---

## Future Directions

### Option B: FastAPI Web Service

If a frontend becomes a firm requirement, Option B can be added on top of Option A without touching the core. The migration is additive:

1. **Add `api/` directory** — FastAPI routes that call the same `pipeline.run()` the CLI calls. The core is untouched.
2. **Wrap the sync pipeline for async** — wrap in `asyncio.run_in_executor` at the API layer (~5 lines, no core changes).
3. **Add a frontend** — lightweight React/Vite app or static HTML served from FastAPI.
4. **Extend Docker Compose** — add a second service entry, expose a port. The CLI service is unchanged.

The key constraint that keeps this cheap: `pipeline.run()` accepts a `str` and returns a `PipelineResult` — no file I/O, no CLI concerns, no stdout. Any entry point (CLI, API, test) can call it the same way.

**Endpoint design (decided):**
- `POST /generate` — body: `GenerateRequest` (see below) → returns `{ run_id }`
- `GET /runs/{run_id}/stream` — SSE stream of typed events (see below)
- `GET /options` — returns everything the frontend needs at page load (see below)

**SSE event schema:**
- `ProgressEvent` — fired after each generation/correction iteration; contains `candidate_id`, `iteration`, `error_count`
- `CompleteEvent` — final event; embeds the full `PipelineResult`
- `ErrorEvent` — fatal pipeline error; contains `message`
- Reconnect behavior: if job complete → send `CompleteEvent` immediately; if still running → resume live stream; if TTL expired → 404

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
  include_grammar: bool | None              # defaults from Pydantic
  strategy_params: dict                     # e.g. {"example_files": ["sale_contract"]}
correction: StageRequest | None             # defaults to generation if omitted
num_candidates: int | None                  # defaults from Pydantic
max_iterations: int | None                  # defaults from Pydantic
temperature: float | None                   # defaults from Pydantic
save_intermediates: bool | None             # defaults from Pydantic
stop_on_first_convergence: bool | None      # defaults from Pydantic
```
Provider is derived from model name via `configs/ui_config.yaml`. For `few_shot`, `strategy_params.example_files` takes example names (not full paths) — the API resolves them to `examples/<name>.yaml` before starting the job (validation at request time, not inside the thread).

**`GET /options` response:**
```
strategies: list[str]          # from registry
models: dict[str, list[str]]   # from configs/ui_config.yaml
parameters: dict               # type + min/max from ui_config.yaml; defaults from Pydantic models
examples: list[str]            # names of .yaml files in examples/ (without extension)
```

**`configs/ui_config.yaml`** — lives alongside pipeline run configs (same Docker volume mount). Holds model lists and parameter constraints (min/max/type). Defaults come from Pydantic, not this file. Update without a code or frontend deploy.

**Job storage:** in-memory dict with TTL (~5 min after completion). TTL cleanup runs as a background task started in the FastAPI lifespan handler. Migrate to Redis before any public deployment (see [[project-fastapi-architecture]]).
