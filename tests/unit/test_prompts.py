import pytest

from symboleo_llm_tool.prompts.context import PromptContext
from symboleo_llm_tool.prompts.strategies.cot import CoTStrategy
from symboleo_llm_tool.prompts.strategies.few_shot import FewShotStrategy
from symboleo_llm_tool.prompts.strategies.zero_shot import ZeroShotStrategy
from symboleo_llm_tool.symboleo.models import SymboleoIssue


@pytest.fixture
def zero_shot() -> ZeroShotStrategy:
    return ZeroShotStrategy({})


@pytest.fixture
def few_shot() -> FewShotStrategy:
    return FewShotStrategy({
        "examples": [
            {
                "contract_text": "Buyer shall pay $100.",
                "symboleo_code": "Contract Example(...) ...",
            }
        ]
    })


@pytest.fixture
def cot() -> CoTStrategy:
    return CoTStrategy({})


def _make_error() -> SymboleoIssue:
    return SymboleoIssue(
        severity="ERROR", code=None, offset=0, line=5, column=3, length=1,
        message="missing ';'",
    )


# --- Zero-shot ---

def test_zero_shot_generation_includes_contract_text(zero_shot: ZeroShotStrategy) -> None:
    ctx = PromptContext(contract_text="Seller shall deliver goods.", grammar_context=None)
    assert "Seller shall deliver goods." in zero_shot.build_generation_prompt(ctx)


def test_zero_shot_generation_includes_grammar_when_provided(zero_shot: ZeroShotStrategy) -> None:
    ctx = PromptContext(contract_text="contract text", grammar_context="grammar rules here")
    assert "grammar rules here" in zero_shot.build_generation_prompt(ctx)


def test_zero_shot_generation_omits_grammar_when_none(zero_shot: ZeroShotStrategy) -> None:
    ctx = PromptContext(contract_text="contract text", grammar_context=None)
    assert "Grammar Reference" not in zero_shot.build_generation_prompt(ctx)


def test_zero_shot_correction_includes_current_code(zero_shot: ZeroShotStrategy) -> None:
    ctx = PromptContext(current_code="some symboleo code", errors=[], grammar_context=None)
    assert "some symboleo code" in zero_shot.build_correction_prompt(ctx)


def test_zero_shot_correction_includes_error_details(zero_shot: ZeroShotStrategy) -> None:
    ctx = PromptContext(current_code="code", errors=[_make_error()], grammar_context=None)
    prompt = zero_shot.build_correction_prompt(ctx)
    assert "missing ';'" in prompt
    assert "5" in prompt
    assert "3" in prompt


def test_zero_shot_correction_omits_grammar_when_none(zero_shot: ZeroShotStrategy) -> None:
    ctx = PromptContext(current_code="code", errors=[], grammar_context=None)
    assert "Grammar Reference" not in zero_shot.build_correction_prompt(ctx)


# --- Few-shot ---

def test_few_shot_generation_includes_examples(few_shot: FewShotStrategy) -> None:
    ctx = PromptContext(contract_text="New contract.", grammar_context=None)
    prompt = few_shot.build_generation_prompt(ctx)
    assert "Buyer shall pay $100." in prompt
    assert "Contract Example" in prompt


def test_few_shot_generation_includes_contract_text(few_shot: FewShotStrategy) -> None:
    ctx = PromptContext(contract_text="New contract.", grammar_context=None)
    assert "New contract." in few_shot.build_generation_prompt(ctx)


def test_few_shot_generation_without_examples_still_works() -> None:
    strategy = FewShotStrategy({})
    ctx = PromptContext(contract_text="contract text", grammar_context=None)
    prompt = strategy.build_generation_prompt(ctx)
    assert "contract text" in prompt
    assert "Example" not in prompt


def test_few_shot_invalid_examples_param_raises() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        FewShotStrategy({"examples": "not a list"})


def test_few_shot_correction_includes_current_code(few_shot: FewShotStrategy) -> None:
    ctx = PromptContext(current_code="some symboleo code", errors=[], grammar_context=None)
    assert "some symboleo code" in few_shot.build_correction_prompt(ctx)


# --- CoT ---

def test_cot_generation_includes_contract_text(cot: CoTStrategy) -> None:
    ctx = PromptContext(contract_text="Seller shall deliver goods.", grammar_context=None)
    assert "Seller shall deliver goods." in cot.build_generation_prompt(ctx)


def test_cot_generation_includes_step_instructions(cot: CoTStrategy) -> None:
    ctx = PromptContext(contract_text="contract text", grammar_context=None)
    prompt = cot.build_generation_prompt(ctx)
    assert "Identify all parties" in prompt
    assert "obligation" in prompt


def test_cot_correction_includes_reasoning_instruction(cot: CoTStrategy) -> None:
    ctx = PromptContext(current_code="code", errors=[_make_error()], grammar_context=None)
    prompt = cot.build_correction_prompt(ctx)
    assert "reason" in prompt.lower()
    assert "missing ';'" in prompt
