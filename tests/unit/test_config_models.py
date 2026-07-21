"""Config input is closed: an unknown key is an error, not a silent default.

Each level is asserted separately because ``extra="forbid"`` is inherited per
model -- a nested model that missed the strict base would still accept typos
while the top level rejected them.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from symboleo_llm_tool.config.models import PipelineConfig, SuiteConfig

# Raw dicts, not model instances: what is under test is how unrecognized input
# is treated on the way *into* the model, so the input cannot be pre-validated.


def _stage_dict() -> dict[str, Any]:
    return {"llm": {"provider": "openai", "model": "gpt-4o-mini"}, "strategy": "zero_shot"}


def _pipeline_dict() -> dict[str, Any]:
    return {"generation": _stage_dict(), "correction": _stage_dict()}


def _suite_dict() -> dict[str, Any]:
    return {
        "contract_text": "Seller shall deliver the goods.",
        "experiments": [{"name": "zero-shot", "config": _pipeline_dict()}],
    }


def test_accepts_a_well_formed_config() -> None:
    # Negative control: the cases below differ from this one only by the typo,
    # so a rejection there cannot be blamed on a malformed base config.
    config = PipelineConfig(**_pipeline_dict())

    assert config.generation.llm.model == "gpt-4o-mini"


def test_rejects_unknown_top_level_key() -> None:
    data = _pipeline_dict() | {"pipelines": {"max_iterations": 5}}

    with pytest.raises(ValidationError, match="pipelines"):
        PipelineConfig(**data)


def test_rejects_unknown_key_inside_llm() -> None:
    data = _pipeline_dict()
    data["generation"]["llm"]["temprature"] = 0.9

    with pytest.raises(ValidationError, match="temprature"):
        PipelineConfig(**data)


def test_rejects_unknown_key_inside_run_config() -> None:
    data = _pipeline_dict() | {"pipeline": {"max_iterationss": 99}}

    with pytest.raises(ValidationError, match="max_iterationss"):
        PipelineConfig(**data)


def test_rejects_unknown_key_inside_stage() -> None:
    data = _pipeline_dict()
    data["correction"]["include_gramar"] = False

    with pytest.raises(ValidationError, match="include_gramar"):
        PipelineConfig(**data)


def test_rejects_unknown_suite_level_key() -> None:
    data = _suite_dict() | {"max_concurency": 4}

    with pytest.raises(ValidationError, match="max_concurency"):
        SuiteConfig(**data)


def test_rejects_unknown_key_inside_experiment() -> None:
    data = _suite_dict()
    data["experiments"][0]["configg"] = _pipeline_dict()

    with pytest.raises(ValidationError, match="configg"):
        SuiteConfig(**data)


def test_dumped_config_reloads_under_forbid() -> None:
    # write_results and write_suite_results persist a model_dump as the run's
    # config.yaml/suite.yaml. If a dump carried any key the model does not
    # declare, forbid would make those artifacts unloadable.
    config = PipelineConfig(**_pipeline_dict())

    reloaded = PipelineConfig(**config.model_dump(mode="json"))

    assert reloaded == config


def test_dumped_suite_reloads_under_forbid() -> None:
    suite = SuiteConfig(**_suite_dict())

    reloaded = SuiteConfig(**suite.model_dump(mode="json"))

    assert reloaded == suite
