from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096


class StageConfig(BaseModel):
    llm: LLMConfig
    strategy: str
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    include_grammar: bool = True


class RunConfig(BaseModel):
    num_candidates: int = 1
    max_iterations: int = 3
    stop_on_first_convergence: bool = False


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
