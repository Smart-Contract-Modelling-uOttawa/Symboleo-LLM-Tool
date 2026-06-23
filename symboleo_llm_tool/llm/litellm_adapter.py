from collections.abc import Callable
from typing import Any

import litellm

from symboleo_llm_tool.config.models import LLMConfig
from symboleo_llm_tool.llm.base import LLMAdapter


class LiteLLMAdapter(LLMAdapter):
    def __init__(self, config: LLMConfig, tracing_enabled: bool = False) -> None:
        self._config = config
        if tracing_enabled:
            from langsmith import traceable

            self._invoke: Callable[[str], str] = traceable(run_type="llm")(self._litellm_call)
        else:
            self._invoke = self._litellm_call

    def generate(self, prompt: str) -> str:
        return self._invoke(prompt)

    def _litellm_call(self, prompt: str) -> str:
        kwargs: dict[str, Any] = {
            "model": self._config.litellm_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self._config.max_tokens,
            # Safety net: drop provider-unsupported sampling params instead of
            # erroring. This is the OpenAI-reasoning backstop; it is a no-op for
            # Anthropic reasoning models (BerriAI/litellm#26444). The primary
            # guard is not sending temperature at all when it isn't set (below).
            "drop_params": True,
        }
        # Only send temperature when explicitly configured — reasoning models
        # reject it, and omitting it is the version-independent fix.
        if self._config.temperature is not None:
            kwargs["temperature"] = self._config.temperature
        response = litellm.completion(**kwargs)
        content: str | None = response.choices[0].message.content
        if content is None:
            raise RuntimeError("LLM returned an empty response.")
        return content
