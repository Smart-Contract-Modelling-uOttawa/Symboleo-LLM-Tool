import pytest

from symboleo_llm_tool.prompts.context import PromptContext
from symboleo_llm_tool.prompts.strategies.zero_shot import ZeroShotStrategy
from symboleo_llm_tool.symboleo.models import SymboleoIssue


@pytest.fixture
def strategy() -> ZeroShotStrategy:
    return ZeroShotStrategy({})


def test_generation_prompt_includes_contract_text(strategy: ZeroShotStrategy) -> None:
    ctx = PromptContext(
        contract_text="Seller shall deliver goods.", grammar_context=None
    )
    prompt = strategy.build_generation_prompt(ctx)
    assert "Seller shall deliver goods." in prompt


def test_generation_prompt_includes_grammar_when_provided(
    strategy: ZeroShotStrategy,
) -> None:
    ctx = PromptContext(
        contract_text="contract text", grammar_context="grammar rules here"
    )
    prompt = strategy.build_generation_prompt(ctx)
    assert "grammar rules here" in prompt


def test_generation_prompt_omits_grammar_section_when_none(
    strategy: ZeroShotStrategy,
) -> None:
    ctx = PromptContext(contract_text="contract text", grammar_context=None)
    prompt = strategy.build_generation_prompt(ctx)
    assert "Grammar Reference" not in prompt


def test_correction_prompt_includes_current_code(strategy: ZeroShotStrategy) -> None:
    ctx = PromptContext(
        current_code="some symboleo code", errors=[], grammar_context=None
    )
    prompt = strategy.build_correction_prompt(ctx)
    assert "some symboleo code" in prompt


def test_correction_prompt_includes_error_details(strategy: ZeroShotStrategy) -> None:
    error = SymboleoIssue(
        severity="ERROR",
        code=None,
        offset=0,
        line=5,
        column=3,
        length=1,
        message="missing ';'",
    )
    ctx = PromptContext(current_code="code", errors=[error], grammar_context=None)
    prompt = strategy.build_correction_prompt(ctx)
    assert "missing ';'" in prompt
    assert "5" in prompt
    assert "3" in prompt


def test_correction_prompt_omits_grammar_section_when_none(
    strategy: ZeroShotStrategy,
) -> None:
    ctx = PromptContext(current_code="code", errors=[], grammar_context=None)
    prompt = strategy.build_correction_prompt(ctx)
    assert "Grammar Reference" not in prompt
