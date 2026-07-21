"""Token/cost extraction in LiteLLMAdapter.

Live completion calls stay untested (see CLAUDE.md), but usage extraction is
pure given a response object, so it is covered here with a fake response and a
patched ``litellm`` — no network or API key required.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from symboleo_llm_tool.config.models import LLMConfig
from symboleo_llm_tool.llm.litellm_adapter import LiteLLMAdapter


def _adapter() -> LiteLLMAdapter:
    return LiteLLMAdapter(LLMConfig(provider="openai", model="gpt-4o-mini"))


def _response(content: str = "Contract C() {}", *, usage: Any = None) -> SimpleNamespace:
    # No total_tokens — TokenUsage computes it from prompt + completion.
    if usage is None:
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=usage,
    )


def test_captures_tokens_and_cost() -> None:
    with (
        patch("litellm.completion", return_value=_response()),
        patch("litellm.completion_cost", return_value=0.0123),
    ):
        result = _adapter().generate("prompt")

    assert result.generated_text == "Contract C() {}"
    assert result.usage.prompt_tokens == 100
    assert result.usage.completion_tokens == 20
    assert result.usage.total_tokens == 120
    assert result.usage.cost_usd == 0.0123


def test_cost_failure_yields_none_but_keeps_tokens() -> None:
    with (
        patch("litellm.completion", return_value=_response()),
        patch("litellm.completion_cost", side_effect=Exception("no pricing for model")),
    ):
        result = _adapter().generate("prompt")

    assert result.usage.cost_usd is None
    assert result.usage.total_tokens == 120


def test_temperature_omitted_when_unset() -> None:
    # The load-bearing guard against reasoning-model 400s: a temperature that was
    # never configured must not reach the provider (see CLAUDE.md).
    with (
        patch("litellm.completion", return_value=_response()) as mock_completion,
        patch("litellm.completion_cost", return_value=0.0),
    ):
        _adapter().generate("prompt")

    assert "temperature" not in mock_completion.call_args.kwargs


def test_temperature_sent_when_configured() -> None:
    adapter = LiteLLMAdapter(LLMConfig(provider="openai", model="gpt-4o-mini", temperature=0.2))
    with (
        patch("litellm.completion", return_value=_response()) as mock_completion,
        patch("litellm.completion_cost", return_value=0.0),
    ):
        adapter.generate("prompt")

    assert mock_completion.call_args.kwargs["temperature"] == 0.2


def test_missing_usage_yields_zeros() -> None:
    with (
        patch("litellm.completion", return_value=_response(usage=SimpleNamespace())),
        patch("litellm.completion_cost", return_value=0.0),
    ):
        result = _adapter().generate("prompt")

    assert result.usage.prompt_tokens == 0
    assert result.usage.completion_tokens == 0
    assert result.usage.total_tokens == 0
