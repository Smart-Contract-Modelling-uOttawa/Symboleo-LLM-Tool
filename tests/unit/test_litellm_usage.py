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
from symboleo_llm_tool.llm.base import LLMCallError
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
        # LLMCallError specifically, not any RuntimeError: the pipeline catches
        # that type to record a failed candidate, so a widening here would let
        # this escape and destroy the run.
        with pytest.raises(LLMCallError, match="empty response"):
            _adapter().generate("prompt")


def test_provider_exception_is_wrapped_in_llm_call_error() -> None:
    # Provider knowledge stays in the adapter layer: the pipeline never imports
    # litellm or openai, so anything the SDK raises has to arrive as LLMCallError
    # or it will not be recognised as recoverable.
    original = TimeoutError("Connection timed out after 120.0 seconds")
    with patch("litellm.completion", side_effect=original):
        with pytest.raises(LLMCallError) as exc_info:
            _adapter().generate("prompt")

    assert "TimeoutError" in str(exc_info.value)
    assert exc_info.value.__cause__ is original


def test_a_self_identifying_provider_error_is_not_double_prefixed() -> None:
    # LiteLLM's exceptions name their own type (and nest it again), so an
    # unconditional prefix produced "AuthenticationError: litellm.Authentication
    # Error: AuthenticationError: ..." in report.json and the UI. Observed
    # 2026-08-06 against a deliberately invalid key.
    class AuthenticationError(Exception):
        pass

    original = AuthenticationError("litellm.AuthenticationError: bad key")
    with patch("litellm.completion", side_effect=original):
        with pytest.raises(LLMCallError) as exc_info:
            _adapter().generate("prompt")

    assert str(exc_info.value) == "litellm.AuthenticationError: bad key"
    assert str(exc_info.value).count("AuthenticationError") == 1


def test_a_response_with_no_choices_is_wrapped() -> None:
    # Cohere's observed NO_VALID_RESPONSE_GENERATED shape. The destructuring is
    # inside the try because this is provider-shaped data, not our bug — left
    # outside, the IndexError escapes the pipeline's catch and destroys the run,
    # which is the exact failure mode LLMCallError exists to prevent.
    empty = SimpleNamespace(choices=[], usage=None)
    with (
        patch("litellm.completion", return_value=empty),
        patch("litellm.completion_cost", return_value=0.0),
    ):
        with pytest.raises(LLMCallError, match="IndexError"):
            _adapter().generate("prompt")


def test_a_bug_in_kwargs_assembly_is_not_wrapped() -> None:
    # The try begins at the provider interaction. A failure building the request
    # is our bug and must stay loud rather than be recorded as a provider fault.
    adapter = _adapter()
    with patch.object(type(adapter._config), "litellm_model", property(_raise_bug)):
        with pytest.raises(AttributeError):
            adapter.generate("prompt")


def _raise_bug(_self: Any) -> str:
    raise AttributeError("bug in our own code")


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


def test_effort_omitted_when_unset() -> None:
    # Same only-send-when-set contract as temperature: an effort nobody
    # configured must not reach the provider (non-reasoning models would have
    # it silently dropped, reasoning models would get an unchosen depth).
    with (
        patch("litellm.completion", return_value=_response()) as mock_completion,
        patch("litellm.completion_cost", return_value=0.0),
    ):
        _adapter().generate("prompt")

    assert "reasoning_effort" not in mock_completion.call_args.kwargs


def test_effort_sent_as_reasoning_effort_when_configured() -> None:
    # The config field is `effort`; the wire name is LiteLLM's unified
    # `reasoning_effort`, which its transformations map per provider.
    adapter = LiteLLMAdapter(
        LLMConfig(provider="anthropic", model="claude-opus-4-8", effort="xhigh")
    )
    with (
        patch("litellm.completion", return_value=_response()) as mock_completion,
        patch("litellm.completion_cost", return_value=0.0),
    ):
        adapter.generate("prompt")

    assert mock_completion.call_args.kwargs["reasoning_effort"] == "xhigh"


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
