from typing import Any

from pydantic import BaseModel, Field

from symboleo_llm_tool.output.models import PipelineResult


class StageRequest(BaseModel):
    model: str
    strategy: str
    include_grammar: bool | None = None
    strategy_params: dict[str, Any] = Field(default_factory=dict)


class GenerateRequest(BaseModel):
    contract_text: str
    generation: StageRequest
    correction: StageRequest | None = None
    num_candidates: int | None = None
    max_iterations: int | None = None
    temperature: float | None = None
    save_intermediates: bool | None = None
    stop_on_first_convergence: bool | None = None


class ProgressEvent(BaseModel):
    type: str = "progress"
    candidate_id: int
    iteration: int
    error_count: int


class CompleteEvent(BaseModel):
    type: str = "complete"
    result: PipelineResult


class ErrorEvent(BaseModel):
    type: str = "error"
    message: str


class RunCreatedResponse(BaseModel):
    run_id: str


class OptionsResponse(BaseModel):
    strategies: list[str]
    models: dict[str, list[str]]
    parameters: dict[str, Any]
    examples: list[str]
