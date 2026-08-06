from abc import ABC, abstractmethod

from pydantic import BaseModel

from symboleo_llm_tool.output.models import TokenUsage


class LLMCallError(RuntimeError):
    """A provider call failed.

    Raised only by adapters, and caught only at the candidate boundary in
    ``pipeline.py``. The narrowness is the point: catching ``Exception`` there
    would record our own bugs in ``report.json`` as provider failures, trading a
    loud data loss for a quiet data corruption.
    """


class GenerationResult(BaseModel):
    """The text an adapter produced plus the token usage of that one call.

    Returned by ``LLMAdapter.generate`` so callers (the pipeline) can attach
    ``usage`` to the per-iteration record without a second round-trip.
    """

    generated_text: str
    usage: TokenUsage


class LLMAdapter(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> GenerationResult:
        """Complete ``prompt``.

        Provider failures must be raised as ``LLMCallError``; the pipeline
        records those as a failed candidate and lets anything else abort the run.
        """
        ...
