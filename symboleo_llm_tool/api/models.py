from enum import Enum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, Field, field_validator

from symboleo_llm_tool.output.models import PipelineResult, SuiteResult


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


def _require_nonempty_contract(v: str) -> str:
    if not v.strip():
        raise ValueError("contract_text must not be empty or whitespace-only")
    return v


# Reusable validated type: the non-empty rule travels with the field wherever a
# contract appears — a single request now, or list[ContractText] per suite later.
ContractText = Annotated[str, AfterValidator(_require_nonempty_contract)]


class RunSettings(BaseModel):
    """The per-run configuration shared by a single generation request and one
    experiment in a suite. Subclasses add the input that distinguishes them — a
    contract to generate from, or a name within a suite. Keeping these fields in
    one place lets ``build_pipeline_config`` accept either kind of request.
    """

    generation: StageRequest
    correction: StageRequest | None = None
    num_candidates: int | None = None
    max_iterations: int | None = None
    save_intermediates: bool | None = None
    stop_on_first_convergence: bool | None = None

    @property
    def effective_correction(self) -> StageRequest:
        return self.correction if self.correction is not None else self.generation


class GenerateRequest(RunSettings):
    contract_text: ContractText


class ExperimentRequest(RunSettings):
    name: str


class SuiteRequest(BaseModel):
    contract_text: ContractText
    experiments: list[ExperimentRequest]
    # Suite-wide concurrency cap; None → the SuiteConfig default. Bounds are
    # enforced by SuiteConfig (clamped to [1, 8]).
    max_concurrency: int | None = None

    @field_validator("experiments")
    @classmethod
    def _validate_experiments(cls, v: list[ExperimentRequest]) -> list[ExperimentRequest]:
        if not v:
            raise ValueError("a suite must contain at least one experiment")
        names = [e.name for e in v]
        if len(names) != len(set(names)):
            raise ValueError("experiment names must be unique within a suite")
        return v


class ProgressEvent(BaseModel):
    type: EventType = EventType.PROGRESS
    # None for single runs; set to the experiment index within a suite so the
    # client can route the update to the right experiment (demultiplexing).
    experiment_index: int | None = None
    candidate_id: int
    iteration: int
    error_count: int


class CompleteEvent(BaseModel):
    type: EventType = EventType.COMPLETE
    result: PipelineResult


class SuiteCompleteEvent(BaseModel):
    type: EventType = EventType.COMPLETE
    result: SuiteResult


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
