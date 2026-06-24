# TEMPORARY — mock LLM for manual testing without an API key.
# To remove: delete this file, remove the "mock" branch in factory.py,
# and delete configs/mock.yaml.
from pathlib import Path

from symboleo_llm_tool.config.models import LLMConfig
from symboleo_llm_tool.llm.base import GenerationResult, LLMAdapter
from symboleo_llm_tool.output.models import TokenUsage

_FIXTURES = Path("tests/fixtures")


class MockLLMAdapter(LLMAdapter):
    """Returns invalid.symboleo on the first call, valid.symboleo on all subsequent calls."""

    def __init__(self, config: LLMConfig) -> None:
        self._call_count = 0

    def generate(self, prompt: str) -> GenerationResult:
        self._call_count += 1
        fixture = "invalid.symboleo" if self._call_count == 1 else "valid.symboleo"
        text = (_FIXTURES / fixture).read_text(encoding="utf-8")
        usage = TokenUsage(prompt_tokens=0, completion_tokens=0, cost_usd=None)
        return GenerationResult(generated_text=text, usage=usage)
