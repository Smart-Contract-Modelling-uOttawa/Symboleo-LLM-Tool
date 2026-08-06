import re
from importlib import resources
from pathlib import Path

import pytest

from symboleo_llm_tool.prompts import grammar
from symboleo_llm_tool.prompts.base import PromptStrategy, build_jinja_env
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


# Names that reach the prompt ONLY through `reserved_names()`. `Asset` and
# `Suspension` — the tokens models actually collided on — are unusable here:
# both appear as static prose in _reserved_names.j2 (and `Asset` in
# _output_format.j2), so asserting them passes even when the derived list is
# empty, leaving the whole feature unfenced.
_DERIVED_ONLY = ("`DataTransfer`", "`thirdParty`", "`UnsuccessfulTermination`")


def test_generation_includes_reserved_names(any_strategy: PromptStrategy) -> None:
    ctx = PromptContext(contract_text="contract text", grammar_context="grammar rules here")
    prompt = any_strategy.build_generation_prompt(ctx)
    assert "## Reserved Names" in prompt
    for name in _DERIVED_ONLY:
        assert name in prompt


def test_correction_includes_reserved_names(any_strategy: PromptStrategy) -> None:
    ctx = PromptContext(
        current_code="some symboleo code",
        errors=[make_issue(message="bad token")],
        grammar_context="grammar rules here",
    )
    prompt = any_strategy.build_correction_prompt(ctx)
    assert "## Reserved Names" in prompt
    for name in _DERIVED_ONLY:
        assert name in prompt


def test_reserved_names_rule_targets_invented_names_only(any_strategy: PromptStrategy) -> None:
    # The list contains words the model MUST still emit (Domain, endDomain, isA,
    # Contract, Happens), so a blanket "never use these" would instruct it to
    # write an unparseable contract — a worse failure than the collision this
    # module exists to prevent. Both stages carry the wording.
    gen = any_strategy.build_generation_prompt(PromptContext(contract_text="contract text"))
    corr = any_strategy.build_correction_prompt(
        PromptContext(current_code="some symboleo code", errors=[make_issue(message="bad token")])
    )
    for prompt in (gen, corr):
        assert "required, not forbidden" in prompt
        assert "names you **invent**" in prompt


def test_grammar_failure_defers_to_render_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # build_jinja_env runs at strategy-module import, so registering the
    # reserved_names function rather than its value keeps an unreadable grammar
    # resource out of import: it must not break `--help` or API startup, and
    # must surface as the friendly RuntimeError when a prompt is actually built.
    def unreadable() -> str:
        raise RuntimeError("Failed to load Symboleo grammar resource")

    monkeypatch.setattr(grammar, "load_grammar", unreadable)
    grammar.reserved_names.cache_clear()  # both are lru_cached and warm by now
    try:
        env = build_jinja_env("zero_shot_generation.j2")
        template = env.get_template("zero_shot_generation.j2")
        with pytest.raises(RuntimeError, match="Failed to load Symboleo grammar resource"):
            template.render(contract_text="contract text", grammar_context=None)
    finally:
        grammar.reserved_names.cache_clear()  # drop the poisoned state for later tests


def test_reserved_names_survive_grammar_omission(any_strategy: PromptStrategy) -> None:
    # Reserved names are a property of the language, not of whether the grammar
    # text is injected — and with the grammar omitted the model knows less, so
    # the collision is likelier. This fails the moment someone folds the module
    # into _grammar_section.j2, which is gated on grammar_context.
    gen_ctx = PromptContext(contract_text="contract text", grammar_context=None)
    corr_ctx = PromptContext(
        current_code="some symboleo code",
        errors=[make_issue(message="bad token")],
        grammar_context=None,
    )
    for prompt in (
        any_strategy.build_generation_prompt(gen_ctx),
        any_strategy.build_correction_prompt(corr_ctx),
    ):
        assert "Grammar Reference" not in prompt
        assert "## Reserved Names" in prompt


def test_state_word_event_guidance_reaches_both_stages(any_strategy: PromptStrategy) -> None:
    # The observed collision family is the past-participle event-naming idiom
    # landing on the reserved state words. Both stages emit contract code, so
    # the trap guidance must reach both — and each phrase must be unique, or a
    # deleted sentence would stay satisfied by an accidental echo elsewhere.
    # Two sentinels because the sentence has two load-bearing halves: the
    # prohibition, and the suffixed-escape prescription the corrections use.
    gen = any_strategy.build_generation_prompt(PromptContext(contract_text="contract text"))
    corr = any_strategy.build_correction_prompt(
        PromptContext(current_code="some symboleo code", errors=[make_issue(message="bad token")])
    )
    for prompt in (gen, corr):
        assert prompt.count("never the bare state word") == 1
        assert prompt.count("Use a suffixed name") == 1


def test_controller_guidance_reaches_both_stages(any_strategy: PromptStrategy) -> None:
    # The AC keyword `Controller` is a DPA-shaped contract's natural vocabulary
    # (GDPR Controller/Processor), and unlike the state words its collision
    # froze uncorrected for 5 iterations in every 2026-08-06 occurrence — the
    # generic list + rename permission did not trigger the rename; naming the
    # word with a prescribed escape is the mechanism that did for state words.
    gen = any_strategy.build_generation_prompt(PromptContext(contract_text="contract text"))
    corr = any_strategy.build_correction_prompt(
        PromptContext(current_code="some symboleo code", errors=[make_issue(message="bad token")])
    )
    for prompt in (gen, corr):
        assert prompt.count("never bare `Controller`") == 1


def test_state_word_guidance_names_only_reserved_words() -> None:
    # The guidance hand-enumerates the state-word family for emphasis — the
    # pointer at the derived list demonstrably failed, with models colliding on
    # words that list already contained. Hand-listing can drift from the
    # grammar, so pin both directions: every named word must still be reserved
    # (a JAR/grammar refresh that unreserves one is named here), and the family
    # must stay fully enumerated — deduplicated, with the prescribed `*Event`
    # escapes excluded, so a trimmed paragraph cannot hide behind the closing
    # "not `Suspension`, not `Suspended`" repeats.
    template = (
        resources.files("symboleo_llm_tool.prompts.templates")
        .joinpath("_reserved_names.j2")
        .read_text(encoding="utf-8")
    )
    reserved = grammar.reserved_names()
    named = re.findall(r"`(\w+)`", template.split("The state words collide most")[1])
    family = {w for w in named if w not in ("Conveyed", "Paid") and not w.endswith("Event")}
    assert len(family) >= 15, f"family enumeration shrank: {sorted(family)}"
    for word in family:
        assert word in reserved, f"guidance names {word!r} but the grammar does not reserve it"


def test_correction_permits_reserved_identifier_rename(any_strategy: PromptStrategy) -> None:
    # Correction's first constraint forbids editing lines with no listed error;
    # a rename cascades across exactly such lines, so the permission must be
    # explicit there — and must not leak into generation, which has no code to
    # preserve.
    corr_ctx = PromptContext(
        current_code="some symboleo code",
        errors=[make_issue(message="bad token")],
    )
    gen_ctx = PromptContext(contract_text="contract text")
    assert "required fix, not an unlisted edit" in any_strategy.build_correction_prompt(corr_ctx)
    assert "required fix, not an unlisted edit" not in any_strategy.build_generation_prompt(gen_ctx)


# --- Placement rules (## Output Format) ---------------------------------------

# One phrase per JAR-pinned placement rule in _output_format.j2, so dropping a
# pinned rule reds this test instead of passing on the others. The older
# structural bullets (the top-level-structure skeleton, O-vs-Obligation, inline
# propositions, the trigger prefix) carry no phrase by design — see the Jinja
# comment in that template.
#
# Each phrase must be unique in the RENDERED prompt, not merely in the template:
# `## Reserved Names` lists every grammar keyword, so a bare construct name is
# already present there and would fence nothing. Same trap as _DERIVED_ONLY
# above, in mirror image; test_placement_rule_phrases_are_unique_in_the_prompt
# enforces it.
_PLACEMENT_RULES = (
    "may only appear in this order",  # fixed section sequence
    "header with nothing under it",  # Obligations header mandatory
    "at least two parameters",  # contract needs >= 2 params
    "The article is fixed",  # isAn Enumeration / isA <base type>
    "there does not parse",  # enum members are bare AT the declaration
    "qualifies it with the type name",  # Quality(PRIME) at every use site
    "never legal in any position",  # the Type.MEMBER dot form, anywhere
    "there are no standalone values",  # no `x: Date := ...` / `x := ...`
    "only date-arithmetic construct",  # Date.add form + no infix `d + N days`
    "expects a time point",  # where Date.add IS allowed
    "may NOT appear in a comparison",  # where it is not
    "the time is required",  # Date("yyyy/MM/dd HH:mm:ss")
    "never wraps a value you already have",  # Date(effDate) is not a wrapper
    "required literal prefix",  # Suspended(obligations.x), not Suspended(x)
    "belong to powers alone",  # Suspended/Resumed/... not in O
    "wraps the assignment",  # Assign(...) / HappensAssign(...) in an O
    "exactly two places in the whole language",  # where semicolons ARE used
    "Every other list is comma-separated",  # and where they are not
    "never the base word itself",  # performer: Role / param: Role do not parse
    "one attribute at a time",  # no wholesale `decl: Type := value`
    "only in a declaration binding",  # a Date literal not in predicate positions
)


def test_output_format_rule_count_is_capped() -> None:
    # `## Output Format` ships on every call in both stages regardless of
    # include_grammar, so it is the section that can quietly re-inject grammar
    # knowledge into the `include_grammar: false` arm until the two arms stop
    # differing. The ceiling is a bullet count rather than a token budget
    # because the section's size is stable but its share of a prompt is not —
    # that varies with strategy, grammar, and contract length. Reaching the cap
    # means the next fix is few-shot or upstream message enrichment, not
    # another bullet (CLAUDE.md, "Leaf-construct policy").
    template = (
        resources.files("symboleo_llm_tool.prompts.templates")
        .joinpath("_output_format.j2")
        .read_text(encoding="utf-8")
    )
    bullets = [ln for ln in template.splitlines() if ln.startswith("- ")]
    assert len(bullets) <= 15, f"## Output Format has {len(bullets)} bullets; cap is 15"


# --- Example vocabulary (## Output Format) -------------------------------------

# The worked examples come from a fictional domain that is no benchmark
# contract's domain. The invariant is GENERALITY, not zero overlap: the bias
# being prevented operates through answer-key fragments — multi-token,
# solution-specific identifiers a model can copy wholesale into one
# benchmark's solution (the retired MeatSale examples carried literal lines
# of sample_contract's answer) — while sharing an ordinary English word with
# a contract's prose leaks nothing. So only the distinctive tokens are fenced
# against the corpus; the generic ones are checked for template presence only.
# The partial ships in every strategy regardless of config, which is why this
# matters at all: few-shot leakage is at least configurable, this is not.
_DISTINCTIVE_EXAMPLE_TOKENS = (
    "CargoGrade",
    "MIDGRADE",
    "unitTally",
    "expectedBy",
    "beginDate",
    "windowDays",
    "conveyCargo",
)
_GENERIC_EXAMPLE_TOKENS = (
    "PREMIUM",
    "BULK",
    "cargo",
    "grade",
    "tally",
    "holder",
    "recipient",
    "Conveyed",
    "conveyed",
)

# MeatSale's identifier ensemble. Some are ordinary words on their own, but
# each is an identifier in the default benchmark's gold solution, so any one
# reappearing in a template signals MeatSale-flavored editing drifting back in.
_RETIRED_MEATSALE_TOKENS = (
    "MeatQuality",
    "PRIME",
    "CHOICE",
    "delDueDateDays",
    "delDueDate",
    "effDate",
    "qnt",
    "deliverGoods",
    "goods",
    "buyer",
    "Delivered",
    "delivered",
)

_CORPUS_FILES = (
    *sorted(Path("contracts").glob("*.txt")),
    *sorted(Path("examples").glob("*.yaml")),
    *sorted(Path("tests/fixtures").glob("*.txt")),
)


def _template_files() -> list:
    return [
        entry
        for entry in resources.files("symboleo_llm_tool.prompts.templates").iterdir()
        if entry.name.endswith(".j2")
    ]


def test_example_vocabulary_is_present_in_output_format() -> None:
    # Freshness guard for the overlap test below: a token that no longer
    # appears in the template is stale in these lists, and the overlap test
    # would keep "passing" for vocabulary the examples no longer use.
    template = (
        resources.files("symboleo_llm_tool.prompts.templates")
        .joinpath("_output_format.j2")
        .read_text(encoding="utf-8")
    )
    for token in _DISTINCTIVE_EXAMPLE_TOKENS + _GENERIC_EXAMPLE_TOKENS:
        assert re.search(rf"\b{token}\b", template), f"{token!r} not in _output_format.j2"


def test_distinctive_example_tokens_do_not_overlap_the_corpus() -> None:
    # A corpus file containing `expectedBy` or `conveyCargo` is borrowing, not
    # prose — it happened once (equipment_loan absorbed `dueBy`/`startDate`
    # from the original de-bias plan), so this reds at introduction time while
    # a rename is still cheap on either side. Deliberately NOT applied to the
    # generic tokens: a contract whose prose says "recipient" or "grade" is
    # routine English and leaks nothing.
    assert len(_CORPUS_FILES) >= 3, "corpus glob found nothing — wrong CWD?"
    for path in _CORPUS_FILES:
        text = path.read_text(encoding="utf-8")
        for token in _DISTINCTIVE_EXAMPLE_TOKENS:
            assert not re.search(rf"\b{token}\b", text, re.IGNORECASE), (
                f"distinctive example token {token!r} appears in {path} — rename one side"
            )


def test_retired_meatsale_vocabulary_stays_out_of_templates() -> None:
    # sample_contract.txt IS MeatSale, so any of these tokens reappearing in a
    # template re-biases every strategy toward that one benchmark contract.
    for entry in _template_files():
        text = entry.read_text(encoding="utf-8")
        for token in _RETIRED_MEATSALE_TOKENS:
            assert not re.search(rf"\b{token}\b", text), f"{token!r} back in {entry.name}"


def test_placement_rule_phrases_are_unique_in_the_prompt(
    any_strategy: PromptStrategy,
) -> None:
    # The fence above only works if each phrase appears exactly once: a phrase
    # occurring elsewhere in the prompt stays satisfied after its rule is
    # deleted, fencing nothing.
    prompt = any_strategy.build_generation_prompt(
        PromptContext(contract_text="contract text", grammar_context="grammar rules here")
    )
    for rule in _PLACEMENT_RULES:
        assert prompt.count(rule) == 1, f"{rule!r} is not unique in the rendered prompt"


def test_placement_rules_reach_both_stages(any_strategy: PromptStrategy) -> None:
    # Both stages emit contract code, so a rule shipping in only one of them
    # would leave half the loop unguided.
    gen_ctx = PromptContext(contract_text="contract text", grammar_context="grammar rules here")
    corr_ctx = PromptContext(
        current_code="some symboleo code",
        errors=[make_issue(message="bad token")],
        grammar_context="grammar rules here",
    )
    for prompt in (
        any_strategy.build_generation_prompt(gen_ctx),
        any_strategy.build_correction_prompt(corr_ctx),
    ):
        for rule in _PLACEMENT_RULES:
            assert rule in prompt


def test_placement_rules_survive_grammar_omission(any_strategy: PromptStrategy) -> None:
    # These substitute for grammar knowledge, so the arm that omits the grammar
    # text needs them most. Fails if someone gates the module on grammar_context
    # to reclaim the tokens (see CLAUDE.md, "Grammar Context Size").
    prompt = any_strategy.build_generation_prompt(
        PromptContext(contract_text="contract text", grammar_context=None)
    )
    assert "Grammar Reference" not in prompt
    for rule in _PLACEMENT_RULES:
        assert rule in prompt


def test_date_invention_guidance_is_generation_only(any_strategy: PromptStrategy) -> None:
    # Not inventing values is placeholder-mapping guidance, not a placement
    # rule: the JAR cannot tell an invented date from a stated one, so it lives
    # with the other constraints rather than in the probe-pinned section.
    gen = any_strategy.build_generation_prompt(PromptContext(contract_text="contract text"))
    corr = any_strategy.build_correction_prompt(
        PromptContext(current_code="some symboleo code", errors=[make_issue(message="bad token")])
    )
    assert "never write a calendar date" in gen
    assert "never write a calendar date" not in corr


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


def test_few_shot_correction_includes_examples(few_shot: FewShotStrategy) -> None:
    # Without this, few_shot correction silently renders the zero_shot prompt —
    # a "few-shot" stage with no shots. The strategy's name is the contract.
    ctx = PromptContext(current_code="Domain D endDomain", errors=[make_issue()])
    prompt = few_shot.build_correction_prompt(ctx)
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
