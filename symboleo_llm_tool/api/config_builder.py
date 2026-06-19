from typing import Any

from pydantic import BaseModel

from symboleo_llm_tool.api._paths import EXAMPLES_DIR
from symboleo_llm_tool.api.models import StageRequest
from symboleo_llm_tool.config.models import LLMConfig, OutputConfig, RunConfig, StageConfig

_PARAM_SOURCES: dict[str, tuple[type[BaseModel], str]] = {
    "num_candidates": (RunConfig, "num_candidates"),
    "max_iterations": (RunConfig, "max_iterations"),
    "stop_on_first_convergence": (RunConfig, "stop_on_first_convergence"),
    "temperature": (LLMConfig, "temperature"),
    "include_grammar": (StageConfig, "include_grammar"),
    "save_intermediates": (OutputConfig, "save_intermediates"),
}


def resolve_provider(model: str, model_to_provider: dict[str, str]) -> str:
    if model not in model_to_provider:
        raise ValueError(f"Unknown model: {model!r}")
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


def get_parameter_defaults(ui_params: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for param_name, constraints in ui_params.items():
        entry = dict(constraints)
        if param_name in _PARAM_SOURCES:
            model_cls, field_name = _PARAM_SOURCES[param_name]
            entry["default"] = model_cls.model_fields[field_name].default
        result[param_name] = entry
    return result


def _resolve_example_paths(strategy_params: dict[str, Any]) -> dict[str, Any]:
    if "example_files" not in strategy_params:
        return strategy_params
    resolved = dict(strategy_params)
    resolved["example_files"] = [
        str(EXAMPLES_DIR / f"{name}.yaml") for name in strategy_params["example_files"]
    ]
    return resolved
