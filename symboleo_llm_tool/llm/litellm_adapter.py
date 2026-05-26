import litellm

from symboleo_llm_tool.config.models import LLMConfig
from symboleo_llm_tool.llm.base import LLMAdapter


class LiteLLMAdapter(LLMAdapter):
    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    def generate(self, prompt: str) -> str:
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
