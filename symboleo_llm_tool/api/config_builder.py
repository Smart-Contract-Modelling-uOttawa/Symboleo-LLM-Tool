from pathlib import Path
from typing import Any

from fastapi import HTTPException

from symboleo_llm_tool.api.models import StageRequest
from symboleo_llm_tool.config.models import LLMConfig, StageConfig


def resolve_provider(model: str, model_to_provider: dict[str, str]) -> str:
    if model not in model_to_provider:
        raise HTTPException(status_code=422, detail=f"Unknown model: {model!r}")
    return model_to_provider[model]


def build_stage_config(stage_req: StageRequest, provider: str) -> StageConfig:
    llm_kwargs: dict[str, Any] = {"provider": provider, "model": stage_req.model}
    if stage_req.temperature is not None:
        llm_kwargs["temperature"] = stage_req.temperature

    stage_kwargs: dict[str, Any] = {
        "llm": LLMConfig(**llm_kwargs),
        "strategy": stage_req.strategy,
        "strategy_params": _resolve_example_paths(stage_req.strategy_params),
    }
    if stage_req.include_grammar is not None:
        stage_kwargs["include_grammar"] = stage_req.include_grammar

    return StageConfig(**stage_kwargs)


def _resolve_example_paths(strategy_params: dict[str, Any]) -> dict[str, Any]:
    if "example_files" not in strategy_params:
        return strategy_params
    resolved = dict(strategy_params)
    resolved["example_files"] = [
        str(Path("examples") / f"{name}.yaml") for name in strategy_params["example_files"]
    ]
    return resolved
