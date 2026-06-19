from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from importlib import resources

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
from symboleo_llm_tool.prompts.strategies import get_strategy
from symboleo_llm_tool.symboleo.models import SymboleoIssue
from symboleo_llm_tool.symboleo.wrapper import SymboleoWrapper

ProgressCallback = Callable[[int, int, list[SymboleoIssue], int, int], None]

_GRAMMAR_PACKAGE = "symboleo_llm_tool.resources"
_GRAMMAR_FILE = "Symboleo.xtext"


@dataclass(frozen=True)
class _RunContext:
    wrapper: SymboleoWrapper
    gen_llm: LLMAdapter
    corr_llm: LLMAdapter
    gen_strategy: PromptStrategy
    corr_strategy: PromptStrategy
    grammar_context: str | None
    gen_include_grammar: bool
    corr_include_grammar: bool
    num_candidates: int
    max_iterations: int
    stop_on_first_convergence: bool
    on_progress: ProgressCallback | None


def run(
    contract_text: str,
    config: PipelineConfig,
    input_file: str = "",
    on_progress: ProgressCallback | None = None,
) -> PipelineResult:
    tracing = config.observability.langsmith.enabled
    ctx = _RunContext(
        wrapper=SymboleoWrapper(config.symboleo.jar_path, config.symboleo.java_executable),
        gen_llm=create_adapter(config.generation.llm, tracing_enabled=tracing),
        corr_llm=create_adapter(config.correction.llm, tracing_enabled=tracing),
        gen_strategy=get_strategy(config.generation.strategy, config.generation.strategy_params),
        corr_strategy=get_strategy(config.correction.strategy, config.correction.strategy_params),
        grammar_context=(
            _load_grammar()
            if (config.generation.include_grammar or config.correction.include_grammar)
            else None
        ),
        gen_include_grammar=config.generation.include_grammar,
        corr_include_grammar=config.correction.include_grammar,
        num_candidates=config.pipeline.num_candidates,
        max_iterations=config.pipeline.max_iterations,
        stop_on_first_convergence=config.pipeline.stop_on_first_convergence,
        on_progress=on_progress,
    )

    candidates: list[CandidateResult] = []
    for i in range(ctx.num_candidates):
        candidate = _run_candidate(candidate_id=i, contract_text=contract_text, ctx=ctx)
        candidates.append(candidate)
        if ctx.stop_on_first_convergence and candidate.converged:
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
    ctx: _RunContext,
) -> CandidateResult:
    gen_context = PromptContext(
        contract_text=contract_text,
        grammar_context=ctx.grammar_context if ctx.gen_include_grammar else None,
    )
    gen_prompt = ctx.gen_strategy.build_generation_prompt(gen_context)
    code = _clean_response(ctx.gen_llm.generate(gen_prompt))

    errors = ctx.wrapper.validate(code)
    error_history = [IterationRecord(iteration=0, code=code, errors=errors)]
    if ctx.on_progress:
        ctx.on_progress(candidate_id, 0, errors, ctx.num_candidates, ctx.max_iterations)

    for iteration in range(1, ctx.max_iterations + 1):
        if not errors:
            break
        corr_context = PromptContext(
            current_code=code,
            errors=errors,
            grammar_context=ctx.grammar_context if ctx.corr_include_grammar else None,
            history=error_history,
        )
        corr_prompt = ctx.corr_strategy.build_correction_prompt(corr_context)
        code = _clean_response(ctx.corr_llm.generate(corr_prompt))
        errors = ctx.wrapper.validate(code)
        error_history.append(IterationRecord(iteration=iteration, code=code, errors=errors))
        if ctx.on_progress:
            ctx.on_progress(candidate_id, iteration, errors, ctx.num_candidates, ctx.max_iterations)

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
        grammar_file = resources.files(_GRAMMAR_PACKAGE).joinpath(_GRAMMAR_FILE)
        return grammar_file.read_text(encoding="utf-8")
    except Exception as e:
        raise RuntimeError(
            f"Failed to load Symboleo grammar resource: {e}. "
            f"Ensure {_GRAMMAR_FILE} is present in symboleo_llm_tool/resources/."
        ) from e
