from importlib import resources

from jinja2 import DictLoader, Environment

from symboleo_llm_tool.prompts import registry
from symboleo_llm_tool.prompts.base import PromptStrategy
from symboleo_llm_tool.prompts.context import PromptContext

_TEMPLATE_NAMES = [
    "_system_header.j2",
    "_grammar_section.j2",
    "zero_shot_generation.j2",
    "zero_shot_correction.j2",
]


def _build_env() -> Environment:
    pkg = resources.files("symboleo_llm_tool.prompts.templates")
    templates = {
        n: pkg.joinpath(n).read_text(encoding="utf-8") for n in _TEMPLATE_NAMES
    }
    return Environment(loader=DictLoader(templates))


_env = _build_env()


@registry.register("zero_shot")
class ZeroShotStrategy(PromptStrategy):
    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._generation_template = _env.get_template("zero_shot_generation.j2")
        self._correction_template = _env.get_template("zero_shot_correction.j2")

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
