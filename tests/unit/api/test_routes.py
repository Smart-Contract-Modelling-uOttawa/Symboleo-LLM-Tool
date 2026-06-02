import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from symboleo_llm_tool.api.jobs import create_job
from symboleo_llm_tool.output.models import CandidateResult, PipelineResult

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_VALID_STAGE: dict[str, Any] = {
    "model": "gpt-4o-mini",
    "strategy": "zero_shot",
}

_VALID_BODY: dict[str, Any] = {
    "contract_text": "Seller shall deliver goods.",
    "generation": _VALID_STAGE,
}


def _make_pipeline_result(*, success: bool = True) -> PipelineResult:
    return PipelineResult(
        success=success,
        timestamp=datetime.now(),
        input_file="test.txt",
        candidates=[
            CandidateResult(
                candidate_id=0,
                final_code="Contract Test() {}",
                converged=success,
                iterations_used=0,
                error_history=[],
            )
        ],
    )


def _parse_sse(text: str) -> dict[str, Any]:
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: "):])  # type: ignore[no-any-return]
    raise AssertionError(f"No SSE data frame found in: {text!r}")


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------


def test_generate_returns_run_id(client: TestClient) -> None:
    with patch("symboleo_llm_tool.api.routes._run_pipeline", new_callable=AsyncMock):
        response = client.post("/generate", json=_VALID_BODY)
    assert response.status_code == 200
    assert "run_id" in response.json()


def test_generate_unknown_model_returns_422(client: TestClient) -> None:
    body = {**_VALID_BODY, "generation": {**_VALID_STAGE, "model": "unknown-model"}}
    response = client.post("/generate", json=body)
    assert response.status_code == 422
    assert "Unknown model" in response.json()["detail"]


def test_generate_unknown_strategy_returns_422(client: TestClient) -> None:
    body = {**_VALID_BODY, "generation": {**_VALID_STAGE, "strategy": "telepathy"}}
    response = client.post("/generate", json=body)
    assert response.status_code == 422
    assert "Unknown strategy" in response.json()["detail"]


def test_generate_empty_contract_text_returns_422(client: TestClient) -> None:
    response = client.post("/generate", json={**_VALID_BODY, "contract_text": ""})
    assert response.status_code == 422


def test_generate_whitespace_contract_text_returns_422(client: TestClient) -> None:
    response = client.post("/generate", json={**_VALID_BODY, "contract_text": "   "})
    assert response.status_code == 422


def test_generate_missing_example_returns_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.chdir(tmp_path)  # tmp_path has no examples/ dir
    body = {
        **_VALID_BODY,
        "generation": {
            **_VALID_STAGE,
            "strategy": "few_shot",
            "strategy_params": {"example_files": ["any_example"]},
        },
    }
    response = client.post("/generate", json=body)
    assert response.status_code == 422
    assert "Example not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/stream
# ---------------------------------------------------------------------------


def test_stream_unknown_run_id_returns_404(client: TestClient) -> None:
    response = client.get("/runs/does-not-exist/stream")
    assert response.status_code == 404


def test_stream_complete_job_yields_complete_event(client: TestClient) -> None:
    job = create_job("test-run-complete")
    job.result = _make_pipeline_result(success=True)
    job.completed_at = datetime.now()

    response = client.get("/runs/test-run-complete/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    payload = _parse_sse(response.text)
    assert payload["type"] == "complete"
    assert payload["result"]["success"] is True


def test_stream_error_job_yields_error_event(client: TestClient) -> None:
    job = create_job("test-run-error")
    job.error = "pipeline exploded"
    job.completed_at = datetime.now()

    response = client.get("/runs/test-run-error/stream")

    payload = _parse_sse(response.text)
    assert payload["type"] == "error"
    assert "pipeline exploded" in payload["message"]


# ---------------------------------------------------------------------------
# GET /options
# ---------------------------------------------------------------------------


def test_options_returns_known_strategies(client: TestClient) -> None:
    response = client.get("/options")
    assert response.status_code == 200
    strategies = response.json()["strategies"]
    assert "zero_shot" in strategies
    assert "few_shot" in strategies
    assert "cot" in strategies


def test_options_returns_models_from_config(client: TestClient) -> None:
    response = client.get("/options")
    models = response.json()["models"]
    assert "gpt-4o-mini" in models["openai"]
    assert "claude-haiku-4-5" in models["anthropic"]


def test_options_examples_empty_when_no_examples_dir(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.chdir(tmp_path)  # tmp_path has no examples/ dir
    response = client.get("/options")
    assert response.json()["examples"] == []
