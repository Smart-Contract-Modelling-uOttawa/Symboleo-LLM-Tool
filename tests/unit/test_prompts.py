from pathlib import Path

import pytest

from symboleo_llm_tool.prompts.base import PromptStrategy
from symboleo_llm_tool.prompts.context import PromptContext
from symboleo_llm_tool.prompts.strategies.cot import CoTStrategy
from symboleo_llm_tool.prompts.strategies.few_shot import FewShotStrategy
from symboleo_llm_tool.prompts.strategies.zero_shot import ZeroShotStrategy
from tests.helpers import make_issue

_EXAMPLE_CONTENT = (
    "contract_text: 'Buyer shall pay $100.'\nsymboleo_code: 'Contract Example(...) ...'\n"
)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the example corpus at a tmp dir holding one example named 'sale'.

    Overriding via the env var rather than patching a module attribute keeps the
    test on the same resolution path a deployment uses.
    """
    (tmp_path / "sale.yaml").write_text(_EXAMPLE_CONTENT, encoding="utf-8")
    monkeypatch.setenv("SYMBOLEO_EXAMPLES_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture(params=["zero_shot", "few_shot", "cot"])
def any_strategy(request: pytest.FixtureRequest, corpus: Path) -> PromptStrategy:
    if request.param == "zero_shot":
        return ZeroShotStrategy({})
    if request.param == "few_shot":
        return FewShotStrategy({"example_files": ["sale"]})
    return CoTStrategy({})


@pytest.fixture
def few_shot(corpus: Path) -> FewShotStrategy:
    return FewShotStrategy({"example_files": ["sale"]})


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


def test_correction_grammar_included_when_provided(any_strategy: PromptStrategy) -> None:
    # The grammar tests above cover generation only; a correction template that
    # lost its include would ship silently.
    ctx = PromptContext(current_code="code", errors=[], grammar_context="grammar rules here")
    assert "grammar rules here" in any_strategy.build_correction_prompt(ctx)


def test_correction_grammar_omitted_when_none(any_strategy: PromptStrategy) -> None:
    ctx = PromptContext(current_code="code", errors=[], grammar_context=None)
    assert "Grammar Reference" not in any_strategy.build_correction_prompt(ctx)


def test_generation_includes_output_format(any_strategy: PromptStrategy) -> None:
    ctx = PromptContext(contract_text="contract text", grammar_context=None)
    assert "## Output Format" in any_strategy.build_generation_prompt(ctx)


def test_correction_includes_output_format(any_strategy: PromptStrategy) -> None:
    # Correction carries the same structural grounding as generation; without it
    # the model over-edits lines that have no listed error (see CLAUDE.md).
    ctx = PromptContext(current_code="some symboleo code", errors=[], grammar_context=None)
    assert "## Output Format" in any_strategy.build_correction_prompt(ctx)


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


def test_unknown_strategy_param_rejected(any_strategy: PromptStrategy) -> None:
    # strategy_params is a free-form dict, so the config models' extra="forbid"
    # cannot reach into it -- the strategy is the only place a typo can surface.
    with pytest.raises(ValueError, match="exmaple_files"):
        type(any_strategy)({"exmaple_files": ["x"]})


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


def test_few_shot_missing_example_raises(corpus: Path) -> None:
    with pytest.raises(ValueError, match="'nonexistent' not found"):
        FewShotStrategy({"example_files": ["nonexistent"]})


def test_few_shot_malformed_example_raises(corpus: Path) -> None:
    (corpus / "bad.yaml").write_text("wrong_key: value\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must have"):
        FewShotStrategy({"example_files": ["bad"]})


def test_few_shot_rejects_a_path_shaped_entry(corpus: Path) -> None:
    # A path-shaped entry names a file that exists, so a bare "not found" would
    # read as a typo. The message has to name the contract instead.
    with pytest.raises(ValueError, match="names, not paths"):
        FewShotStrategy({"example_files": [str(corpus / "sale.yaml")]})


# --- CoT specific ---


def test_cot_generation_includes_step_instructions(cot: CoTStrategy) -> None:
    # Both assertions quote the ## Workflow block, which is what makes this
    # strategy CoT — text shared with the other strategies would not.
    ctx = PromptContext(contract_text="contract text", grammar_context=None)
    prompt = cot.build_generation_prompt(ctx)
    assert "Identify all parties" in prompt
    assert "Map every element to the correct SymboleoAC construct." in prompt


def test_cot_correction_includes_reasoning_workflow(cot: CoTStrategy) -> None:
    # Anchored on the ## Workflow steps, not the word "reason" — that also appears
    # in the constraint telling the model *not* to emit its reasoning, so the old
    # assertion held even with the whole workflow deleted.
    ctx = PromptContext(
        current_code="code",
        errors=[make_issue(line=5, column=3, message="missing ';'")],
        grammar_context=None,
    )
    prompt = cot.build_correction_prompt(ctx)
    assert "## Workflow" in prompt
    assert "Apply the minimal fix that resolves the error." in prompt
