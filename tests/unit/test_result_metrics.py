"""Computed-field rollups on the result models (token/cost totals + iterations).

These are derived, never stored: ``@computed_field`` so they serialize into
report.json, the API, and the generated schema from a single definition.
"""

from datetime import datetime

import pytest

from symboleo_llm_tool.output.models import (
    CandidateResult,
    ExperimentResult,
    IterationRecord,
    PipelineResult,
    SuiteResult,
    TokenUsage,
)
from tests.helpers import make_usage


def _record(usage: TokenUsage | None) -> IterationRecord:
    return IterationRecord(iteration=0, code="", errors=[], usage=usage)


def _candidate(
    usages: list[TokenUsage | None],
    *,
    converged: bool = True,
    iterations_used: int = 0,
) -> CandidateResult:
    return CandidateResult(
        candidate_id=0,
        final_code="",
        converged=converged,
        iterations_used=iterations_used,
        error_history=[_record(u) for u in usages],
    )


def _pipeline(candidates: list[CandidateResult], *, success: bool = True) -> PipelineResult:
    return PipelineResult(
        success=success,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        input_file="",
        candidates=candidates,
    )


class TestCandidateRollups:
    def test_total_tokens_sums_iteration_usage(self) -> None:
        candidate = _candidate(
            [
                make_usage(prompt_tokens=600, completion_tokens=100),
                make_usage(prompt_tokens=700, completion_tokens=100),
            ]
        )
        assert candidate.total_tokens == 1500

    def test_total_cost_sums_reported_costs(self) -> None:
        candidate = _candidate([make_usage(cost_usd=0.001), make_usage(cost_usd=0.002)])
        assert candidate.total_cost_usd == pytest.approx(0.003)

    def test_total_cost_is_none_when_no_cost_reported(self) -> None:
        # Distinct from $0.00 — an all-None rollup means "unknown", shown as a dash.
        candidate = _candidate([make_usage(cost_usd=None), make_usage(cost_usd=None)])
        assert candidate.total_cost_usd is None

    def test_total_cost_sums_only_reported_when_some_are_none(self) -> None:
        candidate = _candidate([make_usage(cost_usd=None), make_usage(cost_usd=0.002)])
        assert candidate.total_cost_usd == pytest.approx(0.002)

    def test_missing_usage_record_is_skipped(self) -> None:
        candidate = _candidate(
            [None, make_usage(prompt_tokens=500, completion_tokens=0, cost_usd=0.001)]
        )
        assert candidate.total_tokens == 500
        assert candidate.total_cost_usd == pytest.approx(0.001)


class TestPipelineRollups:
    def test_totals_sum_across_candidates(self) -> None:
        pipeline = _pipeline(
            [
                _candidate([make_usage(prompt_tokens=700, completion_tokens=0, cost_usd=0.001)]),
                _candidate([make_usage(prompt_tokens=300, completion_tokens=0, cost_usd=0.0005)]),
            ]
        )
        assert pipeline.total_tokens == 1000
        assert pipeline.total_cost_usd == pytest.approx(0.0015)

    def test_iterations_to_convergence_is_first_converged_candidate(self) -> None:
        # Every number here is distinct so the oracle picks out one implementation:
        # 5 is the *first converged* candidate's iterations_used — not its index
        # (1), the converged count (2), the non-converged count (1), the last
        # converger's count (2), the max (7), or the sum (14).
        pipeline = _pipeline(
            [
                _candidate([], converged=False, iterations_used=7),
                _candidate([], converged=True, iterations_used=5),
                _candidate([], converged=True, iterations_used=2),
            ]
        )
        assert pipeline.iterations_to_convergence == 5

    def test_iterations_to_convergence_is_none_when_none_converged(self) -> None:
        pipeline = _pipeline([_candidate([], converged=False, iterations_used=3)], success=False)
        assert pipeline.iterations_to_convergence is None


def test_suite_totals_sum_across_experiments() -> None:
    converged = _pipeline(
        [_candidate([make_usage(prompt_tokens=700, completion_tokens=0, cost_usd=0.001)])]
    )
    no_cost = _pipeline(
        [_candidate([make_usage(prompt_tokens=300, completion_tokens=0, cost_usd=None)])]
    )
    suite = SuiteResult(
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        input_file="",
        experiments=[
            ExperimentResult(name="a", result=converged),
            ExperimentResult(name="b", result=no_cost),
        ],
    )
    assert suite.total_tokens == 1000
    assert suite.total_cost_usd == pytest.approx(0.001)  # b's None cost is skipped


def test_computed_rollups_serialize_into_the_dump() -> None:
    pipeline = _pipeline(
        [
            _candidate(
                [make_usage(prompt_tokens=700, completion_tokens=0, cost_usd=0.001)],
                iterations_used=3,  # ≠ the candidate's index, so the dumped value is unambiguous
            )
        ]
    )
    dumped = pipeline.model_dump()
    assert dumped["total_tokens"] == 700
    assert dumped["total_cost_usd"] == pytest.approx(0.001)
    assert dumped["iterations_to_convergence"] == 3
    assert dumped["candidates"][0]["total_tokens"] == 700
