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
├── prompts/        # PromptStrategy ABC + concrete strategies; PromptContext dataclass
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
- Strategy-specific data (e.g., few-shot examples) comes from `strategy_params` in config, passed to the strategy constructor
- Prompt text lives in Jinja2 `.j2` templates, separate from Python logic
- Zero/few-shot distinction refers to whether **examples** are included, not whether grammar context is included — grammar is baseline for all strategies

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
- Integrated at the `LLMAdapter` base class level so all adapters get tracing automatically

---

## Known Issues / Future Flags

### Privacy — LangSmith
LangSmith sends prompt data (including contract text) to third-party servers. Currently acceptable because contracts are synthetic/fake for research. **Must be removed or replaced (e.g., MLflow, local logging) before use with real legal contracts.**

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

1. **Add `api/` directory** — FastAPI routes that accept a file upload + config JSON body and call the same `pipeline.run()` the CLI calls. The core is untouched.
2. **Wrap the sync pipeline for async** — the pipeline involves subprocess and LLM calls; wrap in `asyncio.run_in_executor` at the API layer (~5 lines, no core changes).
3. **Add a frontend** — lightweight React/Vite app or static HTML served from FastAPI. No backend changes required.
4. **Extend Docker Compose** — `docker-compose.yml` already exists for the CLI. Adding the API service means adding a second entry under `services:` and exposing a port. The CLI service is unchanged.

The key constraint that keeps this cheap: `pipeline.run()` accepts a `str` and returns a `PipelineResult` — no file I/O, no CLI concerns, no stdout. Any entry point (CLI, API, test) can call it the same way.
