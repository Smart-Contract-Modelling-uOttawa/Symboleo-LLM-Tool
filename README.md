# Symboleo LLM Tool

A Python CLI tool that converts plain-English legal contracts into valid [SymboleoAC](https://github.com/Smart-Contract-Modelling-uOttawa/Symboleo-IDE) contracts using an LLM, with an automatic syntax-correction loop backed by the SymboleoAC headless CLI.

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
# Edit .env and fill in your API key
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
  include_grammar: true   # inject SymboleoAC grammar into the prompt

output:
  save_intermediates: true  # save each iteration's .sl file
```

API keys are read from `.env` — never put them in config files.

## Output

Each run produces a timestamped directory under `output/`:

```
output/run_20260601_143022/
├── contract_final.sl     # final generated contract
├── report.json           # full run details: iterations, errors, convergence
├── config.yaml           # copy of the config used (for reproducibility)
└── intermediates/        # per-iteration .sl files (if save_intermediates: true)
```

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check .

# Type check
uv run mypy .
```
