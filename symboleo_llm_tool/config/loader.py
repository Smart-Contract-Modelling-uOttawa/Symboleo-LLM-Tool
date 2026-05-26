from pathlib import Path

import yaml

from symboleo_llm_tool.config.models import PipelineConfig


def load_config(path: Path) -> PipelineConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return PipelineConfig(**data)
