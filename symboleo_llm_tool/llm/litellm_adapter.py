from collections.abc import Callable

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
        response = litellm.completion(
            model=f"{self._config.provider}/{self._config.model}",
            messages=[{"role": "user", "content": prompt}],
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
        )
        content: str | None = response.choices[0].message.content
        if content is None:
            raise RuntimeError("LLM returned an empty response.")
        return content
