from datetime import datetime

from pydantic import BaseModel, computed_field

from symboleo_llm_tool.output import metrics
from symboleo_llm_tool.symboleo.models import SymboleoIssue


class TokenUsage(BaseModel):
    """Token counts and cost for a single LLM call.

    Attached to each ``IterationRecord`` (one call per iteration). ``cost_usd`` is
    best-effort: ``None`` when LiteLLM has no pricing for the model.
    """

    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None = None

    @computed_field  # type: ignore[prop-decorator]  # no pydantic mypy plugin configured
    @property
    def total_tokens(self) -> int:
        """Always prompt + completion — derived rather than trusting the reported total."""
        return self.prompt_tokens + self.completion_tokens


class IterationRecord(BaseModel):
    """One generation or correction pass: the code it produced and its issues.

    ``rejected_response`` holds the raw text of a correction that carried no
    contract and was therefore not adopted. On such a record ``code`` and
    ``errors`` repeat the previous record's, while ``usage`` is the refused
    call's own.
    """

    iteration: int
    code: str
    errors: list[SymboleoIssue]
    usage: TokenUsage | None = None
    rejected_response: str | None = None


class CandidateResult(BaseModel):
    candidate_id: int
    final_code: str
    converged: bool
    iterations_used: int
    error_history: list[IterationRecord]
    # Set when a transient external call (LLM or validator) failed and cut the
    # loop short, carrying that call's message. ``None`` means the loop was not
    # cut short — converged, out of iterations, or cancelled — and the
    # distinction must stay recoverable from the artifact.
    failure: str | None = None

    @computed_field  # type: ignore[prop-decorator]  # no pydantic mypy plugin configured
    @property
    def total_tokens(self) -> int:
        return metrics.candidate_total_tokens(self)

    @computed_field  # type: ignore[prop-decorator]  # no pydantic mypy plugin configured
    @property
    def total_cost_usd(self) -> float | None:
        return metrics.candidate_total_cost_usd(self)

    @computed_field  # type: ignore[prop-decorator]  # no pydantic mypy plugin configured
    @property
    def final_error_count(self) -> int:
        """Blocking errors remaining in the final output — the magnitude behind
        ``converged: false`` (0 also for a run cancelled before any validation).
        """
        return metrics.candidate_final_error_count(self)

    @computed_field  # type: ignore[prop-decorator]  # no pydantic mypy plugin configured
    @property
    def final_warning_count(self) -> int:
        """Warnings lingering in the final output — surfaced, never blocking."""
        return metrics.candidate_final_warning_count(self)


class PipelineResult(BaseModel):
    success: bool
    timestamp: datetime
    input_file: str
    candidates: list[CandidateResult]

    @computed_field  # type: ignore[prop-decorator]  # no pydantic mypy plugin configured
    @property
    def total_tokens(self) -> int:
        return metrics.pipeline_total_tokens(self)

    @computed_field  # type: ignore[prop-decorator]  # no pydantic mypy plugin configured
    @property
    def total_cost_usd(self) -> float | None:
        return metrics.pipeline_total_cost_usd(self)

    @computed_field  # type: ignore[prop-decorator]  # no pydantic mypy plugin configured
    @property
    def iterations_to_convergence(self) -> int | None:
        return metrics.iterations_to_convergence(self)

    @computed_field  # type: ignore[prop-decorator]  # no pydantic mypy plugin configured
    @property
    def failed_candidate_count(self) -> int:
        """Candidates cut short by a failed external call."""
        return metrics.failed_candidate_count(self)


class ExperimentResult(BaseModel):
    """The outcome of one named experiment in a suite.

    Holds the full per-run ``PipelineResult`` unchanged; comparison rollups are
    ``@computed_field``s on the result models that delegate to ``output/metrics.py``,
    derived from the stored atomic facts rather than baked in, so adding a metric
    never requires re-running a suite.
    """

    name: str
    result: PipelineResult


class SuiteResult(BaseModel):
    timestamp: datetime
    input_file: str
    experiments: list[ExperimentResult]

    @computed_field  # type: ignore[prop-decorator]  # no pydantic mypy plugin configured
    @property
    def total_tokens(self) -> int:
        return metrics.suite_total_tokens(self)

    @computed_field  # type: ignore[prop-decorator]  # no pydantic mypy plugin configured
    @property
    def total_cost_usd(self) -> float | None:
        return metrics.suite_total_cost_usd(self)
