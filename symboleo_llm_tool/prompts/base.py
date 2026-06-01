from abc import ABC, abstractmethod
from typing import Any

from symboleo_llm_tool.prompts.context import PromptContext


class PromptStrategy(ABC):
    def __init__(self, params: dict[str, Any]) -> None:
        self._params = params

    @abstractmethod
    def build_generation_prompt(self, context: PromptContext) -> str: ...

    @abstractmethod
    def build_correction_prompt(self, context: PromptContext) -> str: ...
