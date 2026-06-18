import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import symboleo_llm_tool.prompts.strategies  # noqa: F401 — triggers strategy registration
from symboleo_llm_tool import pipeline
from symboleo_llm_tool.api.config_builder import build_stage_config, resolve_provider
from symboleo_llm_tool.api.jobs import Job, create_job, get_job
from symboleo_llm_tool.api.models import (
    CompleteEvent,
    ErrorEvent,
    GenerateRequest,
    OptionsResponse,
    ProgressEvent,
    RunCreatedResponse,
)
from symboleo_llm_tool.config.models import (
    LLMConfig,
    OutputConfig,
    PipelineConfig,
    RunConfig,
    StageConfig,
)
from symboleo_llm_tool.prompts.registry import get_strategy, list_strategies
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
        gen_provider = resolve_provider(req.generation.model, _model_to_provider)
        corr_provider = resolve_provider(req.effective_correction.model, _model_to_provider)

        gen_stage = build_stage_config(req.generation, gen_provider)
        corr_stage = build_stage_config(req.effective_correction, corr_provider)

        # Early validation: instantiate both strategies synchronously so invalid strategy names
        # or missing example files surface as a 422 rather than an ErrorEvent on the SSE stream.
        get_strategy(gen_stage.strategy, gen_stage.strategy_params)
        get_strategy(corr_stage.strategy, corr_stage.strategy_params)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run_kwargs: dict[str, Any] = {}
    if req.num_candidates is not None:
        run_kwargs["num_candidates"] = req.num_candidates
    if req.max_iterations is not None:
        run_kwargs["max_iterations"] = req.max_iterations
    if req.stop_on_first_convergence is not None:
        run_kwargs["stop_on_first_convergence"] = req.stop_on_first_convergence

    output_kwargs: dict[str, Any] = {}
    if req.save_intermediates is not None:
        output_kwargs["save_intermediates"] = req.save_intermediates

    config = PipelineConfig(
        generation=gen_stage,
        correction=corr_stage,
        pipeline=RunConfig(**run_kwargs),
        output=OutputConfig(**output_kwargs),
    )

    run_id = str(uuid.uuid4())
    job = create_job(run_id)
    loop = asyncio.get_running_loop()
    job.task = asyncio.create_task(_run_pipeline(job, req.contract_text, config, loop))

    return RunCreatedResponse(run_id=run_id)


async def _run_pipeline(
    job: Job,
    contract_text: str,
    config: PipelineConfig,
    loop: asyncio.AbstractEventLoop,
) -> None:
    def on_progress(
        candidate_id: int,
        iteration: int,
        errors: list[SymboleoIssue],
        total_candidates: int,
        total_iterations: int,
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
# GET /runs/{run_id}/stream
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/stream", response_model=ProgressEvent | CompleteEvent | ErrorEvent)
async def stream_run(  # type: ignore[no-untyped-def]
    run_id: str, request: Request
):  # return annotation omitted intentionally — see CLAUDE.md "SSE Schema via response_model"
    job = get_job(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found or expired")

    async def event_generator() -> AsyncGenerator[str, None]:
        if job.is_complete:
            if job.result is not None:
                yield _sse(CompleteEvent(result=job.result))
            elif job.error is not None:
                yield _sse(ErrorEvent(message=job.error))
            return

        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(job.queue.get(), timeout=1.0)
                yield _sse(event)
                if isinstance(event, (CompleteEvent, ErrorEvent)):
                    break
            except asyncio.TimeoutError:
                continue

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def _sse(event: ProgressEvent | CompleteEvent | ErrorEvent) -> str:
    return f"data: {event.model_dump_json()}\n\n"


# ---------------------------------------------------------------------------
# GET /options
# ---------------------------------------------------------------------------

_PARAM_SOURCES: dict[str, tuple[type[BaseModel], str]] = {
    "num_candidates": (RunConfig, "num_candidates"),
    "max_iterations": (RunConfig, "max_iterations"),
    "stop_on_first_convergence": (RunConfig, "stop_on_first_convergence"),
    "temperature": (LLMConfig, "temperature"),
    "include_grammar": (StageConfig, "include_grammar"),
    "save_intermediates": (OutputConfig, "save_intermediates"),
}


@router.get("/options", response_model=OptionsResponse)
async def get_options() -> OptionsResponse:
    parameters: dict[str, Any] = {}
    for param_name, constraints in _ui_config.get("parameters", {}).items():
        entry = dict(constraints)
        if param_name in _PARAM_SOURCES:
            model_cls, field_name = _PARAM_SOURCES[param_name]
            entry["default"] = model_cls.model_fields[field_name].default
        parameters[param_name] = entry

    examples_dir = Path("examples")
    examples = sorted(p.stem for p in examples_dir.glob("*.yaml")) if examples_dir.exists() else []

    return OptionsResponse(
        strategies=list_strategies(),
        models=_ui_config.get("models", {}),
        parameters=parameters,
        examples=examples,
    )
