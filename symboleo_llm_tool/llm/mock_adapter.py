# TEMPORARY — mock LLM for manual testing without an API key.
# To remove: delete this file, remove the "mock" branch in factory.py, and delete configs/mock.yaml.
from pathlib import Path

from symboleo_llm_tool.config.models import LLMConfig
from symboleo_llm_tool.llm.base import LLMAdapter

_FIXTURES = Path("tests/fixtures")


class MockLLMAdapter(LLMAdapter):
    """Returns invalid.sl on the first call, valid.sl on all subsequent calls."""

    def __init__(self, config: LLMConfig) -> None:
        self._call_count = 0

    def generate(self, prompt: str) -> str:
        self._call_count += 1
        fixture = "invalid.sl" if self._call_count == 1 else "valid.sl"
        return (_FIXTURES / fixture).read_text(encoding="utf-8")
