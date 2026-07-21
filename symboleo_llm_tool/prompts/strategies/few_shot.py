from typing import Any

from symboleo_llm_tool.prompts.base import PromptStrategy, build_jinja_env
from symboleo_llm_tool.prompts.context import PromptContext
from symboleo_llm_tool.prompts.examples import load_example

_env = build_jinja_env("few_shot_generation.j2", "few_shot_correction.j2")


class FewShotStrategy(PromptStrategy):
    _allowed_params = frozenset({"example_files"})

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        example_files = params.get("example_files", [])
        if not isinstance(example_files, list):
            raise ValueError("few_shot strategy: 'example_files' must be a list")
        if not example_files:
            raise ValueError("few_shot strategy: 'example_files' must not be empty")
        self._examples = [load_example(name) for name in example_files]
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
