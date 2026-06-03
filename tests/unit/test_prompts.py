from pathlib import Path

import pytest

from symboleo_llm_tool.prompts.base import PromptStrategy
from symboleo_llm_tool.prompts.context import PromptContext
from symboleo_llm_tool.prompts.strategies.cot import CoTStrategy
from symboleo_llm_tool.prompts.strategies.few_shot import FewShotStrategy
from symboleo_llm_tool.prompts.strategies.zero_shot import ZeroShotStrategy
from tests.helpers import make_issue

_EXAMPLE_CONTENT = (
    "contract_text: 'Buyer shall pay $100.'\n"
    "symboleo_code: 'Contract Example(...) ...'\n"
)


@pytest.fixture(params=["zero_shot", "few_shot", "cot"])
def any_strategy(request: pytest.FixtureRequest, tmp_path: Path) -> PromptStrategy:
    if request.param == "zero_shot":
        return ZeroShotStrategy({})
    if request.param == "few_shot":
        example_file = tmp_path / "example.yaml"
        example_file.write_text(_EXAMPLE_CONTENT, encoding="utf-8")
        return FewShotStrategy({"example_files": [str(example_file)]})
    return CoTStrategy({})


@pytest.fixture
def few_shot(tmp_path: Path) -> FewShotStrategy:
    example_file = tmp_path / "example.yaml"
    example_file.write_text(_EXAMPLE_CONTENT, encoding="utf-8")
    return FewShotStrategy({"example_files": [str(example_file)]})


@pytest.fixture
def cot() -> CoTStrategy:
    return CoTStrategy({})


# --- Shared contract (all strategies must pass) ---

def test_grammar_included_when_provided(any_strategy: PromptStrategy) -> None:
    ctx = PromptContext(contract_text="contract text", grammar_context="grammar rules here")
    assert "grammar rules here" in any_strategy.build_generation_prompt(ctx)


def test_grammar_omitted_when_none(any_strategy: PromptStrategy) -> None:
    ctx = PromptContext(contract_text="contract text", grammar_context=None)
    assert "Grammar Reference" not in any_strategy.build_generation_prompt(ctx)


def test_generation_includes_contract_text(any_strategy: PromptStrategy) -> None:
    ctx = PromptContext(contract_text="Seller shall deliver goods.", grammar_context=None)
    assert "Seller shall deliver goods." in any_strategy.build_generation_prompt(ctx)


def test_correction_includes_current_code(any_strategy: PromptStrategy) -> None:
    ctx = PromptContext(current_code="some symboleo code", errors=[], grammar_context=None)
    assert "some symboleo code" in any_strategy.build_correction_prompt(ctx)


def test_correction_includes_error_details(any_strategy: PromptStrategy) -> None:
    ctx = PromptContext(
        current_code="code",
        errors=[make_issue(line=5, column=3, message="missing ';'")],
        grammar_context=None,
    )
    prompt = any_strategy.build_correction_prompt(ctx)
    assert "missing ';'" in prompt
    assert "5" in prompt
    assert "3" in prompt


# --- Few-shot specific ---

def test_few_shot_generation_includes_examples(few_shot: FewShotStrategy) -> None:
    ctx = PromptContext(contract_text="New contract.", grammar_context=None)
    prompt = few_shot.build_generation_prompt(ctx)
    assert "Buyer shall pay $100." in prompt
    assert "Contract Example" in prompt


def test_few_shot_empty_example_files_raises() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        FewShotStrategy({})


def test_few_shot_invalid_example_files_param_raises() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        FewShotStrategy({"example_files": "not a list"})


def test_few_shot_missing_example_file_raises() -> None:
    with pytest.raises(ValueError, match="not found"):
        FewShotStrategy({"example_files": ["./nonexistent.yaml"]})


def test_few_shot_malformed_example_file_raises(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("wrong_key: value\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must have"):
        FewShotStrategy({"example_files": [str(bad_file)]})


# --- CoT specific ---

def test_cot_generation_includes_step_instructions(cot: CoTStrategy) -> None:
    ctx = PromptContext(contract_text="contract text", grammar_context=None)
    prompt = cot.build_generation_prompt(ctx)
    assert "Identify all parties" in prompt
    assert "obligation" in prompt


def test_cot_correction_includes_reasoning_instruction(cot: CoTStrategy) -> None:
    ctx = PromptContext(
        current_code="code",
        errors=[make_issue(line=5, column=3, message="missing ';'")],
        grammar_context=None,
    )
    assert "reason" in cot.build_correction_prompt(ctx).lower()
