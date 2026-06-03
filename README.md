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

**Native usage:**
- Python 3.11+
- Java 11+ ([Adoptium](https://adoptium.net/))
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

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
```

## Usage

### Native

```bash
uv run symboleo-tool <contract.txt> --config configs/openai.yaml
```

### Docker

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
| `mock.yaml` | Mock LLM for testing without an API key (temporary) |

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
  save_intermediates: true  # save each iteration's .sl file
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
├── contract_final.sl     # final generated contract
├── report.json           # full run details: iterations, errors, convergence
├── config.yaml           # copy of the config used (for reproducibility)
└── intermediates/        # per-iteration .sl files (if save_intermediates: true)
```

## API (Web Service)

The FastAPI server exposes three endpoints:

- `POST /generate` — submit a contract and config, returns a `run_id`
- `GET /runs/{run_id}/stream` — SSE stream of progress and final result
- `GET /options` — available models, strategies, and parameter constraints

### Running the API

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

A React/Vite + shadcn/ui + Tailwind CSS frontend is planned, served as static files from FastAPI (`GET /`). Not yet started.

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
