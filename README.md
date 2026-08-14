# Symboleo LLM Tool

A Python CLI and FastAPI web service that converts plain-English legal contracts into valid [SymboleoAC](https://github.com/Smart-Contract-Modelling-uOttawa/SymboleoAC-IDE) contracts using an LLM, with an automatic correction loop backed by the SymboleoAC headless CLI validator (Xtext parser + `@Check` rules, including the access-control layer).

This file is the quickstart. How the pieces fit — the pipeline, configs field by
field, what a run's artifacts mean — is in
[docs/architecture.md](docs/architecture.md).

## How It Works

1. Takes a `.txt` legal contract as input
2. Sends it to an LLM to generate a SymboleoAC contract
3. Validates the output with the SymboleoAC JAR
4. If errors are found, feeds them back to the LLM for correction
5. Repeats until the contract is valid or the iteration limit is reached
6. Writes the final contract and a run report to a timestamped output directory

## Prerequisites

**CLI usage:**
- Python 3.11+
- Java 17+ — the validator is a JAR (see [Installing Java](#installing-java))
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

**Frontend dev server:**
- Node.js 18+

**API (Docker):**
- [Docker Desktop](https://www.docker.com/products/docker-desktop) — bundles its own JRE, so Java is not needed separately

### Installing Java

Java is the only prerequisite that differs by platform, and the usual cause of a
failed first run.

| Platform | Install |
|---|---|
| macOS | `brew install --cask temurin@17` (works on both Apple Silicon and Intel) |
| Linux | `sudo apt install openjdk-17-jdk`, or your distribution's equivalent |
| Windows | [Adoptium installer](https://adoptium.net/), ticking "Set JAVA_HOME" |

On macOS, `java -version` may print "No Java runtime" even after installing, if
the shell has not picked up the new runtime — open a new terminal, and if it
persists set `export JAVA_HOME=$(/usr/libexec/java_home -v 17)` in your shell
profile.

## Setup

```bash
# 1. Clone the repo
git clone <repo-url>
cd Symboleo-LLM-Tool

# 2. Install Python dependencies
uv sync

# 3. Configure API keys
cp .env.example .env
# Edit .env and fill in your keys (LLM provider + LangSmith if needed)
```

**Web UI (optional).** Only needed for the browser interface; the CLI does not
use it.

```bash
cd frontend && npm install && cd ..
```

Running it is covered under [Web UI](#web-ui).

## Verify your setup

Both commands are free — neither calls an LLM.

```bash
# Java must be on PATH and 17+. Without this the first run fails partway
# through, after the LLM call has already been billed.
java -version

# Drives the real CLI and validator end to end, faking only the LLM. A pass
# means Python, Java, the JAR, and the output writer are all wired up.
uv run python scripts/smoke_rejection.py
```

## Usage

### CLI

```bash
# Single run — sample contracts ship in contracts/
uv run symboleo-tool run contracts/equipment_loan.txt --config configs/luna.yaml

# Experiment suite — one contract against several named configs, compared
uv run symboleo-tool suite contracts/equipment_loan.txt --config configs/suite_example.yaml
```

A **suite** file lists named `experiments`, each holding a full pipeline `config`;
the contract is the CLI argument, not part of the file. See
`configs/suite_example.yaml`, and [docs/architecture.md](docs/architecture.md)
for what suites are for and what they write.

To compare how *much* contract runs produced — convergence is blind to size:

```bash
# One row per candidate across every run/suite in output/; --csv PATH to export.
# Read rows beside the converged column.
uv run python scripts/richness_sweep.py
```

To judge how *faithfully* runs modeled their source text — an LLM judge scores
each candidate against the contract's curated clause inventory
(`contracts/inventories/`; contracts without one are skipped). Judge calls
cost money; results cache under `output/fidelity_cache/`, so re-runs and
`--score-only` are free:

```bash
uv run python scripts/fidelity_sweep.py output/suite_<timestamp> --csv fidelity.csv
```

After changing a prompt template, check the change reached the models — one
suite per contract (both provider arms, three candidates each), then a census of
how each candidate's error count moved:

```bash
# One contract. Costs contracts x arms x candidates x (1 + max_iterations) LLM
# calls, so name them deliberately. Arms live in configs/prompt_probe.yaml.
uv run python scripts/prompt_probe.py contracts/equipment_loan.txt

# Several — each gets its own suite directory, run one after another.
uv run python scripts/prompt_probe.py contracts/Vaccine.txt contracts/Energy.txt --csv probe.csv

# Re-read finished runs instead, spending nothing. Takes run_* dirs too.
uv run python scripts/prompt_probe.py --census output/suite_<timestamp>
```

The `errors` cell is the ERROR count at each iteration (`20>8>4>0` converged;
`20>20>20>20` never moved), and `stalled` marks a candidate whose last
correction reduced nothing. Every non-converged candidate then prints its final
blocking errors with their source lines — that output is the analysis, and the
census deliberately does not try to classify it for you.

## Configuration

Config files live in `configs/`. Copy `configs/example.yaml` as a starting point:

| File | Purpose |
|---|---|
| `example.yaml` | Reference template — documents all available fields |
| `luna.yaml` | OpenAI `gpt-5.6-luna`, zero-shot — **the usual starting point** (best convergence *and* fidelity) |
| `cohere.yaml` | Cohere, zero-shot |
| `cohere_fewshot.yaml` | Cohere, few-shot with the `vaccine_procurement` example |
| `anthropic.yaml` | Anthropic `claude-sonnet-4-6`, zero-shot |
| `suite_example.yaml` | Suite: zero-shot vs CoT, for `symboleo-tool suite` |
| `prompt_probe.yaml` | Suite: the prompt-regression probe's arms (budget models on purpose — see its comments) |
| `mock.yaml` | No API key — a canned response, for checking plumbing only |
| `app/ui_config.yaml` | Not a run config: the model/parameter lists the web UI offers |

`example.yaml` annotates every field in place, and editors with a YAML language
server (VS Code: the Red Hat "YAML" extension) validate configs as you type,
against the schemas in `configs/schemas/`.
The field-by-field walkthrough is in
[docs/architecture.md](docs/architecture.md).

API keys are read from `.env` — never put them in config files. Keep
`temperature` low (0.2) when comparing configurations, and omit it entirely for
reasoning models — they reject the parameter.

### Prompting strategies

| Strategy | Description |
|---|---|
| `zero_shot` | Baseline — grammar + contract, no examples |
| `few_shot` | Includes example contract→Symboleo pairs loaded from `examples/` |
| `cot` | Adds step-by-step reasoning instructions before generation |

**Few-shot setup.** The corpus ships in `examples/`, one `.yaml` per example, so
`few_shot` works on a fresh clone. Each example has a matching input contract in
`contracts/` — if you run one as input, exclude its example from
`example_files`, or the model is simply shown the answer (pairings and why:
[docs/architecture.md](docs/architecture.md)).

To add your own, create `examples/your_example.yaml` with two block scalars,
`contract_text` and `symboleo_code` — copy `examples/equipment_loan.yaml` as
the model.

Then reference it in your config **by name** — not by path, so the config means the same thing on any machine:

```yaml
generation:
  strategy: few_shot
  strategy_params:
    example_files:
      - your_example    # resolves to examples/your_example.yaml
```

`examples/` is mounted as a read-only volume when running the API via Docker. It is resolved relative to the working directory; set `SYMBOLEO_EXAMPLES_DIR` to point at a corpus elsewhere.

## Output

Each run — CLI or web UI — writes a timestamped `output/run_*/` directory
holding the final contract, a full `report.json`, the input contract, and a copy
of the config used. Layout and how to read the report:
[docs/architecture.md](docs/architecture.md).

## Web UI

A React/Vite + Tailwind + shadcn/ui interface over the same pipeline, served by a
FastAPI backend. The API reads `configs/app/ui_config.yaml` at startup for its model
list and parameter constraints, so models can be added or removed without a code
change.

Interactive API documentation is generated from the code at
`http://localhost:8000/docs`.

### Running locally

The default. Two terminals — the API reloads on Python changes, Vite hot-reloads
the frontend, so this is the loop you want while running experiments:

```bash
# Terminal 1 — API
uv run uvicorn symboleo_llm_tool.api.app:app --reload

# Terminal 2 — frontend dev server (proxies /api → localhost:8000)
cd frontend && npm run dev
```

Open **`http://localhost:5173`** — the Vite dev server, which serves the UI and
proxies API calls to port 8000.

### Running in Docker

An add-on for packaged deployment, not the development path. The image bundles a
JRE, so it is the only way to run the API without Java and Python on the host —
which is moot if you followed Setup above, since you already have both.

It serves a production build rather than the dev server, so there is no hot
reload and the frontend must be built first:

```bash
cd frontend && npm run build && cd ..
docker compose up symboleo-api
```

Open **`http://localhost:8000`** — here the API serves the built frontend itself,
so there is no separate port. `configs/`, `examples/`, and `frontend/dist/` are
mounted read-only, so model lists and the corpus can change without a rebuild;
`output/` is mounted read-write so run artifacts land on the host and survive
the container.

### Experiment Suites

The UI's **Experiment Suite** page (`/experiments`) runs one contract against several named configurations at once and shows a side-by-side comparison — convergence, iterations-to-convergence, and token/cost totals per experiment, plus a suite-wide total — with a downloadable summary CSV. Use it to compare strategies, models, or temperatures on the same contract. To build a comparison quickly, the **Generate variants** control expands one axis (strategy or model) into auto-named experiment cards, holding everything else constant. It maps to `POST /api/suites`, streaming progress over a single multiplexed SSE connection; the **Concurrency** control caps how many experiments and candidates run at once.

**Download suite config** saves the experiments you have configured as a `suite.yaml` — the same format `symboleo-tool suite` reads — so a comparison assembled in the browser can be re-run headlessly, checked into version control, or edited by hand. It needs no contract, since the contract is a CLI argument.

## Supporting scripts

Everything in `scripts/` at a glance. Each is documented in the section where
you would actually reach for it — this table is just the index.

| Script | What it does | LLM calls? |
|---|---|---|
| `richness_sweep.py` | How *much* contract each archived candidate produced ([Usage](#usage)) | Free |
| `fidelity_sweep.py` | How *faithfully* candidates model their source text — the calibrated LLM judge ([Usage](#usage)) | Paid; judgments cache |
| `prompt_probe.py` | Whether a prompt change measurably reached the models ([Usage](#usage)) | Paid; `--census` re-reads for free |
| `generate_config_schemas.py` | Regenerates the committed editor schemas after a config-model change ([Development](#development)) | Free |
| `smoke_rejection.py` | End-to-end wiring check — real CLI, JAR, and writer; faked LLM ([Verify your setup](#verify-your-setup)) | Free |
| `smoke_provider_failure.py` | Its sibling for the failed-LLM-call path; run both before a release ([Development](#development)) | Free |

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=symboleo_llm_tool --cov-report=term-missing

# Lint
uv run ruff check .

# Type check (mypy is run live, not pinned in the lock — see CLAUDE.md)
uv run --with mypy mypy symboleo_llm_tool

# After changing any config model: regenerate the committed editor schemas
# (tests compare committed against live generation, so CI is red until you do)
uv run python scripts/generate_config_schemas.py

# End-to-end smoke tests — not in CI, run both before a release (needs Java 17)
uv run python scripts/smoke_rejection.py
uv run python scripts/smoke_provider_failure.py
```

**Frontend:**

```bash
cd frontend

# Build
npm run build

# Run tests
npm run test

# Run tests with coverage
npm run test:coverage

# Lint
npm run lint

# Regenerate TypeScript types from the live API schema (requires API running).
# schema.d.ts is committed — regenerate AND commit it whenever backend models change.
npm run generate-types
```
