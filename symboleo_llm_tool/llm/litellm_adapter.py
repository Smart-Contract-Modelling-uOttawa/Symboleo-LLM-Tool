from collections.abc import Callable
from typing import Any

import litellm

from symboleo_llm_tool.config.models import LLMConfig
from symboleo_llm_tool.llm.base import GenerationResult, LLMAdapter
from symboleo_llm_tool.output.models import TokenUsage


class LiteLLMAdapter(LLMAdapter):
    def __init__(self, config: LLMConfig, tracing_enabled: bool = False) -> None:
        self._config = config
        if tracing_enabled:
            from langsmith import traceable

            self._invoke: Callable[[str], GenerationResult] = traceable(run_type="llm")(
                self._litellm_call
            )
        else:
            self._invoke = self._litellm_call

    def generate(self, prompt: str) -> GenerationResult:
        return self._invoke(prompt)

    def _litellm_call(self, prompt: str) -> GenerationResult:
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
        return GenerationResult(generated_text=content, usage=_extract_usage(response))


def _extract_usage(response: Any) -> TokenUsage:
    """Pull token counts and dollar cost out of a LiteLLM completion response.

    Cost is best-effort: ``litellm.completion_cost`` raises for models missing
    from the pricing map, in which case ``cost_usd`` is ``None``.
    """
    usage = getattr(response, "usage", None)
    try:
        cost: float | None = litellm.completion_cost(completion_response=response)
    except Exception:
        cost = None
    # total_tokens is a computed field on TokenUsage, so it is not passed here.
    return TokenUsage(
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        cost_usd=cost,
    )
