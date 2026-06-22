from typing import Any

from symboleo_llm_tool.prompts.base import PromptStrategy, build_jinja_env
from symboleo_llm_tool.prompts.context import PromptContext

_env = build_jinja_env(
    [
        "_system_header.j2",
        "_grammar_section.j2",
        "_placeholder_guidance.j2",
        "cot_generation.j2",
        "cot_correction.j2",
    ]
)


class CoTStrategy(PromptStrategy):
    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self._generation_template = _env.get_template("cot_generation.j2")
        self._correction_template = _env.get_template("cot_correction.j2")

    def build_generation_prompt(self, context: PromptContext) -> str:
        return self._generation_template.render(
            contract_text=context.contract_text,
            grammar_context=context.grammar_context,
        )

    def build_correction_prompt(self, context: PromptContext) -> str:
        return self._correction_template.render(
            current_code=context.current_code,
            errors=context.errors,
            grammar_context=context.grammar_context,
        )
