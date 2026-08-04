"""The committed config JSON Schemas: current, world-closing, and actually used.

The schemas exist for editor-time validation, so they are committed files (a
modeline can only point at a path on disk) — which makes them a copy that can
drift when ``config/models.py`` changes. Generation is shared with the writer
script via ``config/loader.py::render_config_schemas()``, so there is exactly
one statement of what the schemas contain.
"""

import json
import re
from pathlib import Path

import jsonschema
import pytest
import yaml

from symboleo_llm_tool.config.loader import render_config_schemas

_CONFIGS = Path("configs")
_SCHEMAS_DIR = _CONFIGS / "schemas"
_SCHEMA_FILES = sorted(render_config_schemas())

# ui_config.yaml is the frontend's model/parameter list, not a pipeline config —
# the one shipped YAML that correctly declares no schema.
_NO_MODELINE = {"ui_config.yaml"}
_MODELINE = re.compile(r"^#\s*yaml-language-server:\s*\$schema=(\S+)")


@pytest.mark.parametrize("filename", _SCHEMA_FILES)
def test_committed_schema_matches_live_generation(filename: str) -> None:
    """A model change reds this until the generator is re-run and committed.

    Parsed comparison, not bytes — semantic equality is the contract;
    whitespace and key order are the serializer's business.
    """
    committed = json.loads((_SCHEMAS_DIR / filename).read_text(encoding="utf-8"))

    assert committed == render_config_schemas()[filename], (
        f"configs/schemas/{filename} is stale — run `uv run python "
        "scripts/generate_config_schemas.py` and commit the result"
    )


@pytest.mark.parametrize("filename", _SCHEMA_FILES)
def test_schema_closes_the_world(filename: str) -> None:
    """`additionalProperties: false` must reach every level of both schemas.

    This is the editor-time mirror of the loader's `extra="forbid"` — the
    property that flags a typo'd key while it is being typed. It comes from
    `_StrictModel`, so losing it (a base-class change, a pydantic behaviour
    shift, one model no longer inheriting the base) would neuter the modelines
    silently: the schemas would still exist and still check types, just no
    longer reject unknown keys.
    """
    schema = json.loads((_SCHEMAS_DIR / filename).read_text(encoding="utf-8"))

    assert schema["additionalProperties"] is False
    for name, definition in schema.get("$defs", {}).items():
        assert definition.get("additionalProperties") is False, (
            f"{filename}: $defs.{name} does not close the world"
        )


def test_schema_carries_the_numeric_bounds() -> None:
    """The bounds must actually reach the schema, pinned by value.

    Complements the rejection tests in ``test_config_models.py``: those fence
    the loader's behaviour; this fences the editor's. Together they close the
    laundering path where dropping a ``Field`` bound reds only the snapshot
    test, whose remediation (regenerate + commit) would erase the bound.
    """
    schema = json.loads((_SCHEMAS_DIR / "config.schema.json").read_text(encoding="utf-8"))
    defs = schema["$defs"]

    temperature = defs["LLMConfig"]["properties"]["temperature"]["anyOf"][0]
    assert temperature["minimum"] == 0.0
    assert temperature["maximum"] == 2.0
    assert defs["LLMConfig"]["properties"]["max_tokens"]["minimum"] == 1
    assert defs["RunConfig"]["properties"]["num_candidates"]["minimum"] == 1
    assert defs["RunConfig"]["properties"]["max_iterations"]["minimum"] == 0

    suite = json.loads((_SCHEMAS_DIR / "suite.schema.json").read_text(encoding="utf-8"))
    assert suite["properties"]["experiments"]["minItems"] == 1


@pytest.mark.parametrize("filename", _SCHEMA_FILES)
def test_path_defaults_are_stripped(filename: str) -> None:
    """No path-format property may carry a ``default`` in a committed schema.

    Pydantic renders Path defaults platform-dependently — omitted on Windows,
    emitted on POSIX — so an unstripped default makes the committed artifact
    disagree with regeneration on the *other* OS: green locally, red in CI.
    The renderer strips them; this pins that for every current and future
    Path-typed field.
    """
    schema = json.loads((_SCHEMAS_DIR / filename).read_text(encoding="utf-8"))

    for def_name, definition in schema.get("$defs", {}).items():
        for prop_name, prop in definition.get("properties", {}).items():
            if prop.get("format") == "path":
                assert "default" not in prop, f"{filename}: {def_name}.{prop_name}"


def test_suite_schema_omits_contract_text_entirely() -> None:
    """A suite *file* must not carry ``contract_text`` — the loader rejects it.

    Absent from ``required`` is not enough: an optional *declared* property
    would make the editor accept the one key the loader rejects, because
    ``additionalProperties: false`` never fires on a declared key. Both halves
    of the strip in ``render_config_schemas`` are pinned here.
    """
    suite = json.loads((_SCHEMAS_DIR / "suite.schema.json").read_text(encoding="utf-8"))

    assert "contract_text" not in suite["properties"]
    assert "contract_text" not in suite["required"]


@pytest.mark.parametrize("yaml_path", sorted(_CONFIGS.glob("*.yaml")), ids=lambda p: p.name)
def test_shipped_config_validates_against_its_modeline_schema(yaml_path: Path) -> None:
    """Every shipped YAML must pass the schema its own modeline declares.

    This exercises the product feature itself — "the editor validates your
    config" — which the committed-matches-live test cannot see. It is what
    catches a schema describing the *model* where the *file* differs: a suite
    schema requiring ``contract_text`` passes generation-comparison happily
    while flagging every valid suite file in the editor.

    Also fences the modeline's presence: a new shipped config without one gets
    no editor validation, silently.
    """
    first_line = yaml_path.read_text(encoding="utf-8").splitlines()[0]
    match = _MODELINE.match(first_line)

    if yaml_path.name in _NO_MODELINE:
        assert match is None, f"{yaml_path.name} should not declare a schema"
        return
    assert match, f"{yaml_path.name} has no yaml-language-server modeline"

    # Resolve the modeline the way an editor does: relative to the YAML file.
    schema_path = yaml_path.parent / match.group(1)
    assert schema_path.exists(), f"{yaml_path.name}'s modeline points at a missing file"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    jsonschema.validate(data, schema)  # raises ValidationError on mismatch
