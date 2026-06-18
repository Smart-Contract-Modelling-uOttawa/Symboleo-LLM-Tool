# Symboleo LLM Tool

A Python CLI and FastAPI web service that converts plain-English legal contracts into valid [SymboleoAC](https://github.com/Smart-Contract-Modelling-uOttawa/Symboleo-IDE) contracts using an LLM, with an automatic syntax-correction loop backed by the SymboleoAC headless CLI.

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
- Java 11+ ([Adoptium](https://adoptium.net/))
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

**Frontend dev server:**
- Node.js 18+

**Docker usage:**
- [Docker Desktop](https://www.docker.com/products/docker-desktop)

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

# For the frontend dev server, also see the Frontend section below.
```

## Usage

### CLI (Native)

```bash
uv run symboleo-tool <contract.txt> --config configs/openai.yaml
```

### CLI (Docker)

```bash
# Build the image (once, or after code changes)
docker compose build

# Run
docker compose run --rm symboleo-tool /app/contracts/<contract.txt> --config /app/configs/openai.yaml
```

Place your contract files in the `contracts/` folder at the project root. Output is written to `output/` on your local machine.

## Configuration

Config files live in `configs/`. Copy `configs/example.yaml` as a starting point:

| File | Purpose |
|---|---|
| `example.yaml` | Reference template — documents all available fields |
| `openai.yaml` | OpenAI (`gpt-4o-mini`) configuration |

Key config options:

```yaml
pipeline:
  num_candidates: 1       # number of independent contracts to generate
  max_iterations: 3       # max correction attempts per candidate

generation:
  llm:
    provider: openai
    model: gpt-4o-mini
    temperature: 0.7
  strategy: zero_shot     # zero_shot | few_shot | cot
  include_grammar: true   # inject SymboleoAC grammar into the prompt

output:
  save_intermediates: true  # save each iteration's .symboleo file
```

API keys are read from `.env` — never put them in config files.

### Prompting strategies

| Strategy | Description |
|---|---|
| `zero_shot` | Baseline — grammar + contract, no examples |
| `few_shot` | Includes example contract→Symboleo pairs loaded from `examples/` |
| `cot` | Adds step-by-step reasoning instructions before generation |

**Few-shot setup:** create `examples/your_example.yaml` at the project root:

```yaml
contract_text: |
  Seller shall deliver 100 units to Buyer within 30 days.
  Buyer shall pay $5,000 upon delivery.
symboleo_code: |
  Domain SalesDomain
    ...
  endDomain
  Contract SalesContract(...)
    ...
  endContract
```

Then reference it in your config:

```yaml
generation:
  strategy: few_shot
  strategy_params:
    example_files:
      - ./examples/your_example.yaml
```

The `examples/` directory is gitignored and mounted as a read-only volume in Docker — same pattern as `contracts/` and `configs/`.

## Output

Each run produces a timestamped directory under `output/`:

```
output/run_20260601_143022/
├── contract_final.symboleo  # final generated contract
├── report.json              # full run details: iterations, errors, convergence
├── config.yaml              # copy of the config used (for reproducibility)
└── intermediates/           # per-iteration .symboleo files (if save_intermediates: true)
```

## API (Web Service)

The FastAPI server exposes three endpoints:

- `POST /api/generate` — submit a contract and config, returns a `run_id`
- `GET /api/runs/{run_id}/stream` — SSE stream of progress and final result
- `GET /api/options` — available models, strategies, and parameter constraints

### Running the API

The API requires `configs/ui_config.yaml` at startup — it defines the model list and parameter constraints exposed to the frontend. Update it to add or remove models without a code change.

**Locally:**
```bash
uv run uvicorn symboleo_llm_tool.api.app:app --reload
```

**Docker Compose:**
```bash
docker compose up symboleo-api
```

Interactive API docs are available at `http://localhost:8000/docs` once the server is running.

### Frontend

A React/Vite + shadcn/ui + Tailwind CSS frontend. In development, run the Vite dev server alongside the API:

```bash
# Terminal 1 — API
uv run uvicorn symboleo_llm_tool.api.app:app --reload

# Terminal 2 — frontend dev server (proxies /api → localhost:8000)
cd frontend
npm install
npm run dev
```

The Vite dev server runs at `http://localhost:5173`. All `/api` requests are proxied to the FastAPI server.

For production, build the frontend first, then start the API — `frontend/dist/` is mounted as a read-only volume (same pattern as `configs/`):

```bash
cd frontend && npm run build && cd ..
docker compose up symboleo-api
```

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

# Type check
uv run mypy symboleo_llm_tool
```

**Frontend:**

```bash
cd frontend

# Install dependencies
npm install

# Dev server
npm run dev

# Build
npm run build

# Generate TypeScript types from the live API schema (requires API running)
npm run generate-types
```
