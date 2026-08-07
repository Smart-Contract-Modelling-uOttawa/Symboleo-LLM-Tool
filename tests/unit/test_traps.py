"""Fences for the taught-rule detector.

Every case is a minimal pair. The illegal half fences the false negative — a
detector that silently stops matching reports a prompt change as a success,
which is the failure mode this module exists to prevent. The legal half fences
the false positive, since a label that fires on correct code makes every census
row unreadable.

The legal halves are the forms ``_output_format.j2`` prescribes and
``tests/integration/test_placement_rules.py`` pins against the JAR; the pairs
here deliberately mirror those cases so the three instruments describe the same
boundary.
"""

from __future__ import annotations

import pytest

from symboleo_llm_tool.output.traps import scan
from symboleo_llm_tool.prompts.examples import list_example_names, load_example

# (label, illegal form, legal form)
PAIRS = [
    (
        "reserved_type_name",
        "Controller isA Role with name: String;",
        "ControllerRole isA Role with name: String;",
    ),
    (
        "reserved_type_name",
        "Suspended isAn Event with performer: Seller;",
        "SuspensionEvent isAn Event with performer: Seller;",
    ),
    (
        "reserved_type_name",
        "Suspension isAn Event with performer: Seller;",
        "PauseEvent isAn Event with performer: Seller;",
    ),
    (
        "base_type_reference",
        "Delivered isAn Event with performer: Role;",
        "Delivered isAn Event with performer: Seller;",
    ),
    (
        "alias_with_attributes",
        "Amount isA Number with value: Number;",
        "Amount isA Number;",
    ),
    (
        "wholesale_assignment",
        "Declarations\n  dueDate: Delivered := someDelivery;\nObligations\n",
        "Declarations\n  delivered: Delivered with dueDate := effDate;\nObligations\n",
    ),
    (
        "base_type_declaration",
        "Declarations\n  fee: Number := 5;\nObligations\n",
        "Declarations\n  goods: Goods with fee := 5;\nObligations\n",
    ),
    (
        # The two shapes that froze the Atos gpt arm and that the wholesale
        # pattern does not match: `with` intervenes before the `:=`.
        "base_type_declaration",
        'Declarations\n  note: String with := "";\nObligations\n',
        'Declarations\n  goods: Goods with note := "";\nObligations\n',
    ),
    (
        "base_type_declaration",
        'Declarations\n  note: String with note := "";\nObligations\n',
        'Declarations\n  goods: Goods with note := "", qty := 1;\nObligations\n',
    ),
    (
        "date_literal_in_predicate",
        'WhappensBefore(delivered, Date("2026/01/31 00:00:00"))',
        "WhappensBefore(delivered, Date.add(effDate, delDays, days))",
    ),
    (
        "type_applied_to_instance",
        "Happens(Delivered(delivered))",
        "Happens(delivered)",
    ),
    (
        # The case that caught the hand-listed version: `Exerted` is a power
        # event, legal inside Happens(...), and absent from an eyeballed list of
        # "state words". It ships in transactive_energy, so a corpus example was
        # being reported as a rule violation.
        "type_applied_to_instance",
        "Happens(PenaltyImposed(imposed))",
        "Happens(Exerted(powers.imposePenalty))",
    ),
    (
        "state_change_in_obligation",
        "o1: O(seller, buyer, true, Suspended(obligations.o2));",
        "p1: P(seller, buyer, true, Suspended(obligations.o2));",
    ),
    (
        # Nested two deep in the antecedent. A bounded-nesting regex matches the
        # flat case above and misses this one, which is the shape real output
        # takes — so the flat pair alone would fence nothing.
        "state_change_in_obligation",
        "o1: O(seller, buyer, Happens(Violated(obligations.o3)), Terminated(obligations.o2));",
        "o1: O(seller, buyer, Happens(Violated(obligations.o3)), Happens(delivered));",
    ),
    (
        "unprefixed_norm_reference",
        "p1: P(seller, buyer, true, Suspended(deliverGoods));",
        "p1: P(seller, buyer, true, Suspended(obligations.deliverGoods));",
    ),
    (
        "dotted_enum_member",
        "goods.grade == CargoGrade.PREMIUM",
        "goods.grade == CargoGrade(PREMIUM)",
    ),
    (
        "non_state_power_consequent",
        "p1: P(seller, buyer, true, Assign(goods.qty := 2));",
        "p1: P(seller, buyer, true, Terminated(self));",
    ),
    (
        "non_state_power_consequent",
        "p1: P(seller, buyer, true, Happens(delivered));",
        "p1: P(seller, buyer, Happens(delivered), Terminated(self));",
    ),
]


@pytest.mark.parametrize(
    ("label", "illegal", "legal"), PAIRS, ids=[f"{p[0]}-{i}" for i, p in enumerate(PAIRS)]
)
def test_minimal_pair(label: str, illegal: str, legal: str) -> None:
    assert label in scan(illegal)
    assert label not in scan(legal)


# Labels decided in `scan` rather than by a `_PATTERNS` entry, because each needs
# a derived word list to consult, or balanced-paren parsing, rather than a fixed
# regex.
DERIVED_LABELS = {
    "type_applied_to_instance",
    "reserved_type_name",
    "non_state_power_consequent",
    "state_change_in_obligation",
}


def test_every_label_has_a_pair() -> None:
    """A rule with no pair is a rule the census cannot see.

    Imported rather than hand-listed so adding a label to ``_PATTERNS`` without
    a case here reds immediately, which is the only moment the omission is
    cheap to notice.
    """
    from symboleo_llm_tool.output.traps import _DECLARATION_PATTERNS, _PATTERNS

    labels = {label for label, _ in _PATTERNS + _DECLARATION_PATTERNS} | DERIVED_LABELS
    assert labels == {label for label, _, _ in PAIRS}


def test_declaration_rules_do_not_fire_outside_declarations() -> None:
    """The same text is legal as a parameter and as a domain attribute.

    Both are routinely wrapped onto their own line in real output, so a
    whole-text pattern reports a correct contract as broken — and this label
    exists to measure a failure that is already the dominant one.
    """
    legal = (
        "Contract C (\n  sellerP: Seller,\n  delDays: Number)\n"
        "Declarations\n  goods: Goods with qty := 1;\nObligations\n"
    )
    assert scan(legal) == []
    attributes = (
        "Domain D\n  Goods isAn Asset with\n    qty: Number,\n    note: String;\nendDomain\n"
    )
    assert scan(attributes) == []


def test_clean_code_scans_clean() -> None:
    assert scan("Domain D\n  Seller isA Role with name: String;\nendDomain\n") == []


def test_truncated_power_clause_is_not_a_violation() -> None:
    # A truncated response is the validator's finding, not a rule violation;
    # reporting one here would blame the model for the wrong thing.
    assert "non_state_power_consequent" not in scan("p1: P(seller, buyer, true, Termi")


@pytest.mark.parametrize("name", list_example_names())
def test_shipped_examples_scan_clean(name: str) -> None:
    """No taught rule may fire on the few-shot corpus.

    Sound as a fence, not merely convenient: every taught rule describes a form
    the JAR rejects, and each example is JAR-validated by
    ``tests/integration/test_example_corpus.py`` — so any label firing here is a
    false positive by construction.
    """
    assert scan(load_example(name)["symboleo_code"]) == []
