"""Regenerate the committed JSON Schemas for the config file formats.

Run from the repo root:  uv run python scripts/generate_config_schemas.py

A thin writer over ``config/loader.py::render_config_schemas()``, which owns
what the schemas contain (including where a config *file* differs from its
model). The files are committed so editors can validate YAML as it is typed —
the ``# yaml-language-server: $schema=...`` modeline in each shipped run config
points at them — and so a fresh clone gets that without running anything.

Re-run after any config-model change and commit the result;
``tests/unit/test_config_schema.py`` reds until the committed files match.
"""

import json
from pathlib import Path

from symboleo_llm_tool.config.loader import render_config_schemas

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "configs" / "schemas"


def main() -> None:
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    for name, schema in render_config_schemas().items():
        path = SCHEMAS_DIR / name
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
