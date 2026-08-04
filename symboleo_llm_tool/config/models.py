from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

# A config path that reloads on an OS other than the one that wrote it.
# ``str(Path)`` uses the host separator, so a Windows-written run record carries
# ``lib\symboleo-cli.jar``, which POSIX reads as one opaque filename. ``json``
# mode only: the defect is in the persisted artifact, so in-memory dumps keep
# returning a real ``Path``. Relative paths only — an absolute ``C:\...`` becomes
# ``C:/...``, which POSIX takes as a *relative* path with a literal ``C:``
# segment, and no serializer can fix that.
PortablePath = Annotated[Path, PlainSerializer(Path.as_posix, return_type=str, when_used="json")]


class _StrictModel(BaseModel):
    """Base for every config model: config input is closed.

    An unknown key is a typo or a stale field, and either way the value the
    author intended is not the value the run uses. Ignoring it (Pydantic's
    default) makes that undetectable after the fact: the run succeeds and
    ``report.json`` records the config as *loaded*, so the durable artifact
    shows the default rather than the misspelling that produced it.

    Stated once here rather than per model so a new config model cannot opt out
    by omission; ``extra="forbid"`` is inherited by subclasses.

    Range checks on subclasses are declarative ``Field(ge=/le=/min_length=)``
    so they reach the generated JSON Schemas — a ``@field_validator`` body is
    invisible to ``model_json_schema()``. *Behaviour* (e.g. ``SuiteConfig``'s
    clamp) stays a validator and deliberately gets no schema bound. Full
    convention: CLAUDE.md, "Config Schema".
    """

    model_config = ConfigDict(extra="forbid")


class LLMConfig(_StrictModel):
    # ``provider``/``model`` are open strings on purpose: the CLI passes them
    # straight to LiteLLM, so any model a provider serves works without a repo
    # change. ``configs/ui_config.yaml`` is only the web form's curated menu.
    provider: str
    model: str
    # Optional so it is only sent when explicitly set. Reasoning models (OpenAI
    # o-series/GPT-5, Anthropic Opus 4.x/Fable 5) reject sampling params; omitting
    # temperature for those models avoids a 400 without relying on LiteLLM's
    # (imperfect) param-support table to drop it. See CLAUDE.md Known Issues.
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1)

    @property
    def litellm_model(self) -> str:
        """Provider-qualified id LiteLLM expects (e.g. ``openai/gpt-4o-mini``).

        Single source of truth so the call and any capability lookup reference
        the same model.
        """
        return f"{self.provider}/{self.model}"


class StageConfig(_StrictModel):
    llm: LLMConfig
    strategy: str
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    include_grammar: bool = True


class RunConfig(_StrictModel):
    num_candidates: int = Field(default=1, ge=1)
    # 0 is valid: generation only, no correction loop.
    max_iterations: int = Field(default=3, ge=0)
    stop_on_first_convergence: bool = False


class SymboleoConfig(_StrictModel):
    jar_path: PortablePath = Path("./lib/symboleo-cli.jar")
    java_executable: str = "java"


class OutputConfig(_StrictModel):
    directory: PortablePath = Path("./output")
    save_intermediates: bool = False


class LangSmithConfig(_StrictModel):
    enabled: bool = False
    project: str = "symboleo-research"


class ObservabilityConfig(_StrictModel):
    langsmith: LangSmithConfig = Field(default_factory=LangSmithConfig)


class PipelineConfig(_StrictModel):
    pipeline: RunConfig = Field(default_factory=RunConfig)
    generation: StageConfig
    correction: StageConfig
    symboleo: SymboleoConfig = Field(default_factory=SymboleoConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)


class Experiment(_StrictModel):
    """One named configuration in an experiment suite.

    The name labels the experiment in the comparison view; the config is a
    complete, independent ``PipelineConfig`` (reused wholesale — a suite does
    not constrain what a single run can express).
    """

    name: str
    config: PipelineConfig


class SuiteConfig(_StrictModel):
    """A set of experiments run against one contract for comparison.

    One contract is the deliberate v1 default: comparison is only
    apples-to-apples with the contract held fixed as the control variable.
    """

    contract_text: str
    # Non-emptiness is declarative so it reaches the schema as minItems;
    # name-uniqueness is genuinely behavioural and stays in the validator.
    experiments: list[Experiment] = Field(min_length=1)
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
        names = [e.name for e in v]
        if len(names) != len(set(names)):
            raise ValueError("experiment names must be unique within a suite")
        return v

    @property
    def output_directory(self) -> Path:
        """Output root for the whole suite — borrowed from the first experiment (a
        suite file has no output section of its own; experiments share one root in
        practice). Encapsulated here so the writer is handed a directory rather than
        reaching through the experiment list to infer one.
        """
        return self.experiments[0].config.output.directory
