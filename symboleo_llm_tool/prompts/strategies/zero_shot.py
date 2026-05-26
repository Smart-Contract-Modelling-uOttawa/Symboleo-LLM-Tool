from importlib import resources

from jinja2 import BaseLoader, Environment

from symboleo_llm_tool.prompts import registry
from symboleo_llm_tool.prompts.base import PromptStrategy
from symboleo_llm_tool.prompts.context import PromptContext


def _load_template(name: str) -> str:
    template_file = resources.files("symboleo_llm_tool.prompts.templates").joinpath(name)
    return template_file.read_text(encoding="utf-8")


@registry.register("zero_shot")
class ZeroShotStrategy(PromptStrategy):
    def __init__(self, params: dict) -> None:
        super().__init__(params)
        env = Environment(loader=BaseLoader())
        self._generation_template = env.from_string(_load_template("zero_shot_generation.j2"))
        self._correction_template = env.from_string(_load_template("zero_shot_correction.j2"))

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
