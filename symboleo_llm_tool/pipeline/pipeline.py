from collections.abc import Callable
from datetime import datetime
from importlib import resources

import symboleo_llm_tool.prompts.strategies  # noqa: F401 — triggers strategy registration
from symboleo_llm_tool.config.models import PipelineConfig
from symboleo_llm_tool.llm.base import LLMAdapter
from symboleo_llm_tool.llm.factory import create_adapter
from symboleo_llm_tool.output.models import (
    CandidateResult,
    IterationRecord,
    PipelineResult,
)
from symboleo_llm_tool.prompts.base import PromptStrategy
from symboleo_llm_tool.prompts.context import PromptContext
from symboleo_llm_tool.prompts.registry import get_strategy
from symboleo_llm_tool.symboleo.models import SymboleoIssue
from symboleo_llm_tool.symboleo.wrapper import SymboleoWrapper

ProgressCallback = Callable[[int, int, list[SymboleoIssue]], None]


def run(
    contract_text: str,
    config: PipelineConfig,
    input_file: str = "",
    on_progress: ProgressCallback | None = None,
) -> PipelineResult:
    wrapper = SymboleoWrapper(config.symboleo.jar_path, config.symboleo.java_executable)
    tracing = config.observability.langsmith.enabled
    gen_llm = create_adapter(config.generation.llm, tracing_enabled=tracing)
    corr_llm = create_adapter(config.correction.llm, tracing_enabled=tracing)
    gen_strategy = get_strategy(
        config.generation.strategy, config.generation.strategy_params
    )
    corr_strategy = get_strategy(
        config.correction.strategy, config.correction.strategy_params
    )

    grammar_context = (
        _load_grammar()
        if (config.generation.include_grammar or config.correction.include_grammar)
        else None
    )

    candidates: list[CandidateResult] = []
    for i in range(config.pipeline.num_candidates):
        candidate = _run_candidate(
            candidate_id=i,
            contract_text=contract_text,
            config=config,
            wrapper=wrapper,
            gen_llm=gen_llm,
            corr_llm=corr_llm,
            gen_strategy=gen_strategy,
            corr_strategy=corr_strategy,
            grammar_context=grammar_context,
            on_progress=on_progress,
        )
        candidates.append(candidate)
        if config.pipeline.stop_on_first_convergence and candidate.converged:
            break

    return PipelineResult(
        success=any(c.converged for c in candidates),
        timestamp=datetime.now(),
        input_file=input_file,
        candidates=candidates,
    )


def _run_candidate(
    candidate_id: int,
    contract_text: str,
    config: PipelineConfig,
    wrapper: SymboleoWrapper,
    gen_llm: LLMAdapter,
    corr_llm: LLMAdapter,
    gen_strategy: PromptStrategy,
    corr_strategy: PromptStrategy,
    grammar_context: str | None,
    on_progress: ProgressCallback | None = None,
) -> CandidateResult:
    gen_context = PromptContext(
        contract_text=contract_text,
        grammar_context=grammar_context if config.generation.include_grammar else None,
    )
    prompt = gen_strategy.build_generation_prompt(gen_context)
    code = _clean_response(gen_llm.generate(prompt))

    errors = wrapper.validate(code)
    error_history = [IterationRecord(iteration=0, code=code, errors=errors)]
    if on_progress:
        on_progress(candidate_id, 0, errors)

    for iteration in range(1, config.pipeline.max_iterations + 1):
        if not errors:
            break
        corr_context = PromptContext(
            current_code=code,
            errors=errors,
            grammar_context=(
                grammar_context if config.correction.include_grammar else None
            ),
            history=error_history,
        )
        prompt = corr_strategy.build_correction_prompt(corr_context)
        code = _clean_response(corr_llm.generate(prompt))
        errors = wrapper.validate(code)
        error_history.append(
            IterationRecord(iteration=iteration, code=code, errors=errors)
        )
        if on_progress:
            on_progress(candidate_id, iteration, errors)

    return CandidateResult(
        candidate_id=candidate_id,
        final_code=code,
        converged=not errors,
        iterations_used=len(error_history) - 1,
        error_history=error_history,
    )


def _clean_response(response: str) -> str:
    """Strip markdown code fences that LLMs sometimes wrap output in."""
    response = response.strip()
    if response.startswith("```"):
        lines = response.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        response = "\n".join(lines)
    return response.strip()


def _load_grammar() -> str:
    try:
        grammar_file = resources.files("symboleo_llm_tool.resources").joinpath(
            "Symboleo.xtext"
        )
        return grammar_file.read_text(encoding="utf-8")
    except Exception:
        return ""
