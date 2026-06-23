from unittest.mock import patch

from symboleo_llm_tool.config.models import LLMConfig, PipelineConfig, StageConfig
from symboleo_llm_tool.llm.compatibility import (
    pipeline_param_warnings,
    reasoning_param_warnings,
)

_TARGET = "symboleo_llm_tool.llm.compatibility.litellm.supports_reasoning"


def _cfg(temperature: float | None) -> LLMConfig:
    return LLMConfig(provider="openai", model="gpt-5", temperature=temperature)


def _pipeline(temperature: float | None) -> PipelineConfig:
    stage = StageConfig(llm=_cfg(temperature), strategy="zero_shot")
    return PipelineConfig(generation=stage, correction=stage)


def test_warns_when_temperature_set_on_reasoning_model() -> None:
    with patch(_TARGET, return_value=True):
        warnings = reasoning_param_warnings(_cfg(temperature=0.2))
    assert len(warnings) == 1
    assert "temperature" in warnings[0]
    assert "gpt-5" in warnings[0]


def test_no_warning_when_temperature_unset_on_reasoning_model() -> None:
    with patch(_TARGET, return_value=True):
        warnings = reasoning_param_warnings(_cfg(temperature=None))
    assert warnings == []


def test_no_warning_for_non_reasoning_model() -> None:
    with patch(_TARGET, return_value=False):
        warnings = reasoning_param_warnings(_cfg(temperature=0.2))
    assert warnings == []


def test_no_warning_when_litellm_raises() -> None:
    # An *unexpected* LiteLLM error in this advisory check must degrade to no
    # warning, never crash the run. (Unrecognized models don't raise — LiteLLM
    # returns False — so this covers the defensive guard, not the unknown path.)
    with patch(_TARGET, side_effect=Exception("boom")):
        warnings = reasoning_param_warnings(_cfg(temperature=0.2))
    assert warnings == []


def test_pipeline_warnings_label_each_stage() -> None:
    with patch(_TARGET, return_value=True):
        warnings = pipeline_param_warnings(_pipeline(temperature=0.2))
    assert len(warnings) == 2
    assert any(w.startswith("generation: ") for w in warnings)
    assert any(w.startswith("correction: ") for w in warnings)


def test_pipeline_warnings_empty_for_non_reasoning() -> None:
    with patch(_TARGET, return_value=False):
        warnings = pipeline_param_warnings(_pipeline(temperature=0.2))
    assert warnings == []
