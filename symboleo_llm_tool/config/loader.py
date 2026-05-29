from pathlib import Path

import yaml

from symboleo_llm_tool.config.models import PipelineConfig


def load_config(path: Path) -> PipelineConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Config file must be a YAML mapping.")
    return PipelineConfig(**data)
