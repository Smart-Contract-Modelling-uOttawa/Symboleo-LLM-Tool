from collections.abc import Callable
from typing import Any

import litellm

from symboleo_llm_tool.config.models import LLMConfig
from symboleo_llm_tool.llm.base import GenerationResult, LLMAdapter, LLMCallError
from symboleo_llm_tool.output.models import TokenUsage

# LiteLLM's default `request_timeout` is 6000s (100 min) — effectively no bound.
# 120 leaves headroom over measured 6-12s calls and ~50s provider slowdowns.
# `num_retries` is unset, so this is the total wall-clock bound, not per-attempt.
_REQUEST_TIMEOUT_SECONDS = 120


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
            "timeout": _REQUEST_TIMEOUT_SECONDS,
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
        # Same omission contract for effort; `reasoning_effort` is LiteLLM's
        # unified name, mapped per provider by its transformations.
        if self._config.effort is not None:
            kwargs["reasoning_effort"] = self._config.effort
        # The call AND the response destructuring are wrapped: a provider that
        # returns an empty `choices` raises IndexError here, which is
        # provider-shaped data rather than our bug, and unwrapped it would
        # escape the pipeline's catch and destroy the run. The kwargs assembly
        # above stays outside — a TypeError there is ours and must stay loud.
        try:
            response = litellm.completion(**kwargs)
            content: str | None = response.choices[0].message.content
        except Exception as exc:
            # Name the type only when the message doesn't already carry it:
            # LiteLLM's exceptions self-identify (and nest their own), so an
            # unconditional prefix stutters in the artifact and the UI, while a
            # bare `TimeoutError("...")` would otherwise arrive unattributed.
            detail, name = str(exc), type(exc).__name__
            raise LLMCallError(detail if name in detail else f"{name}: {detail}") from exc
        if content is None:
            raise LLMCallError("LLM returned an empty response.")
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
