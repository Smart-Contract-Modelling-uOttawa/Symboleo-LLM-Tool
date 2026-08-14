from pathlib import Path
from unittest.mock import patch

import yaml

from symboleo_llm_tool.config.models import (
    Experiment,
    LLMConfig,
    PipelineConfig,
    StageConfig,
    SuiteConfig,
)
from symboleo_llm_tool.llm.compatibility import (
    _TEMPERATURE_RANGES,
    effort_warnings,
    llm_param_warnings,
    pipeline_param_warnings,
    reasoning_models,
    reasoning_param_warnings,
    suite_param_warnings,
    temperature_range_warnings,
)

_TARGET = "symboleo_llm_tool.llm.compatibility.litellm.supports_reasoning"


def _cfg(temperature: float | None) -> LLMConfig:
    return LLMConfig(provider="openai", model="gpt-5", temperature=temperature)


def _anthropic_cfg(temperature: float | None) -> LLMConfig:
    return LLMConfig(provider="anthropic", model="claude-haiku-4-5", temperature=temperature)


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


def test_range_warning_when_temperature_exceeds_provider_max() -> None:
    warnings = temperature_range_warnings(_anthropic_cfg(temperature=1.5))
    assert len(warnings) == 1
    assert "anthropic" in warnings[0]
    assert "1.5" in warnings[0]


def test_no_range_warning_at_provider_boundaries() -> None:
    assert temperature_range_warnings(_anthropic_cfg(temperature=1.0)) == []
    assert temperature_range_warnings(_anthropic_cfg(temperature=0.0)) == []


def test_no_range_warning_within_provider_range() -> None:
    # 1.5 warns for anthropic (above) but is valid for openai — the check is
    # provider-keyed, not a second global bound.
    assert temperature_range_warnings(_cfg(temperature=1.5)) == []


def test_no_range_warning_for_unknown_provider() -> None:
    cfg = LLMConfig(provider="mistral", model="mistral-large", temperature=1.5)
    assert temperature_range_warnings(cfg) == []


def test_no_range_warning_when_temperature_unset() -> None:
    assert temperature_range_warnings(_anthropic_cfg(temperature=None)) == []


def test_pipeline_labels_range_warning_by_stage() -> None:
    # Range warnings ride the same stage labeling as reasoning warnings; only
    # the offending stage is named.
    config = PipelineConfig(
        generation=StageConfig(llm=_anthropic_cfg(1.5), strategy="zero_shot"),
        correction=StageConfig(llm=_anthropic_cfg(0.2), strategy="zero_shot"),
    )
    with patch(_TARGET, return_value=False):
        warnings = pipeline_param_warnings(config)
    assert len(warnings) == 1
    assert warnings[0].startswith("generation: ")
    assert "anthropic" in warnings[0]


def test_reasoning_and_range_warnings_compose() -> None:
    # A set-and-out-of-range temperature on a reasoning model earns both
    # advisories — one of each kind, not one kind twice.
    with patch(_TARGET, return_value=True):
        warnings = llm_param_warnings(_anthropic_cfg(temperature=1.5))
    assert len(warnings) == 2
    # Count by kind rather than position: no consumer depends on the order,
    # so a reordered composite should not redden this test.
    assert sum("reasoning model" in w for w in warnings) == 1
    assert sum("outside" in w for w in warnings) == 1


def test_unset_temperature_clears_both_composed_warnings() -> None:
    with patch(_TARGET, return_value=True):
        assert llm_param_warnings(_anthropic_cfg(temperature=None)) == []


def _effort_cfg(effort: str | None) -> LLMConfig:
    return LLMConfig(provider="openai", model="gpt-4o-mini", effort=effort)


def test_effort_warning_on_non_reasoning_model() -> None:
    # drop_params strips an unsupported reasoning_effort silently, so the run
    # would measure nothing effort-related — the advisory's whole point.
    with patch(_TARGET, return_value=False):
        warnings = effort_warnings(_effort_cfg("high"))
    assert len(warnings) == 1
    assert "effort='high'" in warnings[0]
    assert "gpt-4o-mini" in warnings[0]


def test_no_effort_warning_on_reasoning_model() -> None:
    with patch(_TARGET, return_value=True):
        assert effort_warnings(_effort_cfg("xhigh")) == []


def test_no_effort_warning_when_unset() -> None:
    with patch(_TARGET, return_value=False):
        assert effort_warnings(_effort_cfg(None)) == []


def test_no_effort_warning_when_litellm_raises() -> None:
    with patch(_TARGET, side_effect=Exception("boom")):
        assert effort_warnings(_effort_cfg("high")) == []


def test_effort_warns_on_unknown_model_against_real_litellm() -> None:
    # The documented asymmetry with the temperature checks' fail-quiet contract:
    # an unknown model reads as non-reasoning and DOES draw the effort warning,
    # because staying quiet would let a silently-dropped effort corrupt the
    # comparison the field exists for. Unpatched for the same reason as the
    # temperature unknown-model test: the claim is about real LiteLLM behaviour.
    warnings = effort_warnings(
        LLMConfig(provider="openai", model="totally-made-up-model-xyz", effort="high")
    )
    assert len(warnings) == 1


def test_effort_warning_joins_the_composed_warnings() -> None:
    # temperature + effort on a non-reasoning model: the range check passes
    # (1.5 is in openai's range), reasoning check passes (not reasoning), and
    # the effort advisory still lands via llm_param_warnings.
    cfg = LLMConfig(provider="openai", model="gpt-4o-mini", temperature=1.5, effort="low")
    with patch(_TARGET, return_value=False):
        warnings = llm_param_warnings(cfg)
    assert len(warnings) == 1
    assert "effort" in warnings[0]


def test_range_table_stays_within_the_hard_envelope() -> None:
    # A table row wider than the LLMConfig validator's envelope would advise a
    # range the hard validator rejects — contradictory UX, and nothing else
    # reddens. Constructing a config at each bound proves representability
    # without duplicating the envelope literal here. An inverted row (low >
    # high) would warn on every set temperature — a constant false alarm the
    # module contract forbids — and both endpoints still construct, so it
    # needs its own assert.
    assert _TEMPERATURE_RANGES
    for provider, (low, high) in _TEMPERATURE_RANGES.items():
        assert low <= high, f"{provider} row is inverted"
        LLMConfig(provider=provider, model="any", temperature=low)
        LLMConfig(provider=provider, model="any", temperature=high)


def test_shipped_ui_config_models_block_maps_providers_to_name_lists() -> None:
    # routes.py builds model->provider with `for model in models`, so a scalar
    # instead of a list iterates the string's characters and silently yields a
    # corrupted map rather than failing. Nothing else parses this block.
    data = yaml.safe_load(Path("configs/app/ui_config.yaml").read_text(encoding="utf-8"))
    assert data["models"]
    for provider, names in data["models"].items():
        assert isinstance(names, list) and names, f"{provider} must map to a non-empty list"
        assert all(isinstance(n, str) for n in names)


def test_shipped_ui_config_lists_openai_first() -> None:
    # The frontend seeds its default model from the first model of the first
    # provider, so provider order is behaviour, not formatting.
    data = yaml.safe_load(Path("configs/app/ui_config.yaml").read_text(encoding="utf-8"))
    assert next(iter(data["models"])) == "openai"


def test_reasoning_models_flags_only_the_reasoning_entries() -> None:
    # Against the real pinned map: the per-provider dict flattens to the names
    # a form must gate, and an unknown model is silently not flagged — the
    # fail-quiet contract, where a missed flag costs an enabled field and a
    # contained 400, never a blocked run.
    flagged = reasoning_models(
        {
            "openai": ["gpt-4o-mini", "gpt-5-nano"],
            "anthropic": ["claude-opus-4-8"],
            "nosuch": ["model-that-does-not-exist"],
        }
    )
    assert "gpt-5-nano" in flagged
    assert "claude-opus-4-8" in flagged
    assert "gpt-4o-mini" not in flagged
    assert "model-that-does-not-exist" not in flagged


def test_reasoning_models_survives_a_litellm_failure() -> None:
    # Advisory contract: a freak LiteLLM error degrades to "not flagged",
    # never a crashed options request.
    with patch(_TARGET, side_effect=RuntimeError("boom")):
        assert reasoning_models({"openai": ["gpt-5-nano"]}) == []


def test_shipped_ui_config_gpt5_entries_are_flagged_reasoning() -> None:
    # The form gates its temperature seed on this flag, so the shipped gpt-5*
    # entries MUST be flagged or the seed rides into a request the provider
    # 400s (observed live on gpt-5.6-luna, 2026-08-10). The non-reasoning
    # entries must stay unflagged or their seed disappears for no reason.
    data = yaml.safe_load(Path("configs/app/ui_config.yaml").read_text(encoding="utf-8"))
    flagged = set(reasoning_models(data["models"]))
    openai_names = set(data["models"]["openai"])
    gpt5 = {name for name in openai_names if name.startswith("gpt-5")}
    assert gpt5, "shipped config lost its gpt-5 entries — update this fence"
    assert gpt5 <= flagged
    assert not {"gpt-4o", "gpt-4o-mini", "gpt-4.1-mini"} & flagged


def test_cohere_is_deliberately_absent_from_the_range_table() -> None:
    # Cohere documents no temperature cap, so it has no row on purpose. A
    # guessed row would warn on every Cohere run; this pins the omission.
    assert "cohere" not in _TEMPERATURE_RANGES
    cfg = LLMConfig(provider="cohere", model="command-a-03-2025", temperature=1.5)
    assert temperature_range_warnings(cfg) == []


def test_shipped_ui_config_temperature_bounds_fit_the_hard_envelope() -> None:
    # The shipped deployment file advertises the UI's temperature bounds; a
    # bound outside the validator's envelope would let the form submit a value
    # the backend 422s. Same construct-oracle as the table fence, applied to
    # the repo's shipped copy (the file is deployment-mutable by design).
    data = yaml.safe_load(Path("configs/app/ui_config.yaml").read_text(encoding="utf-8"))
    bounds = data["parameters"]["temperature"]
    LLMConfig(provider="openai", model="any", temperature=bounds["min"])
    LLMConfig(provider="openai", model="any", temperature=bounds["max"])


def test_suite_warnings_pair_experiment_name_with_stage_labeled_range_warning() -> None:
    # The one test that runs the real suite -> pipeline -> range chain
    # unmocked: a composition bug (e.g. suite_param_warnings bypassing the
    # stage labeling) passes every per-function test but fails here.
    suite = SuiteConfig(
        contract_text="c",
        experiments=[
            Experiment(
                name="exp-a",
                config=PipelineConfig(
                    generation=StageConfig(llm=_anthropic_cfg(1.5), strategy="zero_shot"),
                    correction=StageConfig(llm=_anthropic_cfg(0.2), strategy="zero_shot"),
                ),
            )
        ],
    )
    with patch(_TARGET, return_value=False):
        pairs = suite_param_warnings(suite)
    assert len(pairs) == 1
    name, warning = pairs[0]
    assert name == "exp-a"
    assert warning.startswith("generation: ")
    assert "anthropic" in warning
