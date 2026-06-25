"""Experiment-suite orchestration.

Sits one level above ``pipeline.run`` and composes it: ``run_suite`` loops over
the suite's experiments, calling the single-run pipeline (unchanged) for each. It
is I/O-agnostic by design (no HTTP, SSE, or asyncio here) so the same function can
be driven by the API now and a CLI or test later — the same discipline that keeps
``pipeline.run`` thin.

Concurrency (``suite.max_concurrency > 1``) runs candidates from all experiments
on one bounded pool, with a separate light pool driving the experiments — see
``docs/suite-concurrency-design.md`` for why two pools (deadlock avoidance) and
how the single global cap bounds resource use.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from symboleo_llm_tool import pipeline
from symboleo_llm_tool.concurrency import CancellationToken, RunCoordinator
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
    cancel: CancellationToken | None = None,
) -> SuiteResult:
    """Run every experiment against the contract and return them for comparison.

    ``suite.max_concurrency == 1`` is the unchanged sequential path. Higher values
    run candidates across all experiments on one bounded pool. ``cancel`` is an
    optional request-scoped token the caller may trip externally (phase 2: a
    dropped connection) — it is the parent of each experiment's own token, so
    cancelling it short-circuits the whole suite.
    """
    if suite.max_concurrency == 1:
        experiments = _run_sequential(suite, input_file, on_progress)
    else:
        experiments = _run_concurrent(suite, input_file, on_progress, cancel or CancellationToken())
    return SuiteResult(timestamp=datetime.now(), input_file=input_file, experiments=experiments)


def _run_sequential(
    suite: SuiteConfig, input_file: str, on_progress: SuiteProgressCallback | None
) -> list[ExperimentResult]:
    experiments: list[ExperimentResult] = []
    for index, experiment in enumerate(suite.experiments):
        result = pipeline.run(
            suite.contract_text,
            experiment.config,
            input_file=input_file,
            on_progress=_cell_callback(on_progress, index),
        )
        experiments.append(ExperimentResult(name=experiment.name, result=result))
    return experiments


def _run_concurrent(
    suite: SuiteConfig,
    input_file: str,
    on_progress: SuiteProgressCallback | None,
    request_cancel: CancellationToken,
) -> list[ExperimentResult]:
    experiments = suite.experiments
    slots: list[ExperimentResult | None] = [None] * len(experiments)
    # Two pools: candidate_pool (bounded — the throttle) runs the heavy work;
    # experiment_pool (light) drives each pipeline.run. Distinct pools so a driver
    # blocking on its candidates can never starve the candidates it waits on. Only
    # max_concurrency candidates run at once, so that many drivers are enough to
    # keep the candidate pool saturated — sizing the driver pool to K (not E) needs
    # no separate cap and bounds total threads to ~2K.
    driver_count = min(len(experiments), suite.max_concurrency)
    with (
        ThreadPoolExecutor(max_workers=suite.max_concurrency) as candidate_pool,
        ThreadPoolExecutor(max_workers=driver_count) as experiment_pool,
    ):
        futures = {
            experiment_pool.submit(
                pipeline.run,
                suite.contract_text,
                experiment.config,
                input_file=input_file,
                on_progress=_cell_callback(on_progress, index),
                coordinator=RunCoordinator(candidate_pool, request_cancel.child()),
            ): index
            for index, experiment in enumerate(experiments)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                result = future.result()
            except Exception:
                request_cancel.cancel()  # fail-fast: short-circuit the siblings
                raise
            slots[index] = ExperimentResult(name=experiments[index].name, result=result)
    return [e for e in slots if e is not None]


def _cell_callback(
    on_progress: SuiteProgressCallback | None, experiment_index: int
) -> ProgressCallback | None:
    """Adapt the suite callback into the pipeline's per-run callback for one cell.

    Captures ``experiment_index`` and prepends it to each pipeline update so the
    pipeline's own ``ProgressCallback`` signature stays untouched. Returns ``None``
    when there is no suite callback, so callers don't repeat the guard.
    """
    if on_progress is None:
        return None

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
