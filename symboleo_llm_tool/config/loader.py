import warnings
from pathlib import Path
from typing import Any

import yaml
from pydantic.json_schema import PydanticJsonSchemaWarning

from symboleo_llm_tool.config.models import PipelineConfig, SuiteConfig


def load_config(path: Path) -> PipelineConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Config file must be a YAML mapping.")
    return PipelineConfig(**data)


def load_suite_config(path: Path, contract_text: str) -> SuiteConfig:
    """Load a suite file (experiments + settings) and bind the CLI-supplied contract.

    The contract is a CLI argument, never part of the file — consistent with the
    single-run command and keeping legal text out of YAML. A ``contract_text`` key
    in the file is rejected rather than silently ignored, so the source of the
    contract is never ambiguous.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Suite config file must be a YAML mapping.")
    if "contract_text" in data:
        raise ValueError(
            "Suite config must not contain 'contract_text'; the contract is passed "
            "as a CLI argument."
        )
    return SuiteConfig(contract_text=contract_text, **data)


def dump_suite_file(suite: SuiteConfig, *, minimal: bool = False) -> str:
    """Serialize a suite to the input-file schema ``load_suite_config`` accepts.

    Lives beside its inverse so "which keys the file carries" is stated once: the
    contract is dropped here because the loader above rejects it.

    ``minimal`` selects the policy, which differs by purpose and must not be
    unified:

    - ``False`` (default) for a **record of a run** — every value the run used,
      including ones equal to today's defaults. Omitting them would make the
      artifact replay a *different* run if a default later changes.
    - ``True`` for an **export the user will edit** — only what was configured,
      which also drops this machine's ``jar_path``/``output.directory`` and makes
      the file portable.
    """
    data = suite.model_dump(mode="json", exclude_defaults=minimal)
    data.pop("contract_text", None)
    dumped: str = yaml.dump(data, default_flow_style=False, sort_keys=False)
    return dumped


def render_config_schemas() -> dict[str, dict[str, Any]]:
    """The JSON Schemas for the two config *file* formats, keyed by filename.

    Rendered from the models, then adjusted where a file differs from its
    model: a suite file must NOT contain ``contract_text`` (rejected by
    ``load_suite_config`` above), so the suite schema strips it — a schema
    generated straight from ``SuiteConfig`` would fail every valid suite file
    in the editor while passing the one mistake the loader rejects. Lives in
    this module so all three statements of "which keys a suite file carries"
    — reject on load, drop on dump, strip here — sit together.

    Consumed by ``scripts/generate_config_schemas.py`` (writes the committed
    ``configs/schemas/*.json``) and by ``tests/unit/test_config_schema.py``
    (fails CI whenever the committed files no longer match this output).
    """
    with warnings.catch_warnings():
        # The two PortablePath defaults are Path objects the schema renderer
        # cannot express as JSON defaults; it omits them (harmless — both
        # fields are optional) with a warning that would otherwise read as a
        # failure.
        warnings.simplefilter("ignore", PydanticJsonSchemaWarning)
        pipeline_schema = PipelineConfig.model_json_schema()
        suite_schema = SuiteConfig.model_json_schema()

    suite_schema["properties"].pop("contract_text")
    suite_schema["required"].remove("contract_text")
    return {"config.schema.json": pipeline_schema, "suite.schema.json": suite_schema}
