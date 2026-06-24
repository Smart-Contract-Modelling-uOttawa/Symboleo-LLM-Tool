"""Experiment-suite orchestration.

Sits one level above ``pipeline.run`` and composes it: ``run_suite`` loops over
the suite's experiments, calling the single-run pipeline unchanged for each. It
is I/O-agnostic by design (no HTTP, SSE, or asyncio here) so the same function
can be driven by the API now and a CLI or test later — the same discipline that
keeps ``pipeline.run`` thin.
"""

from collections.abc import Callable
from datetime import datetime

from symboleo_llm_tool import pipeline
from symboleo_llm_tool.config.models import SuiteConfig
from symboleo_llm_tool.output.models import ExperimentResult, SuiteResult
from symboleo_llm_tool.pipeline.pipeline import ProgressCallback
from symboleo_llm_tool.symboleo.models import SymboleoIssue

# (experiment_index, candidate_id, iteration, errors, total_candidates, total_iterations)
# The pipeline's own ProgressCallback with experiment_index prepended, so the
# caller (the API adapter) can route each update to the right experiment without
# reaching into the suite config for totals.
SuiteProgressCallback = Callable[[int, int, int, list[SymboleoIssue], int, int], None]


def run_suite(
    suite: SuiteConfig,
    input_file: str = "",
    on_progress: SuiteProgressCallback | None = None,
) -> SuiteResult:
    """Run every experiment in the suite sequentially against the contract.

    Experiments run in order; v1 is deliberately sequential (concurrency is a
    later optimization that reuses this same callback contract). An exception in
    any experiment propagates and aborts the suite — per-experiment error
    isolation is a future improvement.
    """
    experiments: list[ExperimentResult] = []
    for index, experiment in enumerate(suite.experiments):
        cell_progress = _make_cell_callback(on_progress, index) if on_progress is not None else None
        result = pipeline.run(
            suite.contract_text,
            experiment.config,
            input_file=input_file,
            on_progress=cell_progress,
        )
        experiments.append(ExperimentResult(name=experiment.name, result=result))

    return SuiteResult(timestamp=datetime.now(), input_file=input_file, experiments=experiments)


def _make_cell_callback(
    on_progress: SuiteProgressCallback, experiment_index: int
) -> ProgressCallback:
    """Adapt a suite callback into the pipeline's per-run callback for one cell.

    Captures ``experiment_index`` and prepends it to each pipeline update, so the
    pipeline's own ``ProgressCallback`` signature stays untouched.
    """

    def forward(
        candidate_id: int,
        iteration: int,
        errors: list[SymboleoIssue],
        total_candidates: int,
        total_iterations: int,
    ) -> None:
        on_progress(
            experiment_index,
            candidate_id,
            iteration,
            errors,
            total_candidates,
            total_iterations,
        )

    return forward
