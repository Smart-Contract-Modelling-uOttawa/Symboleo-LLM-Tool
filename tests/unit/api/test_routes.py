import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from symboleo_llm_tool.api.jobs import create_job
from symboleo_llm_tool.api.models import CompleteEvent, ErrorEvent, ProgressEvent
from symboleo_llm_tool.api.routes import _run_pipeline, _stream_job
from symboleo_llm_tool.config.models import LLMConfig, PipelineConfig, StageConfig
from symboleo_llm_tool.output.models import CandidateResult, PipelineResult
from tests.helpers import make_issue, passthrough_threadpool

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
            return json.loads(line[len("data: ") :])  # type: ignore[no-any-return]
    raise AssertionError(f"No SSE data frame found in: {text!r}")


def _parse_all_sse(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :]) for line in text.splitlines() if line.startswith("data: ")
    ]


def _make_pipeline_config() -> PipelineConfig:
    stage = StageConfig(llm=LLMConfig(provider="openai", model="gpt-4o-mini"), strategy="zero_shot")
    return PipelineConfig(generation=stage, correction=stage)


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------


def test_generate_returns_run_id(client: TestClient, patch_run_pipeline: None) -> None:
    response = client.post("/api/generate", json=_VALID_BODY)
    assert response.status_code == 200
    assert "run_id" in response.json()


def test_generate_unknown_model_returns_422(client: TestClient) -> None:
    body = {**_VALID_BODY, "generation": {**_VALID_STAGE, "model": "unknown-model"}}
    response = client.post("/api/generate", json=body)
    assert response.status_code == 422
    assert "Unknown model" in response.json()["detail"]


def test_generate_unknown_strategy_returns_422(client: TestClient) -> None:
    body = {**_VALID_BODY, "generation": {**_VALID_STAGE, "strategy": "telepathy"}}
    response = client.post("/api/generate", json=body)
    assert response.status_code == 422
    assert "Unknown strategy" in response.json()["detail"]


def test_generate_empty_contract_text_returns_422(client: TestClient) -> None:
    response = client.post("/api/generate", json={**_VALID_BODY, "contract_text": ""})
    assert response.status_code == 422


def test_generate_whitespace_contract_text_returns_422(client: TestClient) -> None:
    response = client.post("/api/generate", json={**_VALID_BODY, "contract_text": "   "})
    assert response.status_code == 422


def test_generate_missing_example_returns_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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
    response = client.post("/api/generate", json=body)
    assert response.status_code == 422
    assert "Example 'any_example' not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/stream
# ---------------------------------------------------------------------------


def test_stream_unknown_run_id_returns_404(client: TestClient) -> None:
    response = client.get("/api/runs/does-not-exist/stream")
    assert response.status_code == 404


def test_stream_complete_job_yields_complete_event(client: TestClient) -> None:
    job = create_job("test-run-complete")
    job.result = _make_pipeline_result(success=True)
    job.completed_at = datetime.now()

    response = client.get("/api/runs/test-run-complete/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    payload = _parse_sse(response.text)
    assert payload["type"] == "complete"
    assert payload["result"]["success"] is True


def test_stream_complete_job_reconnect_carries_persistence_fields(client: TestClient) -> None:
    # The reconnect branch rebuilds the terminal event from the job's stash;
    # without it a client that reconnects after completion gets blanked fields.
    # This test uses the write-failure state; the suite mirror uses the success
    # state, so between them both fields are pinned on the reconnect path.
    job = create_job("test-run-reconnect")
    job.result = _make_pipeline_result(success=True)
    job.write_error = "Results were not written to disk: disk full"
    job.completed_at = datetime.now()

    response = client.get("/api/runs/test-run-reconnect/stream")

    payload = _parse_sse(response.text)
    assert payload["type"] == "complete"
    assert payload["output_dir"] is None
    assert payload["write_error"] == "Results were not written to disk: disk full"


def test_stream_error_job_yields_error_event(client: TestClient) -> None:
    job = create_job("test-run-error")
    job.error = "pipeline exploded"
    job.completed_at = datetime.now()

    response = client.get("/api/runs/test-run-error/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    payload = _parse_sse(response.text)
    assert payload["type"] == "error"
    assert "pipeline exploded" in payload["message"]


# ---------------------------------------------------------------------------
# GET /options
# ---------------------------------------------------------------------------


def test_options_returns_known_strategies(client: TestClient) -> None:
    response = client.get("/api/options")
    assert response.status_code == 200
    strategies = response.json()["strategies"]
    assert "zero_shot" in strategies
    assert "few_shot" in strategies
    assert "cot" in strategies


def test_options_returns_models_from_config(client: TestClient) -> None:
    response = client.get("/api/options")
    models = response.json()["models"]
    assert "gpt-4o-mini" in models["openai"]
    assert "claude-haiku-4-5" in models["anthropic"]


def test_options_examples_empty_when_no_examples_dir(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # tmp_path has no examples/ dir
    response = client.get("/api/options")
    assert response.json()["examples"] == []


def test_options_returns_parameter_defaults(client: TestClient, parameters_config: None) -> None:
    response = client.get("/api/options")
    params = response.json()["parameters"]
    assert params["num_candidates"]["default"] == 1
    # temperature has no default (None) so it is only sent when set.
    assert params["temperature"]["default"] is None


def test_options_returns_max_concurrency_default(
    client: TestClient, parameters_config: None
) -> None:
    response = client.get("/api/options")
    param = response.json()["parameters"]["max_concurrency"]
    assert param["default"] == 2  # SuiteConfig default
    assert (param["min"], param["max"]) == (1, 8)


# ---------------------------------------------------------------------------
# POST /runs/{run_id}/cancel
# ---------------------------------------------------------------------------


def test_cancel_run_trips_the_token(client: TestClient) -> None:
    job = create_job("cancel-me")
    response = client.post("/api/runs/cancel-me/cancel")
    assert response.status_code == 204
    assert job.cancel.cancelled is True


def test_cancel_unknown_run_returns_404(client: TestClient) -> None:
    response = client.post("/api/runs/does-not-exist/cancel")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /generate: correction stage
# ---------------------------------------------------------------------------


def test_generate_with_unknown_correction_strategy_returns_422(client: TestClient) -> None:
    body = {**_VALID_BODY, "correction": {**_VALID_STAGE, "strategy": "telepathy"}}
    response = client.post("/api/generate", json=body)
    assert response.status_code == 422
    assert "Unknown strategy" in response.json()["detail"]


def test_generate_with_explicit_correction_stage_returns_run_id(
    client: TestClient, patch_run_pipeline: None
) -> None:
    body = {**_VALID_BODY, "correction": _VALID_STAGE}
    response = client.post("/api/generate", json=body)
    assert response.status_code == 200
    assert "run_id" in response.json()


def test_generate_returns_no_warnings_for_non_reasoning_model(
    client: TestClient, patch_run_pipeline: None
) -> None:
    response = client.post("/api/generate", json=_VALID_BODY)
    assert response.status_code == 200
    assert response.json()["warnings"] == []


def test_generate_surfaces_param_warnings_in_response(
    client: TestClient, patch_run_pipeline: None
) -> None:
    # Wiring only: whatever pipeline_param_warnings returns reaches the response.
    # Stage labeling itself is covered in test_compatibility.py.
    with patch(
        "symboleo_llm_tool.api.routes.pipeline_param_warnings",
        return_value=["generation: temperature will be ignored"],
    ):
        response = client.post("/api/generate", json=_VALID_BODY)
    assert response.status_code == 200
    assert response.json()["warnings"] == ["generation: temperature will be ignored"]


# ---------------------------------------------------------------------------
# POST /generate: optional stage and pipeline fields
# ---------------------------------------------------------------------------


def test_generate_with_temperature_and_include_grammar(
    client: TestClient, patch_run_pipeline: None
) -> None:
    body = {
        **_VALID_BODY,
        "generation": {**_VALID_STAGE, "temperature": 0.5, "include_grammar": False},
    }
    response = client.post("/api/generate", json=body)
    assert response.status_code == 200


def test_generate_with_optional_pipeline_kwargs(
    client: TestClient, patch_run_pipeline: None
) -> None:
    body = {
        **_VALID_BODY,
        "num_candidates": 2,
        "max_iterations": 5,
        "stop_on_first_convergence": True,
        "save_intermediates": True,
    }
    response = client.post("/api/generate", json=body)
    assert response.status_code == 200
    assert "run_id" in response.json()


def test_generate_with_valid_few_shot_example(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, patch_run_pipeline: None
) -> None:
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir()
    (examples_dir / "my_example.yaml").write_text(
        "contract_text: 'Buyer pays.'\nsymboleo_code: 'Contract C(){}'\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    body = {
        **_VALID_BODY,
        "generation": {
            **_VALID_STAGE,
            "strategy": "few_shot",
            "strategy_params": {"example_files": ["my_example"]},
        },
    }
    response = client.post("/api/generate", json=body)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/stream: live path
# ---------------------------------------------------------------------------


def test_stream_in_progress_job_yields_progress_then_complete(client: TestClient) -> None:
    job = create_job("test-run-live")
    result = _make_pipeline_result(success=True)
    job.queue.put_nowait(ProgressEvent(candidate_id=0, iteration=0, error_count=2))
    job.queue.put_nowait(CompleteEvent(result=result))

    response = client.get("/api/runs/test-run-live/stream")

    assert response.status_code == 200
    events = _parse_all_sse(response.text)
    assert len(events) == 2
    assert events[0]["type"] == "progress"
    assert events[0]["error_count"] == 2
    assert events[1]["type"] == "complete"


class _StubRequest:
    """Minimal stand-in for ``Request`` — ``_stream_job`` only polls disconnect."""

    def __init__(self, disconnected: bool) -> None:
        self._disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self._disconnected


async def _drain(job: Any, request: _StubRequest) -> None:
    response = await _stream_job(job, request, lambda result: CompleteEvent(result=result))
    async for _ in response.body_iterator:
        pass


def test_stream_marks_job_detached_when_client_disconnects() -> None:
    # detached_at is the only signal cancel_abandoned() keys on — if the stream
    # stops stamping it, grace cancellation never fires for any job.
    job = create_job("stream-detached")

    asyncio.run(_drain(job, _StubRequest(disconnected=True)))

    assert job.detached_at is not None


def test_stream_marks_job_attached_clearing_an_earlier_detach() -> None:
    job = create_job("stream-reattach")
    job.detached_at = datetime.now()  # a previous stream dropped
    job.queue.put_nowait(CompleteEvent(result=_make_pipeline_result()))

    asyncio.run(_drain(job, _StubRequest(disconnected=False)))

    assert job.detached_at is None


# ---------------------------------------------------------------------------
# _run_pipeline: async bridge
# ---------------------------------------------------------------------------


def test_run_pipeline_puts_complete_event_on_queue() -> None:
    job = create_job("pipe-complete")
    result = _make_pipeline_result(success=True)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with (
            patch("symboleo_llm_tool.api.routes.run_in_threadpool", passthrough_threadpool),
            patch("symboleo_llm_tool.pipeline.run", return_value=result),
            patch("symboleo_llm_tool.api.routes.write_results", return_value=Path("out")),
        ):
            await _run_pipeline(job, "contract text", _make_pipeline_config(), loop)

    asyncio.run(run())

    assert job.result is result
    assert job.completed_at is not None
    event = job.queue.get_nowait()
    assert isinstance(event, CompleteEvent)
    assert event.result is result


def test_run_pipeline_forwards_job_cancel_token() -> None:
    # Without this kwarg the Stop button is a no-op for every single run.
    job = create_job("pipe-cancel")

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with (
            patch("symboleo_llm_tool.api.routes.run_in_threadpool", passthrough_threadpool),
            patch(
                "symboleo_llm_tool.pipeline.run", return_value=_make_pipeline_result()
            ) as mock_run,
            patch("symboleo_llm_tool.api.routes.write_results", return_value=Path("out")),
        ):
            await _run_pipeline(job, "contract text", _make_pipeline_config(), loop)
            assert mock_run.call_args.kwargs["cancel"] is job.cancel

    asyncio.run(run())


def test_run_pipeline_writes_results_before_complete_event() -> None:
    # A `complete` event implies the artifact exists (or write_error says why
    # not) — so the write must happen before the terminal event is queued, and
    # the event must carry where it landed.
    job = create_job("pipe-writes")
    result = _make_pipeline_result(success=True)
    config = _make_pipeline_config()

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with (
            patch("symboleo_llm_tool.api.routes.run_in_threadpool", passthrough_threadpool),
            patch("symboleo_llm_tool.pipeline.run", return_value=result),
            patch(
                "symboleo_llm_tool.api.routes.write_results",
                return_value=Path("output/run_20260101_120000"),
            ) as mock_write,
        ):
            await _run_pipeline(job, "contract text", config, loop)
            mock_write.assert_called_once_with(result, config, contract_text="contract text")

    asyncio.run(run())

    event = job.queue.get_nowait()
    assert isinstance(event, CompleteEvent)
    assert event.output_dir == str(Path("output/run_20260101_120000"))
    assert event.write_error is None
    # Stashed on the job too — the reconnect branch rebuilds the event from it.
    assert job.output_dir == event.output_dir


def test_run_pipeline_write_failure_still_delivers_result() -> None:
    # The run succeeded; only the disk failed. The result the client is waiting
    # for must still arrive, with the failure named on the same event.
    job = create_job("pipe-write-fail")
    result = _make_pipeline_result(success=True)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with (
            patch("symboleo_llm_tool.api.routes.run_in_threadpool", passthrough_threadpool),
            patch("symboleo_llm_tool.pipeline.run", return_value=result),
            patch("symboleo_llm_tool.api.routes.write_results", side_effect=OSError("disk full")),
        ):
            await _run_pipeline(job, "contract text", _make_pipeline_config(), loop)

    asyncio.run(run())

    # job.error is reserved for pipeline failures — a write failure must not
    # make a delivered run look like a failed one.
    assert job.error is None
    assert job.output_dir is None
    event = job.queue.get_nowait()
    assert isinstance(event, CompleteEvent)
    assert event.result is result
    assert event.output_dir is None
    assert event.write_error is not None
    assert "disk full" in event.write_error
    assert job.write_error == event.write_error


def test_run_pipeline_puts_error_event_on_exception() -> None:
    job = create_job("pipe-error")

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with (
            patch("symboleo_llm_tool.api.routes.run_in_threadpool", passthrough_threadpool),
            patch("symboleo_llm_tool.pipeline.run", side_effect=RuntimeError("pipeline boom")),
            patch("symboleo_llm_tool.api.routes.write_results") as mock_write,
        ):
            await _run_pipeline(job, "contract text", _make_pipeline_config(), loop)
            # CLI parity: the pipeline-exception path writes nothing — there is
            # no result to persist, and half-writing would mask the failure.
            mock_write.assert_not_called()

    asyncio.run(run())

    assert job.error == "pipeline boom"
    assert job.completed_at is not None
    event = job.queue.get_nowait()
    assert isinstance(event, ErrorEvent)
    assert event.message == "pipeline boom"


def test_run_pipeline_progress_event_error_count_excludes_warnings() -> None:
    # error_count means blocking errors: a warning must not inflate the live
    # counter the way it must not block convergence.
    job = create_job("pipe-progress")

    async def run() -> None:
        loop = asyncio.get_running_loop()
        with (
            patch("symboleo_llm_tool.api.routes.run_in_threadpool", passthrough_threadpool),
            patch(
                "symboleo_llm_tool.pipeline.run", return_value=_make_pipeline_result()
            ) as mock_run,
            patch("symboleo_llm_tool.api.routes.write_results", return_value=Path("out")),
        ):
            await _run_pipeline(job, "contract text", _make_pipeline_config(), loop)
            on_progress = mock_run.call_args.kwargs["on_progress"]
            # Asymmetric counts on purpose: 2 errors vs 1 warning separates
            # "counts errors" from "counts warnings", from len(), and from 0.
            on_progress(
                0,
                1,
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
