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


class Experiment(BaseModel):
    """One named configuration in an experiment suite.

    The name labels the experiment in the comparison view; the config is a
    complete, independent ``PipelineConfig`` (reused wholesale — a suite does
    not constrain what a single run can express).
    """

    name: str
    config: PipelineConfig


class SuiteConfig(BaseModel):
    """A set of experiments run against one contract for comparison.

    One contract is the deliberate v1 default: comparison is only
    apples-to-apples with the contract held fixed as the control variable.
    """

    contract_text: str
    experiments: list[Experiment]
    # Max candidates running concurrently across the whole suite (one global
    # throttle for both axes; see docs/suite-concurrency-design.md). 1 is the
    # sequential floor — the unchanged single-threaded path.
    max_concurrency: int = 2

    @field_validator("max_concurrency")
    @classmethod
    def _clamp_max_concurrency(cls, v: int) -> int:
        # Clamp rather than reject: a config typo shouldn't break a run, and it
        # must never oversubscribe the machine (each unit may spawn a JVM).
        return max(1, min(v, 8))

    @field_validator("experiments")
    @classmethod
    def _validate_experiments(cls, v: list[Experiment]) -> list[Experiment]:
        if not v:
            raise ValueError("a suite must contain at least one experiment")
        names = [e.name for e in v]
        if len(names) != len(set(names)):
            raise ValueError("experiment names must be unique within a suite")
        return v
