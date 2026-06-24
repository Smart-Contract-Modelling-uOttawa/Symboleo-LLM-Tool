from datetime import datetime

from pydantic import BaseModel

from symboleo_llm_tool.symboleo.models import SymboleoIssue


class IterationRecord(BaseModel):
    iteration: int
    code: str
    errors: list[SymboleoIssue]


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
