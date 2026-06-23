FROM python:3.13-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

# Pin LiteLLM's model-compatibility data to the package-bundled copy for
# deterministic, offline-safe behavior (no GitHub fetch at startup). Refresh by
# bumping the litellm version. Set to False to opt into the live remote fetch.
ENV LITELLM_LOCAL_MODEL_COST_MAP=True

COPY symboleo_llm_tool/ ./symboleo_llm_tool/
RUN uv sync --frozen --no-dev

COPY lib/ ./lib/

EXPOSE 8000

ENTRYPOINT ["uvicorn", "symboleo_llm_tool.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
