"""Reserved-name extraction from the bundled Symboleo grammar.

The list is derived, never hand-maintained: a name that stops or starts being
reserved must follow the grammar file automatically, because a stale hand list
fails silently and in exactly the way the feature exists to prevent (an
unrecoverable 1-ERROR plateau, see CLAUDE.md).
"""

import re

from symboleo_llm_tool.prompts.grammar import load_grammar, reserved_names

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def test_load_grammar_returns_the_grammar_text() -> None:
    assert load_grammar().startswith("grammar ca.uottawa.csmlab.symboleo.Symboleo")


def test_load_grammar_is_cached() -> None:
    # The module docstring promises both functions are cached; only asserting it
    # for reserved_names would leave the 13 KB re-read unfenced.
    assert load_grammar() is load_grammar()


def test_reserved_names_includes_ontology_types() -> None:
    assert {"Asset", "Event", "Role", "Contract", "DataTransfer"} <= set(reserved_names())


def test_reserved_names_includes_words_the_model_must_still_emit() -> None:
    # The premise that forces the prompt wording to be about invented names
    # rather than forbidden words: these are reserved AND mandatory syntax, so a
    # blanket prohibition would make the contract unparseable. If extraction ever
    # stops picking them up, that wording becomes stylistic instead of load-bearing.
    assert {"Domain", "endDomain", "isA", "Contract", "Happens"} <= set(reserved_names())


def test_reserved_names_includes_state_literals() -> None:
    assert {
        "Suspension",
        "Active",
        "InEffect",
        "Violation",
        "Fulfillment",
        "Rescission",
        "Discharge",
        "Create",
    } <= set(reserved_names())


def test_reserved_names_covers_both_quote_styles() -> None:
    # The highest-value assertion here. The grammar mixes quote styles:
    # "Asset" is double-quoted (OntologyType), 'Suspension' single-quoted
    # (PowerStateName). A single-style regex passes every other test in this
    # file while silently dropping the whole base-type category — which is one
    # of the two collisions actually observed against real models.
    names = set(reserved_names())
    assert "Asset" in names
    assert "Suspension" in names


def test_reserved_names_excludes_non_identifier_literals() -> None:
    # A name cannot be punctuation or a dotted call, so listing those would be
    # tokens spent on entries that can never collide.
    assert all(_IDENTIFIER.fullmatch(n) for n in reserved_names())
    for noise in ("(", ":=", "->", "Date.add", "Math.pow", "obligations."):
        assert noise not in reserved_names()


def test_reserved_names_excludes_grammar_rule_names() -> None:
    # Catches an extraction that grabbed capitalised words rather than quoted
    # literals: rule names appear left of ':' and are never reserved tokens.
    names = set(reserved_names())
    assert "PowerStateName" not in names
    assert "OntologyType" not in names


def test_reserved_names_are_sorted_and_unique() -> None:
    # Load-bearing, not cosmetic: the prompt is a research artifact and must be
    # byte-reproducible across processes, which set iteration order would not be.
    assert list(reserved_names()) == sorted(set(reserved_names()))


def test_reserved_names_nonempty_and_bounded() -> None:
    # Canary for an extraction that matched nothing or swallowed the file. The
    # exact count is deliberately NOT asserted: it would red CI on every
    # legitimate grammar refresh, defeating the zero-drift property.
    assert 50 < len(reserved_names()) < 200


def test_reserved_names_is_cached() -> None:
    assert reserved_names() is reserved_names()
