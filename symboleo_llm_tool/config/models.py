from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LLMConfig(BaseModel):
    provider: str
    model: str
    # Optional so it is only sent when explicitly set. Reasoning models (OpenAI
    # o-series/GPT-5, Anthropic Opus 4.x/Fable 5) reject sampling params; omitting
    # temperature for those models avoids a 400 without relying on LiteLLM's
    # (imperfect) param-support table to drop it. See CLAUDE.md Known Issues.
    temperature: float | None = None
    max_tokens: int = 4096

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, v: float | None) -> float | None:
        if v is not None and not 0.0 <= v <= 2.0:
            raise ValueError(f"temperature must be between 0.0 and 2.0, got {v}")
        return v

    @field_validator("max_tokens")
    @classmethod
    def _validate_max_tokens(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"max_tokens must be at least 1, got {v}")
        return v

    @property
    def litellm_model(self) -> str:
        """Provider-qualified id LiteLLM expects (e.g. ``openai/gpt-4o-mini``).

        Single source of truth so the call and any capability lookup reference
        the same model.
        """
        return f"{self.provider}/{self.model}"


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
