from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from symboleo_llm_tool.output.models import PipelineResult


class EventType(str, Enum):
    PROGRESS = "progress"
    COMPLETE = "complete"
    ERROR = "error"


class StageRequest(BaseModel):
    model: str
    strategy: str
    temperature: float | None = None
    include_grammar: bool | None = None
    strategy_params: dict[str, Any] = Field(default_factory=dict)


class GenerateRequest(BaseModel):
    contract_text: str
    generation: StageRequest
    correction: StageRequest | None = None
    num_candidates: int | None = None
    max_iterations: int | None = None
    save_intermediates: bool | None = None
    stop_on_first_convergence: bool | None = None

    @property
    def effective_correction(self) -> StageRequest:
        return self.correction if self.correction is not None else self.generation

    @field_validator("contract_text")
    @classmethod
    def _validate_contract_text(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("contract_text must not be empty or whitespace-only")
        return v


class ProgressEvent(BaseModel):
    type: EventType = EventType.PROGRESS
    candidate_id: int
    iteration: int
    error_count: int


class CompleteEvent(BaseModel):
    type: EventType = EventType.COMPLETE
    result: PipelineResult


class ErrorEvent(BaseModel):
    type: EventType = EventType.ERROR
    message: str


class RunCreatedResponse(BaseModel):
    run_id: str
    warnings: list[str] = Field(default_factory=list)


class OptionsResponse(BaseModel):
    strategies: list[str]
    models: dict[str, list[str]]
    parameters: dict[str, Any]
    examples: list[str]
