"""Derivation of the computed metrics on the result models.

The ``@computed_field``s on the result models declare the fields and delegate
here. Keeping the derivation in its own module leaves ``models.py`` as
data-shape declarations and gives the logic a named, reusable home — any
consumer (CLI, report tooling) can call these directly.

Model types are imported only under ``TYPE_CHECKING``; the function bodies use
plain attribute access, so there is no runtime import cycle with ``models.py``
(which imports this module at load time).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from symboleo_llm_tool.output.models import (
        CandidateResult,
        PipelineResult,
        SuiteResult,
        TokenUsage,
    )


def _sum_optional_costs(costs: Iterable[float | None]) -> float | None:
    """Sum costs, treating ``None`` as "not reported".

    Stays ``None`` until at least one cost contributes, so an all-``None`` rollup
    reads as *unknown* (rendered as a dash) rather than a misleading ``$0.00``.
    """
    total: float | None = None
    for cost in costs:
        if cost is not None:
            total = cost if total is None else total + cost
    return total


def _candidate_usages(candidate: CandidateResult) -> list[TokenUsage]:
    """The non-``None`` usage records in a candidate's iteration history."""
    usages: list[TokenUsage] = []
    for record in candidate.error_history:
        if record.usage is not None:
            usages.append(record.usage)
    return usages


def candidate_total_tokens(candidate: CandidateResult) -> int:
    return sum(u.total_tokens for u in _candidate_usages(candidate))


def candidate_total_cost_usd(candidate: CandidateResult) -> float | None:
    return _sum_optional_costs(u.cost_usd for u in _candidate_usages(candidate))


def candidate_final_error_count(candidate: CandidateResult) -> int:
    """ERROR-severity issues in the candidate's final iteration (0 for empty history)."""
    if not candidate.error_history:
        return 0
    return sum(1 for issue in candidate.error_history[-1].errors if issue.is_error)


def candidate_final_warning_count(candidate: CandidateResult) -> int:
    """Non-ERROR issues in the candidate's final iteration (0 for empty history).

    Counts non-ERROR rather than ``== "WARNING"`` so the error and warning
    counts partition the final record's issues even if the validator emits
    another severity (INFO).
    """
    if not candidate.error_history:
        return 0
    return sum(1 for issue in candidate.error_history[-1].errors if not issue.is_error)


def pipeline_total_tokens(result: PipelineResult) -> int:
    return sum(c.total_tokens for c in result.candidates)


def pipeline_total_cost_usd(result: PipelineResult) -> float | None:
    return _sum_optional_costs(c.total_cost_usd for c in result.candidates)


def failed_candidate_count(result: PipelineResult) -> int:
    """Candidates whose loop was cut short by a failed external call."""
    return sum(1 for candidate in result.candidates if candidate.failure is not None)


def iterations_to_convergence(result: PipelineResult) -> int | None:
    """Iterations used by the first converged candidate, or ``None`` if none converged."""
    for candidate in result.candidates:
        if candidate.converged:
            return candidate.iterations_used
    return None


def suite_total_tokens(result: SuiteResult) -> int:
    return sum(e.result.total_tokens for e in result.experiments)


def suite_total_cost_usd(result: SuiteResult) -> float | None:
    return _sum_optional_costs(e.result.total_cost_usd for e in result.experiments)
