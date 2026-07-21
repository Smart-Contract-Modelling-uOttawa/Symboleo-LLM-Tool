from pathlib import Path

import yaml

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
