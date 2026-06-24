from abc import ABC, abstractmethod

from pydantic import BaseModel

from symboleo_llm_tool.output.models import TokenUsage


class GenerationResult(BaseModel):
    """The text an adapter produced plus the token usage of that one call.

    Returned by ``LLMAdapter.generate`` so callers (the pipeline) can attach
    ``usage`` to the per-iteration record without a second round-trip.
    """

    generated_text: str
    usage: TokenUsage


class LLMAdapter(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> GenerationResult: ...
