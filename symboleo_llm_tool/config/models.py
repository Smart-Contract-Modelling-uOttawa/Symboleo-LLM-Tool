from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LLMConfig(BaseModel):
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 2.0:
            raise ValueError(f"temperature must be between 0.0 and 2.0, got {v}")
        return v

    @field_validator("max_tokens")
    @classmethod
    def _validate_max_tokens(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"max_tokens must be at least 1, got {v}")
        return v


class StageConfig(BaseModel):
    llm: LLMConfig
    strategy: str
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    include_grammar: bool = True


class RunConfig(BaseModel):
    num_candidates: int = 1
    max_iterations: int = 3
    stop_on_first_convergence: bool = False

    @field_validator("num_candidates")
    @classmethod
    def _validate_num_candidates(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"num_candidates must be at least 1, got {v}")
        return v

    @field_validator("max_iterations")
    @classmethod
    def _validate_max_iterations(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"max_iterations must be >= 0, got {v}")
        return v


class SymboleoConfig(BaseModel):
    jar_path: Path = Path("./lib/symboleo-cli.jar")
    java_executable: str = "java"


class OutputConfig(BaseModel):
    directory: Path = Path("./output")
    save_intermediates: bool = False


class LangSmithConfig(BaseModel):
    enabled: bool = False
    project: str = "symboleo-research"


class ObservabilityConfig(BaseModel):
    langsmith: LangSmithConfig = Field(default_factory=LangSmithConfig)


class PipelineConfig(BaseModel):
    pipeline: RunConfig = Field(default_factory=RunConfig)
    generation: StageConfig
    correction: StageConfig
    symboleo: SymboleoConfig = Field(default_factory=SymboleoConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
