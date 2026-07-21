"""Request settings → PipelineConfig translation.

The endpoints' happy-path tests patch the pipeline away and can only assert a
200, so every mapping here — provider resolution, the omit-when-unset fields,
correction defaulting to generation — is exercised directly instead.
"""

from pathlib import Path

import pytest

from symboleo_llm_tool.api.config_builder import (
    build_pipeline_config,
    build_stage_config,
    get_parameter_defaults,
    resolve_provider,
)
from symboleo_llm_tool.api.models import GenerateRequest, StageRequest
from symboleo_llm_tool.config.models import LLMConfig, RunConfig

_MODEL_TO_PROVIDER = {"gpt-4o-mini": "openai", "claude-haiku-4-5": "anthropic"}


def _request(**overrides: object) -> GenerateRequest:
    body: dict[str, object] = {
        "contract_text": "Seller shall deliver goods.",
        "generation": StageRequest(model="gpt-4o-mini", strategy="zero_shot"),
    }
    body.update(overrides)
    return GenerateRequest(**body)  # type: ignore[arg-type]


class TestProviderResolution:
    def test_maps_each_model_to_its_own_provider(self) -> None:
        assert resolve_provider("gpt-4o-mini", _MODEL_TO_PROVIDER) == "openai"
        assert resolve_provider("claude-haiku-4-5", _MODEL_TO_PROVIDER) == "anthropic"

    def test_rejects_a_model_the_ui_config_does_not_list(self) -> None:
        with pytest.raises(ValueError, match="Unknown model"):
            resolve_provider("gpt-9-ultra", _MODEL_TO_PROVIDER)


class TestStageConfig:
    def test_omits_temperature_when_the_request_leaves_it_unset(self) -> None:
        # The reasoning-model guard starts here: an unset temperature must not
        # become a concrete value on its way to the adapter.
        request = StageRequest(model="gpt-4o-mini", strategy="zero_shot")
        stage = build_stage_config(request, "openai")
        assert stage.llm.temperature is None

    def test_carries_an_explicit_temperature_and_grammar_flag(self) -> None:
        stage = build_stage_config(
            StageRequest(
                model="gpt-4o-mini",
                strategy="zero_shot",
                temperature=0.2,
                include_grammar=False,
            ),
            "openai",
        )
        assert stage.llm.temperature == 0.2
        assert stage.include_grammar is False

    def test_defaults_include_grammar_to_the_model_default_when_unset(self) -> None:
        request = StageRequest(model="gpt-4o-mini", strategy="zero_shot")
        stage = build_stage_config(request, "openai")
        assert stage.include_grammar is True

    def test_resolves_example_names_to_paths_under_the_examples_dir(self) -> None:
        stage = build_stage_config(
            StageRequest(
                model="gpt-4o-mini",
                strategy="zero_shot",
                strategy_params={"example_files": ["sale_contract"]},
            ),
            "openai",
        )
        resolved = stage.strategy_params["example_files"]
        assert [Path(p).name for p in resolved] == ["sale_contract.yaml"]

    def test_leaves_strategy_params_alone_when_no_examples_are_named(self) -> None:
        stage = build_stage_config(
            StageRequest(model="gpt-4o-mini", strategy="zero_shot", strategy_params={"k": "v"}),
            "openai",
        )
        assert stage.strategy_params == {"k": "v"}


class TestPipelineConfig:
    def test_correction_defaults_to_the_generation_stage(self) -> None:
        config = build_pipeline_config(_request(), _MODEL_TO_PROVIDER)
        assert config.correction.llm.model == "gpt-4o-mini"
        assert config.correction.strategy == "zero_shot"

    def test_an_explicit_correction_stage_is_resolved_independently(self) -> None:
        # Different model *and* provider from generation, so a build that reused
        # the generation stage for both would fail here.
        config = build_pipeline_config(
            _request(
                correction=StageRequest(model="claude-haiku-4-5", strategy="cot", temperature=0.9)
            ),
            _MODEL_TO_PROVIDER,
        )
        assert config.generation.llm.provider == "openai"
        assert config.generation.strategy == "zero_shot"
        assert config.correction.llm.provider == "anthropic"
        assert config.correction.llm.model == "claude-haiku-4-5"
        assert config.correction.strategy == "cot"
        assert config.correction.llm.temperature == 0.9

    def test_run_options_land_in_their_own_fields(self) -> None:
        # Every value differs from both its default and the others, so a field
        # swapped for its neighbour fails.
        config = build_pipeline_config(
            _request(
                num_candidates=4,
                max_iterations=7,
                stop_on_first_convergence=True,
                save_intermediates=True,
            ),
            _MODEL_TO_PROVIDER,
        )
        assert config.pipeline.num_candidates == 4
        assert config.pipeline.max_iterations == 7
        assert config.pipeline.stop_on_first_convergence is True
        assert config.output.save_intermediates is True

    def test_unset_run_options_fall_back_to_the_pydantic_defaults(self) -> None:
        config = build_pipeline_config(_request(), _MODEL_TO_PROVIDER)
        assert config.pipeline.num_candidates == RunConfig().num_candidates
        assert config.pipeline.max_iterations == RunConfig().max_iterations
        assert config.pipeline.stop_on_first_convergence is False
        assert config.output.save_intermediates is False

    def test_rejects_an_unknown_strategy_before_any_job_starts(self) -> None:
        with pytest.raises(ValueError):
            build_pipeline_config(
                _request(generation=StageRequest(model="gpt-4o-mini", strategy="no_such_strategy")),
                _MODEL_TO_PROVIDER,
            )


class TestParameterDefaults:
    def test_fills_each_known_parameter_from_its_owning_model(self) -> None:
        defaults = get_parameter_defaults(
            {"num_candidates": {"type": "int", "min": 1}, "temperature": {"type": "float"}}
        )
        assert defaults["num_candidates"]["default"] == RunConfig().num_candidates
        # temperature deliberately has no forced default — the frontend shows the
        # field empty rather than pre-filling a value reasoning models reject.
        assert defaults["temperature"]["default"] == LLMConfig(provider="p", model="m").temperature
        assert defaults["num_candidates"]["min"] == 1  # ui constraints are preserved

    def test_leaves_an_unrecognised_parameter_untouched(self) -> None:
        defaults = get_parameter_defaults({"mystery": {"type": "int"}})
        assert defaults["mystery"] == {"type": "int"}
