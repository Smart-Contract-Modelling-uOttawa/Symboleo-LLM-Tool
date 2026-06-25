import asyncio
import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from symboleo_llm_tool import pipeline
from symboleo_llm_tool.api._paths import EXAMPLES_DIR
from symboleo_llm_tool.api.config_builder import (
    build_pipeline_config,
    get_parameter_defaults,
)
from symboleo_llm_tool.api.jobs import (
    Job,
    create_job,
    create_suite_job,
    get_job,
    get_suite_job,
)
from symboleo_llm_tool.api.models import (
    CompleteEvent,
    ErrorEvent,
    EventType,
    GenerateRequest,
    OptionsResponse,
    ProgressEvent,
    RunCreatedResponse,
    SuiteCompleteEvent,
    SuiteRequest,
)
from symboleo_llm_tool.config.models import Experiment, PipelineConfig, SuiteConfig
from symboleo_llm_tool.experiments import run_suite
from symboleo_llm_tool.llm.compatibility import pipeline_param_warnings
from symboleo_llm_tool.output.models import PipelineResult, SuiteResult
from symboleo_llm_tool.prompts.strategies import list_strategies
from symboleo_llm_tool.symboleo.models import SymboleoIssue

router = APIRouter()

_ui_config: dict[str, Any] = {}
_model_to_provider: dict[str, str] = {}


def init_router(ui_config: dict[str, Any]) -> None:
    global _ui_config, _model_to_provider
    _ui_config = ui_config
    _model_to_provider = {
        model: provider
        for provider, models in ui_config.get("models", {}).items()
        for model in models
    }


def reset_router() -> None:
    global _ui_config, _model_to_provider
    _ui_config = {}
    _model_to_provider = {}


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------


@router.post("/generate", response_model=RunCreatedResponse)
async def generate(req: GenerateRequest) -> RunCreatedResponse:
    try:
        config = build_pipeline_config(req, _model_to_provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    warnings = pipeline_param_warnings(config)

    run_id = str(uuid.uuid4())
    job = create_job(run_id)
    loop = asyncio.get_running_loop()
    job.task = asyncio.create_task(_run_pipeline(job, req.contract_text, config, loop))

    return RunCreatedResponse(run_id=run_id, warnings=warnings)


async def _run_pipeline(
    job: Job[PipelineResult],
    contract_text: str,
    config: PipelineConfig,
    loop: asyncio.AbstractEventLoop,
) -> None:
    def on_progress(
        candidate_id: int,
        iteration: int,
        errors: list[SymboleoIssue],
        _total_candidates: int,
        _total_iterations: int,
    ) -> None:
        event = ProgressEvent(
            candidate_id=candidate_id,
            iteration=iteration,
            error_count=len(errors),
        )
        loop.call_soon_threadsafe(job.queue.put_nowait, event)

    try:
        result = await run_in_threadpool(
            pipeline.run, contract_text, config, on_progress=on_progress
        )
        job.result = result
        job.completed_at = datetime.now()
        await job.queue.put(CompleteEvent(result=result))
    except Exception as exc:
        job.error = str(exc)
        job.completed_at = datetime.now()
        await job.queue.put(ErrorEvent(message=str(exc)))


# ---------------------------------------------------------------------------
# POST /suites
# ---------------------------------------------------------------------------


@router.post("/suites", response_model=RunCreatedResponse)
async def create_suite(req: SuiteRequest) -> RunCreatedResponse:
    try:
        experiments = [
            Experiment(name=exp.name, config=build_pipeline_config(exp, _model_to_provider))
            for exp in req.experiments
        ]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    suite_kwargs: dict[str, Any] = {
        "contract_text": req.contract_text,
        "experiments": experiments,
    }
    if req.max_concurrency is not None:
        suite_kwargs["max_concurrency"] = req.max_concurrency
    suite_config = SuiteConfig(**suite_kwargs)

    warnings = [
        f"{experiment.name}: {warning}"
        for experiment in suite_config.experiments
        for warning in pipeline_param_warnings(experiment.config)
    ]

    suite_id = str(uuid.uuid4())
    job = create_suite_job(suite_id)
    loop = asyncio.get_running_loop()
    job.task = asyncio.create_task(_run_suite(job, suite_config, loop))

    return RunCreatedResponse(run_id=suite_id, warnings=warnings)


async def _run_suite(
    job: Job[SuiteResult],
    suite_config: SuiteConfig,
    loop: asyncio.AbstractEventLoop,
) -> None:
    def on_progress(
        experiment_index: int,
        candidate_id: int,
        iteration: int,
        errors: list[SymboleoIssue],
        _total_candidates: int,
        _total_iterations: int,
    ) -> None:
        event = ProgressEvent(
            experiment_index=experiment_index,
            candidate_id=candidate_id,
            iteration=iteration,
            error_count=len(errors),
        )
        loop.call_soon_threadsafe(job.queue.put_nowait, event)

    try:
        result = await run_in_threadpool(run_suite, suite_config, on_progress=on_progress)
        job.result = result
        job.completed_at = datetime.now()
        await job.queue.put(SuiteCompleteEvent(result=result))
    except Exception as exc:
        job.error = str(exc)
        job.completed_at = datetime.now()
        await job.queue.put(ErrorEvent(message=str(exc)))


# ---------------------------------------------------------------------------
# SSE streams (run + suite share one multiplexing generator)
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/stream", response_model=ProgressEvent | CompleteEvent | ErrorEvent)
async def stream_run(  # type: ignore[no-untyped-def]
    run_id: str, request: Request
):  # return annotation omitted intentionally — see CLAUDE.md "SSE Schema via response_model"
    job = get_job(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found or expired")
    return await _stream_job(job, request, lambda result: CompleteEvent(result=result))


@router.get(
    "/suites/{suite_id}/stream",
    response_model=ProgressEvent | SuiteCompleteEvent | ErrorEvent,
)
async def stream_suite(  # type: ignore[no-untyped-def]
    suite_id: str, request: Request
):  # return annotation omitted intentionally — see CLAUDE.md "SSE Schema via response_model"
    job = get_suite_job(suite_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Suite {suite_id!r} not found or expired")
    return await _stream_job(job, request, lambda result: SuiteCompleteEvent(result=result))


async def _stream_job(
    job: Job[Any],
    request: Request,
    on_complete: Callable[[Any], BaseModel],
) -> StreamingResponse:
    """Drain one job's event queue to an SSE response.

    Shared by the run and suite streams; the only difference is the terminal
    completion event, supplied by ``on_complete``. Events queued by a suite
    carry an ``experiment_index`` tag — the multiplexing into this single stream
    happens on the producer side (the ``_run_suite`` callback); the client
    demultiplexes by reading that tag.
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        if job.is_complete:
            if job.result is not None:
                yield _sse(on_complete(job.result))
            elif job.error is not None:
                yield _sse(ErrorEvent(message=job.error))
            return

        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(job.queue.get(), timeout=1.0)
                yield _sse(event)
                if event.type in (EventType.COMPLETE, EventType.ERROR):
                    break
            except asyncio.TimeoutError:
                continue

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def _sse(event: BaseModel) -> str:
    return f"data: {event.model_dump_json()}\n\n"


# ---------------------------------------------------------------------------
# GET /options
# ---------------------------------------------------------------------------


@router.get("/options", response_model=OptionsResponse)
async def get_options() -> OptionsResponse:
    parameters = get_parameter_defaults(_ui_config.get("parameters", {}))
    examples = sorted(p.stem for p in EXAMPLES_DIR.glob("*.yaml")) if EXAMPLES_DIR.exists() else []
    return OptionsResponse(
        strategies=list_strategies(),
        models=_ui_config.get("models", {}),
        parameters=parameters,
        examples=examples,
    )
