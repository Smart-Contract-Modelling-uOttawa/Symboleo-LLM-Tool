from pathlib import Path
from typing import Any

import yaml

from symboleo_llm_tool.prompts.base import PromptStrategy, build_jinja_env
from symboleo_llm_tool.prompts.context import PromptContext

_env = build_jinja_env(
    [
        "_system_header.j2",
        "_grammar_section.j2",
        "few_shot_generation.j2",
        "few_shot_correction.j2",
    ]
)


def _load_examples(example_files: list[str]) -> list[dict[str, str]]:
    examples = []
    for path_str in example_files:
        path = Path(path_str)
        if not path.exists():
            raise ValueError(f"Example not found: {path!r}")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "contract_text" not in data or "symboleo_code" not in data:
            raise ValueError(
                f"few_shot strategy: {path} must have 'contract_text' and 'symboleo_code' keys"
            )
        examples.append(
            {"contract_text": data["contract_text"], "symboleo_code": data["symboleo_code"]}
        )
    return examples


class FewShotStrategy(PromptStrategy):
    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        example_files = params.get("example_files", [])
        if not isinstance(example_files, list):
            raise ValueError("few_shot strategy: 'example_files' must be a list")
        if not example_files:
            raise ValueError("few_shot strategy: 'example_files' must not be empty")
        self._examples = _load_examples(example_files)
        self._generation_template = _env.get_template("few_shot_generation.j2")
        self._correction_template = _env.get_template("few_shot_correction.j2")

    def build_generation_prompt(self, context: PromptContext) -> str:
        return self._generation_template.render(
            contract_text=context.contract_text,
            grammar_context=context.grammar_context,
            examples=self._examples,
        )

    def build_correction_prompt(self, context: PromptContext) -> str:
        return self._correction_template.render(
            current_code=context.current_code,
            errors=context.errors,
            grammar_context=context.grammar_context,
        )
