"""Token/cost extraction in LiteLLMAdapter.

Live completion calls stay untested (see CLAUDE.md), but usage extraction is
pure given a response object, so it is covered here with a fake response and a
patched ``litellm`` — no network or API key required.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from symboleo_llm_tool.config.models import LLMConfig
from symboleo_llm_tool.llm.litellm_adapter import _REQUEST_TIMEOUT_SECONDS, LiteLLMAdapter


def _adapter() -> LiteLLMAdapter:
    return LiteLLMAdapter(LLMConfig(provider="openai", model="gpt-4o-mini"))


def _response(content: str | None = "Contract C() {}", *, usage: Any = None) -> SimpleNamespace:
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


def test_empty_content_raises_rather_than_returning_none() -> None:
    # A reasoning model can return only a thinking block; the pipeline would then
    # try to validate None as Symboleo code.
    with (
        patch("litellm.completion", return_value=_response(content=None)),
        patch("litellm.completion_cost", return_value=0.0),
    ):
        with pytest.raises(RuntimeError, match="empty response"):
            _adapter().generate("prompt")


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


def test_request_timeout_is_always_sent() -> None:
    # Two asserts, two different properties: the equality pins that the module
    # constant is what actually reaches the provider, and the range pins that
    # the constant is a real bound — without it, retuning to LiteLLM's
    # effectively-unbounded 6000 default would still pass. Retuning to another
    # sane value is deliberately allowed, so neither assert hardcodes 120.
    with (
        patch("litellm.completion", return_value=_response()) as mock_completion,
        patch("litellm.completion_cost", return_value=0.0),
    ):
        _adapter().generate("prompt")

    timeout = mock_completion.call_args.kwargs["timeout"]
    assert timeout == _REQUEST_TIMEOUT_SECONDS
    assert 0 < timeout < 600


def test_missing_usage_yields_zeros() -> None:
    with (
        patch("litellm.completion", return_value=_response(usage=SimpleNamespace())),
        patch("litellm.completion_cost", return_value=0.0),
    ):
        result = _adapter().generate("prompt")

    assert result.usage.prompt_tokens == 0
    assert result.usage.completion_tokens == 0
    assert result.usage.total_tokens == 0
