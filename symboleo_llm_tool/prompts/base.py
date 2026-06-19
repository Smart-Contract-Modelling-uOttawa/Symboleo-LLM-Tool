from abc import ABC, abstractmethod
from importlib import resources
from typing import Any

from jinja2 import DictLoader, Environment

from symboleo_llm_tool.prompts.context import PromptContext


def build_jinja_env(template_names: list[str]) -> Environment:
    pkg = resources.files(f"{__package__}.templates")
    templates = {n: pkg.joinpath(n).read_text(encoding="utf-8") for n in template_names}
    return Environment(loader=DictLoader(templates))


class PromptStrategy(ABC):
    def __init__(self, params: dict[str, Any]) -> None:
        self._params = params

    @abstractmethod
    def build_generation_prompt(self, context: PromptContext) -> str: ...

    @abstractmethod
    def build_correction_prompt(self, context: PromptContext) -> str: ...
