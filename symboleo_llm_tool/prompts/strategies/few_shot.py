from importlib import resources
from typing import Any

from jinja2 import DictLoader, Environment

from symboleo_llm_tool.prompts import registry
from symboleo_llm_tool.prompts.base import PromptStrategy
from symboleo_llm_tool.prompts.context import PromptContext

_TEMPLATE_NAMES = [
    "_system_header.j2",
    "_grammar_section.j2",
    "few_shot_generation.j2",
    "few_shot_correction.j2",
]


def _build_env() -> Environment:
    pkg = resources.files("symboleo_llm_tool.prompts.templates")
    templates = {
        n: pkg.joinpath(n).read_text(encoding="utf-8") for n in _TEMPLATE_NAMES
    }
    return Environment(loader=DictLoader(templates))


_env = _build_env()


@registry.register("few_shot")
class FewShotStrategy(PromptStrategy):
    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        examples = params.get("examples", [])
        if not isinstance(examples, list):
            raise ValueError("few_shot strategy: 'examples' must be a list")
        self._examples = examples
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
