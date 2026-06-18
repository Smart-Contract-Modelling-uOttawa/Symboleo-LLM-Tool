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
