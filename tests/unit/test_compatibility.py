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


def _mixed_pipeline(generation: float | None, correction: float | None) -> PipelineConfig:
    return PipelineConfig(
        generation=StageConfig(llm=_cfg(generation), strategy="zero_shot"),
        correction=StageConfig(llm=_cfg(correction), strategy="zero_shot"),
    )


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


def test_unknown_model_yields_no_warning_against_real_litellm() -> None:
    # Deliberately unpatched: the "no false alarm for an unrecognized model"
    # property is a claim about real LiteLLM behaviour, so patching the lookup
    # would assert nothing about it.
    warnings = reasoning_param_warnings(
        LLMConfig(provider="openai", model="totally-made-up-model-xyz", temperature=0.2)
    )
    assert warnings == []


def test_pipeline_warnings_label_each_stage() -> None:
    with patch(_TARGET, return_value=True):
        warnings = pipeline_param_warnings(_pipeline(temperature=0.2))
    assert len(warnings) == 2
    assert any(w.startswith("generation: ") for w in warnings)
    assert any(w.startswith("correction: ") for w in warnings)


def test_pipeline_warning_names_generation_when_only_it_offends() -> None:
    # Both stages warning at once cannot reveal a swapped label mapping — the two
    # messages differ only by prefix. One offending stage at a time can.
    with patch(_TARGET, return_value=True):
        warnings = pipeline_param_warnings(_mixed_pipeline(generation=0.2, correction=None))
    assert len(warnings) == 1
    assert warnings[0].startswith("generation: ")


def test_pipeline_warning_names_correction_when_only_it_offends() -> None:
    with patch(_TARGET, return_value=True):
        warnings = pipeline_param_warnings(_mixed_pipeline(generation=None, correction=0.2))
    assert len(warnings) == 1
    assert warnings[0].startswith("correction: ")


def test_pipeline_warnings_empty_for_non_reasoning() -> None:
    with patch(_TARGET, return_value=False):
        warnings = pipeline_param_warnings(_pipeline(temperature=0.2))
    assert warnings == []
