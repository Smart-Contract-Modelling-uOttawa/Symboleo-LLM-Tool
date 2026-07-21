from typing import Any

from pydantic import BaseModel

from symboleo_llm_tool.api.models import RunSettings, StageRequest, SuiteSettings
from symboleo_llm_tool.config.models import (
    Experiment,
    LLMConfig,
    OutputConfig,
    PipelineConfig,
    RunConfig,
    StageConfig,
    SuiteConfig,
)
from symboleo_llm_tool.prompts.strategies import get_strategy

_PARAM_SOURCES: dict[str, tuple[type[BaseModel], str]] = {
    "num_candidates": (RunConfig, "num_candidates"),
    "max_iterations": (RunConfig, "max_iterations"),
    "stop_on_first_convergence": (RunConfig, "stop_on_first_convergence"),
    "temperature": (LLMConfig, "temperature"),
    "include_grammar": (StageConfig, "include_grammar"),
    "save_intermediates": (OutputConfig, "save_intermediates"),
    "max_concurrency": (SuiteConfig, "max_concurrency"),
}


def resolve_provider(model: str, model_to_provider: dict[str, str]) -> str:
    if model not in model_to_provider:
        raise ValueError(f"Unknown model: {model!r}")
    return model_to_provider[model]


def build_pipeline_config(
    settings: RunSettings, model_to_provider: dict[str, str]
) -> PipelineConfig:
    """Assemble a ``PipelineConfig`` from request-layer settings.

    Shared by the single-run and suite endpoints — the only difference between
    them is what wraps these settings (a contract, or a named experiment).
    Raises ``ValueError`` on an unknown model or invalid strategy so the route
    can convert it to a 422 before any job starts.
    """
    gen_provider = resolve_provider(settings.generation.model, model_to_provider)
    corr_provider = resolve_provider(settings.effective_correction.model, model_to_provider)

    gen_stage = build_stage_config(settings.generation, gen_provider)
    corr_stage = build_stage_config(settings.effective_correction, corr_provider)

    # Early validation: instantiate both strategies so invalid strategy names or
    # missing example files surface here (→ 422) rather than as an SSE ErrorEvent.
    get_strategy(gen_stage.strategy, gen_stage.strategy_params)
    get_strategy(corr_stage.strategy, corr_stage.strategy_params)

    run_kwargs: dict[str, Any] = {}
    if settings.num_candidates is not None:
        run_kwargs["num_candidates"] = settings.num_candidates
    if settings.max_iterations is not None:
        run_kwargs["max_iterations"] = settings.max_iterations
    if settings.stop_on_first_convergence is not None:
        run_kwargs["stop_on_first_convergence"] = settings.stop_on_first_convergence

    output_kwargs: dict[str, Any] = {}
    if settings.save_intermediates is not None:
        output_kwargs["save_intermediates"] = settings.save_intermediates

    return PipelineConfig(
        generation=gen_stage,
        correction=corr_stage,
        pipeline=RunConfig(**run_kwargs),
        output=OutputConfig(**output_kwargs),
    )


def build_suite_config(
    settings: SuiteSettings, model_to_provider: dict[str, str], contract_text: str
) -> SuiteConfig:
    """Assemble a ``SuiteConfig`` from request-layer settings.

    Shared by the suite-run and suite-export endpoints. Export has no contract of
    its own and passes a placeholder, because ``SuiteConfig`` requires one and the
    exported file must not carry it (``load_suite_config`` rejects the key).
    Raises ``ValueError`` so the route can convert it to a 422.
    """
    experiments = [
        Experiment(name=exp.name, config=build_pipeline_config(exp, model_to_provider))
        for exp in settings.experiments
    ]
    kwargs: dict[str, Any] = {"contract_text": contract_text, "experiments": experiments}
    if settings.max_concurrency is not None:
        kwargs["max_concurrency"] = settings.max_concurrency
    return SuiteConfig(**kwargs)


def build_stage_config(stage_req: StageRequest, provider: str) -> StageConfig:
    llm_kwargs: dict[str, Any] = {"provider": provider, "model": stage_req.model}
    if stage_req.temperature is not None:
        llm_kwargs["temperature"] = stage_req.temperature

    stage_kwargs: dict[str, Any] = {
        "llm": LLMConfig(**llm_kwargs),
        "strategy": stage_req.strategy,
        "strategy_params": stage_req.strategy_params,
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
