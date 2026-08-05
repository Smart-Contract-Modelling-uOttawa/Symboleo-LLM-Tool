import asyncio
import json
from datetime import datetime
from pathlib import Path
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
from tests.helpers import make_issue, passthrough_threadpool

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
        with (
            patch("symboleo_llm_tool.api.routes.run_in_threadpool", passthrough_threadpool),
            patch("symboleo_llm_tool.api.routes.run_suite", return_value=result),
            patch("symboleo_llm_tool.api.routes.write_suite_results", return_value=Path("out")),
        ):
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
        with (
            patch("symboleo_llm_tool.api.routes.run_in_threadpool", passthrough_threadpool),
            patch("symboleo_llm_tool.api.routes.run_suite", return_value=_suite_result()) as m,
            patch("symboleo_llm_tool.api.routes.write_suite_results", return_value=Path("out")),
        ):
            await _run_suite(job, _suite_config(), loop)
            assert m.call_args.kwargs["cancel"] is job.cancel

    asyncio.run(run())


def test_run_suite_writes_results_before_suite_complete_event() -> None:
    # Mirror of the single-run fence: a `complete` event implies the artifact
    # exists, and the suite writer is handed the config (it carries the
    # contract, so there is no contract kwarg here).
    job = create_suite_job("suite-writes")
    result = _suite_result()
    config = _suite_config()

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with (
            patch("symboleo_llm_tool.api.routes.run_in_threadpool", passthrough_threadpool),
            patch("symboleo_llm_tool.api.routes.run_suite", return_value=result),
            patch(
                "symboleo_llm_tool.api.routes.write_suite_results",
                return_value=Path("output/suite_20260101_120000"),
            ) as mock_write,
        ):
            await _run_suite(job, config, loop)
            mock_write.assert_called_once_with(result, config)

    asyncio.run(run())

    event = job.queue.get_nowait()
    assert isinstance(event, SuiteCompleteEvent)
    assert event.output_dir == str(Path("output/suite_20260101_120000"))
    assert event.write_error is None
    assert job.output_dir == event.output_dir


def test_run_suite_write_failure_still_delivers_result() -> None:
    job = create_suite_job("suite-write-fail")
    result = _suite_result()

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with (
            patch("symboleo_llm_tool.api.routes.run_in_threadpool", passthrough_threadpool),
            patch("symboleo_llm_tool.api.routes.run_suite", return_value=result),
            patch(
                "symboleo_llm_tool.api.routes.write_suite_results",
                side_effect=OSError("disk full"),
            ),
        ):
            await _run_suite(job, _suite_config(), loop)

    asyncio.run(run())

    # job.error is reserved for pipeline failures — a write failure must not
    # make a delivered run look like a failed one.
    assert job.error is None
    event = job.queue.get_nowait()
    assert isinstance(event, SuiteCompleteEvent)
    assert event.result is result
    assert event.output_dir is None
    assert event.write_error is not None
    assert "disk full" in event.write_error


def test_suite_stream_reconnect_carries_persistence_fields(client: TestClient) -> None:
    # Fences the suite stream's on_complete lambda reading the job stash.
    job = create_suite_job("suite-reconnect")
    job.result = _suite_result()
    job.output_dir = "output/suite_20260101_120000"
    job.write_error = None
    job.completed_at = datetime.now()

    response = client.get("/api/suites/suite-reconnect/stream")

    events = _parse_all_sse(response.text)
    assert events[-1]["type"] == "complete"
    assert events[-1]["output_dir"] == "output/suite_20260101_120000"
    assert events[-1]["write_error"] is None


def test_run_suite_puts_error_event_on_exception() -> None:
    job = create_suite_job("suite-bridge-error")

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with (
            patch("symboleo_llm_tool.api.routes.run_in_threadpool", passthrough_threadpool),
            patch("symboleo_llm_tool.api.routes.run_suite", side_effect=RuntimeError("suite boom")),
            patch("symboleo_llm_tool.api.routes.write_suite_results") as mock_write,
        ):
            await _run_suite(job, _suite_config(), loop)
            # CLI parity: the suite-exception path writes nothing.
            mock_write.assert_not_called()

    asyncio.run(run())

    assert job.error == "suite boom"
    event = job.queue.get_nowait()
    assert isinstance(event, ErrorEvent)
    assert event.message == "suite boom"


def test_run_suite_progress_event_error_count_excludes_warnings() -> None:
    # The suite bridge carries its own copy of the ERROR filter; the single-run
    # test cannot cover it. Asymmetric counts (2 errors, 1 warning) separate
    # "counts errors" from "counts warnings" and from len().
    job = create_suite_job("suite-progress")

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with (
            patch("symboleo_llm_tool.api.routes.run_in_threadpool", passthrough_threadpool),
            patch("symboleo_llm_tool.api.routes.run_suite", return_value=_suite_result()) as m,
            patch("symboleo_llm_tool.api.routes.write_suite_results", return_value=Path("out")),
        ):
            await _run_suite(job, _suite_config(), loop)
            on_progress = m.call_args.kwargs["on_progress"]
            on_progress(
                1,
                0,
                2,
                [
                    make_issue(severity="ERROR"),
                    make_issue(severity="ERROR"),
                    make_issue(severity="WARNING"),
                ],
                1,
                3,
            )
            await asyncio.sleep(0)  # let call_soon_threadsafe deliver the event

    asyncio.run(run())

    events = []
    while not job.queue.empty():
        events.append(job.queue.get_nowait())
    progress = [e for e in events if isinstance(e, ProgressEvent)]
    assert len(progress) == 1
    assert progress[0].error_count == 2
    assert progress[0].experiment_index == 1
