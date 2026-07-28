from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

from symboleo_llm_tool.concurrency import CancellationToken, RunCoordinator
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
from symboleo_llm_tool.prompts.grammar import load_grammar
from symboleo_llm_tool.prompts.strategies import get_strategy
from symboleo_llm_tool.symboleo.models import SymboleoIssue
from symboleo_llm_tool.symboleo.wrapper import SymboleoWrapper

# Args: (candidate_id, iteration, errors, total_candidates, total_iterations).
# `errors` carries ALL validator issues — blocking errors and warnings alike —
# so callers can surface both; the convergence gate filters separately.
ProgressCallback = Callable[[int, int, list[SymboleoIssue], int, int], None]


def _blocking(issues: list[SymboleoIssue]) -> list[SymboleoIssue]:
    """The issues that gate convergence and feed the correction prompt.

    WARNINGs are surfaced but never block: an ERROR-free contract that warns is
    converged, and feeding warnings to the LLM measurably invites the
    over-editing that loses near-converged runs (see CLAUDE.md, "Convergence
    Semantics", for the census evidence).
    """
    return [i for i in issues if i.is_error]


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
    # Resolved by run(): the coordinator's per-experiment token on the concurrent
    # path, a caller-supplied token on the sequential path (e.g. the API on
    # disconnect or explicit cancel), or an inert default when neither is given.
    cancel: CancellationToken


def run(
    contract_text: str,
    config: PipelineConfig,
    input_file: str = "",
    on_progress: ProgressCallback | None = None,
    coordinator: RunCoordinator | None = None,
    cancel: CancellationToken | None = None,
) -> PipelineResult:
    """Generate and correction-loop candidates for one contract.

    ``coordinator`` is supplied only by the suite runner for concurrent execution;
    its absence selects the unchanged sequential path (CLI, single-run API).
    ``cancel`` lets a caller abort that sequential path cooperatively (e.g. the
    API on client disconnect); a ``coordinator``'s own token takes precedence.
    """
    tracing = config.observability.langsmith.enabled
    if coordinator is not None:
        cancel_token = coordinator.cancel
    elif cancel is not None:
        cancel_token = cancel
    else:
        cancel_token = CancellationToken()
    ctx = _RunContext(
        wrapper=SymboleoWrapper(config.symboleo.jar_path, config.symboleo.java_executable),
        gen_llm=create_adapter(config.generation.llm, tracing_enabled=tracing),
        corr_llm=create_adapter(config.correction.llm, tracing_enabled=tracing),
        gen_strategy=get_strategy(config.generation.strategy, config.generation.strategy_params),
        corr_strategy=get_strategy(config.correction.strategy, config.correction.strategy_params),
        grammar_context=(
            load_grammar()
            if (config.generation.include_grammar or config.correction.include_grammar)
            else None
        ),
        gen_include_grammar=config.generation.include_grammar,
        corr_include_grammar=config.correction.include_grammar,
        num_candidates=config.pipeline.num_candidates,
        max_iterations=config.pipeline.max_iterations,
        stop_on_first_convergence=config.pipeline.stop_on_first_convergence,
        on_progress=on_progress,
        cancel=cancel_token,
    )

    if coordinator is None:
        candidates = _run_candidates_sequential(contract_text, ctx)
    else:
        candidates = _run_candidates_concurrent(contract_text, ctx, coordinator.candidate_pool)

    return PipelineResult(
        success=any(c.converged for c in candidates),
        timestamp=datetime.now(),
        input_file=input_file,
        candidates=candidates,
    )


def _run_candidates_sequential(contract_text: str, ctx: _RunContext) -> list[CandidateResult]:
    candidates: list[CandidateResult] = []
    for i in range(ctx.num_candidates):
        candidate = _run_candidate(candidate_id=i, contract_text=contract_text, ctx=ctx)
        if candidate is None:  # cancelled before this candidate started — skip it
            continue
        candidates.append(candidate)
        if ctx.stop_on_first_convergence and candidate.converged:
            break
    return candidates


def _run_candidates_concurrent(
    contract_text: str, ctx: _RunContext, pool: ThreadPoolExecutor
) -> list[CandidateResult]:
    """Run candidates on the shared pool; cancel siblings on first convergence.

    All candidates are submitted up front; the pool bounds how many run at once.
    On ``stop_on_first_convergence`` we cancel this run's token — not-yet-started
    candidates short-circuit at their entry checkpoint, in-flight ones at their
    next iteration. Results are reordered by ``candidate_id`` (futures complete
    out of order).
    """
    futures = {
        pool.submit(_run_candidate, i, contract_text, ctx): i for i in range(ctx.num_candidates)
    }
    candidates: list[CandidateResult] = []
    for future in as_completed(futures):
        candidate = future.result()
        if candidate is None:  # skipped — cancelled before it started
            continue
        candidates.append(candidate)
        if ctx.stop_on_first_convergence and candidate.converged:
            ctx.cancel.cancel()
    candidates.sort(key=lambda c: c.candidate_id)
    return candidates


def _run_candidate(
    candidate_id: int,
    contract_text: str,
    ctx: _RunContext,
) -> CandidateResult | None:
    """Run one candidate, or return ``None`` if cancelled before it started.

    A ``None`` happens when the run was cancelled before this candidate ran — a
    sibling converged on the concurrent path, or the caller's token was tripped
    (Stop, disconnect) — and is excluded from results on both paths.
    """
    if ctx.cancel.cancelled:
        return None

    gen_context = PromptContext(
        contract_text=contract_text,
        grammar_context=ctx.grammar_context if ctx.gen_include_grammar else None,
    )
    gen_prompt = ctx.gen_strategy.build_generation_prompt(gen_context)
    gen_result = ctx.gen_llm.generate(gen_prompt)
    code = _clean_response(gen_result.generated_text)

    errors = ctx.wrapper.validate(code)
    blocking = _blocking(errors)
    error_history = [IterationRecord(iteration=0, code=code, errors=errors, usage=gen_result.usage)]
    if ctx.on_progress:
        ctx.on_progress(candidate_id, 0, errors, ctx.num_candidates, ctx.max_iterations)

    for iteration in range(1, ctx.max_iterations + 1):
        if not blocking:
            break
        if ctx.cancel.cancelled:  # cooperative checkpoint between iterations
            break
        corr_context = PromptContext(
            current_code=code,
            errors=blocking,
            grammar_context=ctx.grammar_context if ctx.corr_include_grammar else None,
            history=error_history,
        )
        corr_prompt = ctx.corr_strategy.build_correction_prompt(corr_context)
        corr_result = ctx.corr_llm.generate(corr_prompt)
        code = _clean_response(corr_result.generated_text)
        errors = ctx.wrapper.validate(code)
        blocking = _blocking(errors)
        error_history.append(
            IterationRecord(iteration=iteration, code=code, errors=errors, usage=corr_result.usage)
        )
        if ctx.on_progress:
            ctx.on_progress(candidate_id, iteration, errors, ctx.num_candidates, ctx.max_iterations)

    return CandidateResult(
        candidate_id=candidate_id,
        final_code=code,
        converged=not blocking,
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
