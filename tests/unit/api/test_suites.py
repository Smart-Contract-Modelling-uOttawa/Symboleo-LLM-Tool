import asyncio
import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from symboleo_llm_tool.api.jobs import create_suite_job
from symboleo_llm_tool.api.models import ErrorEvent, ProgressEvent, SuiteCompleteEvent
from symboleo_llm_tool.api.routes import _run_suite
from symboleo_llm_tool.config.models import (
    Experiment,
    LLMConfig,
    PipelineConfig,
    StageConfig,
    SuiteConfig,
)
from symboleo_llm_tool.output.models import (
    CandidateResult,
    ExperimentResult,
    PipelineResult,
    SuiteResult,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_VALID_STAGE: dict[str, Any] = {"model": "gpt-4o-mini", "strategy": "zero_shot"}

_VALID_SUITE_BODY: dict[str, Any] = {
    "contract_text": "Seller shall deliver goods.",
    "experiments": [
        {"name": "zero-shot", "generation": {"model": "gpt-4o-mini", "strategy": "zero_shot"}},
        {"name": "cot", "generation": {"model": "gpt-4o-mini", "strategy": "cot"}},
    ],
}


def _parse_all_sse(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :]) for line in text.splitlines() if line.startswith("data: ")
    ]


def _pipeline_result(*, success: bool = True) -> PipelineResult:
    return PipelineResult(
        success=success,
        timestamp=datetime.now(),
        input_file="",
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


def _suite_result() -> SuiteResult:
    return SuiteResult(
        timestamp=datetime.now(),
        input_file="",
        experiments=[
            ExperimentResult(name="zero-shot", result=_pipeline_result(success=True)),
            ExperimentResult(name="cot", result=_pipeline_result(success=False)),
        ],
    )


def _suite_config() -> SuiteConfig:
    stage = StageConfig(llm=LLMConfig(provider="openai", model="gpt-4o-mini"), strategy="zero_shot")
    config = PipelineConfig(generation=stage, correction=stage)
    return SuiteConfig(
        contract_text="Seller shall deliver goods.",
        experiments=[Experiment(name="zero-shot", config=config)],
    )


# ---------------------------------------------------------------------------
# POST /suites
# ---------------------------------------------------------------------------


def test_create_suite_returns_run_id(client: TestClient, patch_run_suite: None) -> None:
    response = client.post("/api/suites", json=_VALID_SUITE_BODY)
    assert response.status_code == 200
    assert "run_id" in response.json()


def test_create_suite_unknown_model_returns_422(client: TestClient) -> None:
    body = {
        "contract_text": "Seller delivers.",
        "experiments": [{"name": "a", "generation": {**_VALID_STAGE, "model": "nope"}}],
    }
    response = client.post("/api/suites", json=body)
    assert response.status_code == 422
    assert "Unknown model" in response.json()["detail"]


def test_create_suite_unknown_strategy_returns_422(client: TestClient) -> None:
    body = {
        "contract_text": "Seller delivers.",
        "experiments": [{"name": "a", "generation": {**_VALID_STAGE, "strategy": "telepathy"}}],
    }
    response = client.post("/api/suites", json=body)
    assert response.status_code == 422
    assert "Unknown strategy" in response.json()["detail"]


def test_create_suite_empty_experiments_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/suites", json={"contract_text": "Seller delivers.", "experiments": []}
    )
    assert response.status_code == 422


def test_create_suite_duplicate_names_returns_422(client: TestClient) -> None:
    body = {
        "contract_text": "Seller delivers.",
        "experiments": [
            {"name": "dup", "generation": _VALID_STAGE},
            {"name": "dup", "generation": _VALID_STAGE},
        ],
    }
    response = client.post("/api/suites", json=body)
    assert response.status_code == 422


def test_create_suite_empty_contract_returns_422(client: TestClient) -> None:
    body = {**_VALID_SUITE_BODY, "contract_text": "   "}
    response = client.post("/api/suites", json=body)
    assert response.status_code == 422


def test_cancel_suite_trips_the_token(client: TestClient) -> None:
    # The shared cancel endpoint works for suite jobs too (one store, unique ids).
    job = create_suite_job("cancel-suite")
    response = client.post("/api/runs/cancel-suite/cancel")
    assert response.status_code == 204
    assert job.cancel.cancelled is True


def test_create_suite_forwards_max_concurrency_to_config(client: TestClient) -> None:
    body = {**_VALID_SUITE_BODY, "max_concurrency": 4}
    with patch("symboleo_llm_tool.api.routes._run_suite", new_callable=AsyncMock) as mock_run:
        response = client.post("/api/suites", json=body)
    assert response.status_code == 200
    # _run_suite(job, suite_config, loop) — inspect the config it was handed.
    suite_config = mock_run.call_args.args[1]
    assert suite_config.max_concurrency == 4


def test_create_suite_uses_default_max_concurrency_when_omitted(client: TestClient) -> None:
    with patch("symboleo_llm_tool.api.routes._run_suite", new_callable=AsyncMock) as mock_run:
        response = client.post("/api/suites", json=_VALID_SUITE_BODY)
    assert response.status_code == 200
    suite_config = mock_run.call_args.args[1]
    assert suite_config.max_concurrency == 2


def test_create_suite_labels_warnings_by_experiment_name(
    client: TestClient, patch_run_suite: None
) -> None:
    # pipeline_param_warnings is patched to return one warning per experiment;
    # the route must prefix each with that experiment's name.
    with patch(
        "symboleo_llm_tool.llm.compatibility.pipeline_param_warnings",
        return_value=["generation: temperature will be ignored"],
    ):
        response = client.post("/api/suites", json=_VALID_SUITE_BODY)
    assert response.status_code == 200
    assert response.json()["warnings"] == [
        "zero-shot: generation: temperature will be ignored",
        "cot: generation: temperature will be ignored",
    ]


# ---------------------------------------------------------------------------
# GET /suites/{suite_id}/stream
# ---------------------------------------------------------------------------


def test_suite_stream_unknown_id_returns_404(client: TestClient) -> None:
    response = client.get("/api/suites/does-not-exist/stream")
    assert response.status_code == 404


def test_suite_stream_complete_job_yields_suite_complete_event(client: TestClient) -> None:
    job = create_suite_job("suite-complete")
    job.result = _suite_result()
    job.completed_at = datetime.now()

    response = client.get("/api/suites/suite-complete/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_all_sse(response.text)
    assert events[-1]["type"] == "complete"
    names = [e["name"] for e in events[-1]["result"]["experiments"]]
    assert names == ["zero-shot", "cot"]


def test_suite_stream_multiplexes_progress_with_experiment_index(client: TestClient) -> None:
    job = create_suite_job("suite-live")
    job.queue.put_nowait(
        ProgressEvent(experiment_index=0, candidate_id=0, iteration=0, error_count=1)
    )
    job.queue.put_nowait(
        ProgressEvent(experiment_index=1, candidate_id=0, iteration=0, error_count=0)
    )
    job.queue.put_nowait(SuiteCompleteEvent(result=_suite_result()))

    response = client.get("/api/suites/suite-live/stream")

    events = _parse_all_sse(response.text)
    assert [e["experiment_index"] for e in events[:2]] == [0, 1]
    assert events[-1]["type"] == "complete"


def test_suite_stream_error_job_yields_error_event(client: TestClient) -> None:
    job = create_suite_job("suite-error")
    job.error = "suite exploded"
    job.completed_at = datetime.now()

    response = client.get("/api/suites/suite-error/stream")

    events = _parse_all_sse(response.text)
    assert events[-1]["type"] == "error"
    assert "suite exploded" in events[-1]["message"]


# ---------------------------------------------------------------------------
# _run_suite: async bridge
# ---------------------------------------------------------------------------


def test_run_suite_puts_suite_complete_event_on_queue() -> None:
    job = create_suite_job("suite-bridge-complete")
    result = _suite_result()

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with patch(
            "symboleo_llm_tool.api.routes.run_in_threadpool", new_callable=AsyncMock
        ) as mock_tp:
            mock_tp.return_value = result
            await _run_suite(job, _suite_config(), loop)

    asyncio.run(run())

    assert job.result is result
    assert job.completed_at is not None
    event = job.queue.get_nowait()
    assert isinstance(event, SuiteCompleteEvent)
    assert event.result is result


def test_run_suite_forwards_job_cancel_token() -> None:
    job = create_suite_job("suite-cancel")

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with patch(
            "symboleo_llm_tool.api.routes.run_in_threadpool", new_callable=AsyncMock
        ) as mock_tp:
            mock_tp.return_value = _suite_result()
            await _run_suite(job, _suite_config(), loop)
            assert mock_tp.call_args.kwargs["cancel"] is job.cancel

    asyncio.run(run())


def test_run_suite_puts_error_event_on_exception() -> None:
    job = create_suite_job("suite-bridge-error")

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with patch(
            "symboleo_llm_tool.api.routes.run_in_threadpool", new_callable=AsyncMock
        ) as mock_tp:
            mock_tp.side_effect = RuntimeError("suite boom")
            await _run_suite(job, _suite_config(), loop)

    asyncio.run(run())

    assert job.error == "suite boom"
    event = job.queue.get_nowait()
    assert isinstance(event, ErrorEvent)
    assert event.message == "suite boom"
