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
