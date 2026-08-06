"""Fences for the richness counters in ``output/richness.py``.

Oracles are hand-derived from the quoted snippets and the fixture file, never
from the implementation's output. The fixture case pins both keyword
alternations (``O``/``Obligation``, ``P``/``Power``) and comment stripping at
once: ``valid.symboleo`` is 89 raw lines (64 code + 15 comment-only + 10
blank) and contains two commented-out Obligation clauses, so an implementation
that skips stripping reads 6 obligations and 79 non-blank lines instead of 4
and 64 (the blank filter is independent of stripping).
"""

from pathlib import Path

from symboleo_llm_tool.output.richness import measure

FIXTURE = Path("tests/fixtures/valid.symboleo")


def test_fixture_counts_mixed_short_and_long_forms() -> None:
    counts = measure(FIXTURE.read_text(encoding="utf-8"))
    assert counts.loc == 64
    assert (counts.obligations, counts.surviving_obligations, counts.powers) == (4, 0, 3)


def test_commented_out_clauses_do_not_count() -> None:
    assert measure("// x: O(a, b, true, true);").obligations == 0


def test_block_comments_and_string_literals_do_not_count() -> None:
    counts = measure('/* O( */\ncondition := "O(";')
    assert counts.obligations == 0


def test_block_comment_opener_inside_line_comment_does_not_swallow_code() -> None:
    code = "// note /* dangling\nob: O(a, b, true, true); // end */\n"
    assert measure(code).obligations == 1


def test_line_comment_marker_inside_block_comment_does_not_swallow_code() -> None:
    code = "x := 1; /* a // b */ ob: O(a, b, true, true);\n"
    assert measure(code).obligations == 1


def test_string_masking_does_not_splice_a_clause_match() -> None:
    assert measure('O "x" (y)').obligations == 0


def test_section_headers_alone_count_nothing() -> None:
    counts = measure("Obligations\nSurviving Obligations\nPowers")
    assert (counts.obligations, counts.surviving_obligations, counts.powers) == (0, 0, 0)


def test_surviving_obligations_split() -> None:
    code = (
        "Obligations\n"
        "  a: O(x, y, true, Happens(e));\n"
        "Surviving Obligations\n"
        "  b: O(x, y, true, Happens(f));\n"
    )
    counts = measure(code)
    assert (counts.obligations, counts.surviving_obligations, counts.powers) == (1, 1, 0)


def test_fulfilled_obligations_event_is_not_an_obligation() -> None:
    code = "pw: Happens(FulfilledObligations(self)) -> P(a, b, true, Terminated(self));"
    assert measure(code).obligations == 0


def test_power_consequents_and_states_are_not_norms() -> None:
    code = "Suspended(obligations.a);\nTerminated(self);\nOccurs(Suspension(obligations.a), i);\n"
    counts = measure(code)
    assert (counts.obligations, counts.surviving_obligations, counts.powers) == (0, 0, 0)


def test_trigger_form_counts_once() -> None:
    assert measure("x: Happens(e) -> O(a, b, true, true);").obligations == 1


def test_loc_excludes_blank_and_comment_only_lines_keeps_trailing_comments() -> None:
    code = "\n// alone\ncode; // trailing\n"
    assert measure(code).loc == 1
