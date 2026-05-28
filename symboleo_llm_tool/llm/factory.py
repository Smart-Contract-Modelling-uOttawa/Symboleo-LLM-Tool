from symboleo_llm_tool.config.models import LLMConfig
from symboleo_llm_tool.llm.base import LLMAdapter
from symboleo_llm_tool.llm.litellm_adapter import LiteLLMAdapter


def create_adapter(config: LLMConfig) -> LLMAdapter:
    if config.provider == "mock":
        # TEMPORARY — remove this branch when mock_adapter.py is deleted
        from symboleo_llm_tool.llm.mock_adapter import MockLLMAdapter
        return MockLLMAdapter(config)
    return LiteLLMAdapter(config)
