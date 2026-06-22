from abc import ABC, abstractmethod
from importlib import resources
from typing import Any

from jinja2 import DictLoader, Environment

from symboleo_llm_tool.prompts.context import PromptContext


def build_jinja_env(*template_names: str) -> Environment:
    """Build an env containing the named strategy templates plus all shared
    partials.

    Shared partials are the ``_``-prefixed ``.j2`` files in ``templates/``; they
    are always loaded so a strategy never has to re-list them. Which partials a
    strategy actually uses is controlled by the ``{% include %}`` directives in
    its own templates, not by this list -- an available-but-unincluded partial
    renders nothing.
    """
    pkg = resources.files(f"{__package__}.templates")
    partials = {
        r.name: r.read_text(encoding="utf-8")
        for r in pkg.iterdir()
        if r.name.startswith("_") and r.name.endswith(".j2")
    }
    specific = {n: pkg.joinpath(n).read_text(encoding="utf-8") for n in template_names}
    return Environment(loader=DictLoader(partials | specific))


class PromptStrategy(ABC):
    def __init__(self, params: dict[str, Any]) -> None:
        self._params = params

    @abstractmethod
    def build_generation_prompt(self, context: PromptContext) -> str: ...

    @abstractmethod
    def build_correction_prompt(self, context: PromptContext) -> str: ...
