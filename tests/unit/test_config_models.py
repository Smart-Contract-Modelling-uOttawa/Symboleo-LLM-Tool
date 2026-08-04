"""Properties of the config models: input is closed, serialized output is portable.

Config input is closed: an unknown key is an error, not a silent default. Each
level is asserted separately because ``extra="forbid"`` is inherited per model --
a nested model that missed the strict base would still accept typos while the top
level rejected them.

Serialized output is portable: a run record must reload on a different OS than
the one that wrote it, which the same-platform round-trip tests here cannot show.
"""

from pathlib import Path, PurePosixPath
from typing import Any, get_args

import pytest
from pydantic import BaseModel, PlainSerializer, ValidationError

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


def test_path_fields_serialize_with_forward_slashes() -> None:
    """A run record must reload on a different OS than the one that wrote it.

    The round-trip tests above cannot catch this. They reload on the same OS that
    dumped, and ``str(Path)`` uses the host separator -- so a Windows-written
    ``lib\\symboleo-cli.jar`` round-trips there and fails only on POSIX, where it
    parses as one opaque filename instead of a path.
    """
    config = PipelineConfig(
        **_pipeline_dict(),
        symboleo={"jar_path": "vendor/jars/symboleo-cli.jar"},
        output={"directory": "runs/batch-1"},
    )

    dumped = config.model_dump(mode="json")

    # Nested on purpose: a single-segment path has no separator to get wrong, so
    # the shipped defaults would satisfy this even with the bug present.
    assert PurePosixPath(dumped["symboleo"]["jar_path"]).parts == (
        "vendor",
        "jars",
        "symboleo-cli.jar",
    )
    assert PurePosixPath(dumped["output"]["directory"]).parts == ("runs", "batch-1")


def _path_fields(model: type[BaseModel], prefix: str = "") -> list[tuple[str, Any]]:
    """Every `Path`-annotated field in the config tree, as (dotted name, FieldInfo).

    `Annotated[Path, ...]` reports `Path` as its annotation and keeps the
    serializer in `.metadata`, so a portable field and a bare one look identical
    here apart from that metadata — which is exactly the difference under test.
    """
    found: list[tuple[str, Any]] = []
    for name, field in model.model_fields.items():
        dotted = f"{prefix}{name}"
        if field.annotation is Path:
            found.append((dotted, field))
            continue
        # Covers both a directly nested model and one inside a container
        # (SuiteConfig.experiments is a list[Experiment]).
        for candidate in (field.annotation, *get_args(field.annotation)):
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                found.extend(_path_fields(candidate, f"{dotted}."))
    return found


def test_every_path_config_field_is_portable() -> None:
    """`PortablePath` is opt-*in*: a new field declared as bare `Path` would
    silently serialize with host separators again, and every other test here
    would still pass. This is what makes it an enforced convention rather than a
    habit — forgetting reds here, naming the field.
    """
    fields = _path_fields(SuiteConfig)

    # Vacuity guard: an empty walk would make the assertion below trivially true.
    assert len(fields) >= 2, f"walk found no path fields to check: {fields}"
    bare = [
        name
        for name, field in fields
        if not any(isinstance(m, PlainSerializer) for m in field.metadata)
    ]

    assert bare == [], f"declare these as PortablePath, not Path: {bare}"


def test_python_mode_dump_still_yields_path_objects() -> None:
    # The serializer is deliberately scoped to json mode: the defect is in the
    # persisted artifact, so an in-memory dump keeps handing back a real Path and
    # callers doing path arithmetic on it are unaffected.
    config = PipelineConfig(**_pipeline_dict())

    assert isinstance(config.model_dump()["symboleo"]["jar_path"], Path)
