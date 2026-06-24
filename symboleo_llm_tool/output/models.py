from datetime import datetime

from pydantic import BaseModel, computed_field

from symboleo_llm_tool.symboleo.models import SymboleoIssue


class TokenUsage(BaseModel):
    """Token counts and cost for a single LLM call.

    Attached to each ``IterationRecord`` (one call per iteration). Per-candidate
    and per-experiment totals are derived from these by summing, never stored —
    consistent with the "metrics are derived, not stored" rule. ``cost_usd`` is
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
    iteration: int
    code: str
    errors: list[SymboleoIssue]
    usage: TokenUsage | None = None


class CandidateResult(BaseModel):
    candidate_id: int
    final_code: str
    converged: bool
    iterations_used: int
    error_history: list[IterationRecord]


class PipelineResult(BaseModel):
    success: bool
    timestamp: datetime
    input_file: str
    candidates: list[CandidateResult]


class ExperimentResult(BaseModel):
    """The outcome of one named experiment in a suite.

    Holds the full per-run ``PipelineResult`` unchanged; comparison metrics are
    derived from it at write/display time rather than baked into the model, so
    adding a metric never requires re-running a suite.
    """

    name: str
    result: PipelineResult


class SuiteResult(BaseModel):
    timestamp: datetime
    input_file: str
    experiments: list[ExperimentResult]
