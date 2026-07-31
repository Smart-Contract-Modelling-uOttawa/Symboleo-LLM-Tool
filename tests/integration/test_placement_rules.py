"""Pins the JAR-verified placement rules `_output_format.j2` asserts.

These rules are hand-written rather than derived from `Symboleo.xtext`, because
the grammar is not the whole specification: a large share of what the JAR
enforces lives in Java beside it. A date literal is the clearest case — the
grammar accepts any string (``Date returns ecore::EDate: 'Date' '(' STRING ')'``)
while `SymboleoValueConverters` requires ``yyyy/MM/dd HH:mm:ss``, so
``Date("2026-01-31")`` parses and is still rejected
(``test_date_literal_requires_slashes_and_time``). The `@Check` rules — AC
attributes, reserved-word collisions, attribute initialization — are equally
invisible in the grammar. A derived reference would therefore be systematically
incomplete on exactly the rules that stall the correction loop.

The JAR is the oracle, so this file is what keeps the guidance honest: if a JAR
refresh changes what is legal, these tests fail instead of the prompt silently
teaching a falsehood. Most cases are a whole contract differing from ``BASE`` in
one construct; the arity cases use the separate ``_MINIMAL`` template for the
reason given there. Where a rule's legal alternative is not already exercised by
``BASE``, the illegal case is paired with it, so the boundary is pinned from both
sides: ``assert errors(...)`` catches "became legal" and ``== []`` catches
"became illegal".
"""

from pathlib import Path

import pytest

from symboleo_llm_tool.symboleo.wrapper import SymboleoWrapper

JAR_PATH = Path("./lib/symboleo-cli.jar")

# AC-complete and minimal: roles carry name/org/dept and the event a Role-typed
# performer, so a probe never fails for a reason it is not testing.
BASE = """Domain D
  Seller isA Role with name: String, org: String, dept: String;
  Buyer isA Role with name: String, org: String, dept: String;
  Goods isAn Asset with qty: Number, owner: Seller;
  Delivered isAn Event with delDueDate: Date, performer: Seller;
endDomain

Contract C (sellerP: Seller, buyerP: Buyer, effDate: Date, delDays: Number)
Declarations
  seller: Seller with name := sellerP.name, org := sellerP.org, dept := sellerP.dept;
  buyer: Buyer with name := buyerP.name, org := buyerP.org, dept := buyerP.dept;
  goods: Goods with qty := 1, owner := seller;
  delivered: Delivered with delDueDate := Date.add(effDate, delDays, days), performer := seller;
Obligations
  o1: O(seller, buyer, true, {consequent});
{extra}endContract
"""


@pytest.fixture(scope="module")
def wrapper() -> SymboleoWrapper:
    return SymboleoWrapper(jar_path=JAR_PATH)


def contract(consequent: str = "Happens(delivered)", extra: str = "") -> str:
    # str.format drops unknown kwargs silently, so a BASE that lost a slot would
    # return valid BASE for every case — the same false-green `sub()` guards.
    assert "{consequent}" in BASE and "{extra}" in BASE, "BASE lost a format slot"
    return BASE.format(consequent=consequent, extra=extra)


def sub(code: str, old: str, new: str) -> str:
    """Replace ``old`` once, asserting it was there.

    A silent no-op would leave BASE untouched, and BASE is valid — so every
    "this is the legal form" assertion would keep passing while testing
    nothing. The asymmetry matters: the illegal halves would still fail loudly,
    so drift would land exactly on the half that keeps the prompt honest.
    """
    assert old in code, f"code no longer contains {old!r}"
    return code.replace(old, new, 1)


def errors(wrapper: SymboleoWrapper, code: str) -> list[str]:
    return [i.message for i in wrapper.validate(code) if i.is_error]


def test_base_contract_is_valid(wrapper: SymboleoWrapper) -> None:
    # Guards every BASE-derived case: a broken BASE would make the "illegal"
    # assertions pass for the wrong reason. `_MINIMAL`'s baseline is
    # `test_two_parameters_accepted`.
    assert errors(wrapper, contract()) == []


# --- Contract structure -------------------------------------------------------


# Declarations bind literals, not parameters, so removing a parameter leaves no
# dangling reference. Otherwise a relaxed arity rule — the drift this case
# exists to catch — would keep the test green on the resulting scoping errors.
_MINIMAL = """Domain D
  Seller isA Role with name: String, org: String, dept: String;
endDomain

Contract C {params}
Declarations
  seller: Seller with name := "a", org := "b", dept := "c";
Obligations
  o1: O(seller, seller, true, true);
endContract
"""


def minimal(params: str) -> str:
    assert "{params}" in _MINIMAL, "_MINIMAL lost its format slot"
    return _MINIMAL.format(params=params)


@pytest.mark.parametrize("params", ["(sellerP: Seller)", "()"])
def test_fewer_than_two_parameters_rejected(wrapper: SymboleoWrapper, params: str) -> None:
    assert errors(wrapper, minimal(params))


def test_two_parameters_accepted(wrapper: SymboleoWrapper) -> None:
    assert errors(wrapper, minimal("(sellerP: Seller, otherP: Seller)")) == []


def test_obligations_header_required_even_with_only_powers(wrapper: SymboleoWrapper) -> None:
    powers = "Powers\n  p1: P(seller, buyer, true, Terminated(self));\n"
    obligations = "Obligations\n  o1: O(seller, buyer, true, Happens(delivered));\n"

    assert errors(wrapper, sub(contract(), obligations, powers))

    # The form the prompt tells the model to write: the header, kept empty.
    assert errors(wrapper, sub(contract(), obligations, "Obligations\n" + powers)) == []


def test_sections_out_of_order_rejected(wrapper: SymboleoWrapper) -> None:
    constraints = "Constraints\n  not(IsEqual(seller, buyer));\n"
    powers = "Powers\n  p1: P(seller, buyer, true, Terminated(self));\n"
    assert errors(wrapper, contract(extra=constraints + powers))
    assert errors(wrapper, contract(extra=powers + constraints)) == []


def test_declared_section_order_is_accepted(wrapper: SymboleoWrapper) -> None:
    # The order the prompt lists, exercised end to end. ACPolicy is omitted: it
    # needs its own controller/rule scaffolding and models rarely emit it, so
    # its position rests on the grammar's Model rule (a plain sequence, which
    # is reliable for order) rather than on this probe.
    code = sub(
        contract(
            extra="Surviving Obligations\n  o2: O(seller, buyer, true, true);\n"
            "Powers\n  p1: P(seller, buyer, true, Terminated(self));\n"
            "Constraints\n  not(IsEqual(seller, buyer));\n",
        ),
        "Obligations\n  o1:",
        "Preconditions\n  true;\nPostconditions\n  true;\nObligations\n  o1:",
    )
    assert errors(wrapper, code) == []


# --- isA / isAn article rigidity ----------------------------------------------


def test_enumeration_requires_isan(wrapper: SymboleoWrapper) -> None:
    illegal = sub(contract(), "endDomain", "  Quality isA Enumeration(PRIME, AAA);\nendDomain")
    legal = sub(contract(), "endDomain", "  Quality isAn Enumeration(PRIME, AAA);\nendDomain")
    assert errors(wrapper, illegal)
    assert errors(wrapper, legal) == []


def test_base_type_alias_requires_isa(wrapper: SymboleoWrapper) -> None:
    illegal = sub(contract(), "endDomain", "  Amount isAn Number;\nendDomain")
    legal = sub(contract(), "endDomain", "  Amount isA Number;\nendDomain")
    assert errors(wrapper, illegal)
    assert errors(wrapper, legal) == []


# --- Enumeration values -------------------------------------------------------


def with_enum(comparison: str) -> str:
    declared = sub(
        contract(consequent=f"Happens(delivered) and {comparison}"),
        "  Delivered isAn Event with delDueDate: Date, performer: Seller;",
        "  Quality isAn Enumeration(PRIME, AAA);\n"
        "  Delivered isAn Event with delDueDate: Date, q: Quality, performer: Seller;",
    )
    return sub(
        declared,
        "delDueDate := Date.add(effDate, delDays, days), performer",
        "delDueDate := Date.add(effDate, delDays, days), q := Quality(PRIME), performer",
    )


def test_enum_value_must_be_qualified_at_use_sites(wrapper: SymboleoWrapper) -> None:
    assert errors(wrapper, with_enum("delivered.q == PRIME"))
    assert errors(wrapper, with_enum("delivered.q == Quality(PRIME)")) == []


def test_enum_members_must_be_bare_in_the_declaration(wrapper: SymboleoWrapper) -> None:
    # The mirror of the rule above, and the reason the prompt states both: a
    # rule that says only "qualify enum values" gets applied to the declaration,
    # where qualifying is a parse error.
    #
    # The enum is declared but never used, so the declaration is the only thing
    # that can fail. Qualifying members in a *used* enum also breaks its use
    # sites, and those collateral errors would keep this green if the JAR ever
    # accepted the dot form here.
    dotted = "  Quality isAn Enumeration(Quality.PRIME, Quality.AAA);\nendDomain"
    assert errors(wrapper, sub(contract(), "endDomain", dotted))

    bare = sub(contract(), "endDomain", "  Quality isAn Enumeration(PRIME, AAA);\nendDomain")
    assert errors(wrapper, bare) == []


def test_bare_enum_value_rejected_in_a_binding(wrapper: SymboleoWrapper) -> None:
    # `with_enum` binds `q := Quality(PRIME)`, so the legal binding form is
    # covered by the passing case above; this pins the bare form as illegal.
    bare_binding = sub(
        with_enum("delivered.q == Quality(PRIME)"),
        "q := Quality(PRIME)",
        "q := PRIME",
    )
    assert errors(wrapper, bare_binding)


def test_enum_dot_form_rejected_at_a_use_site(wrapper: SymboleoWrapper) -> None:
    # The prompt says the dot form is never legal in any position; the
    # declaration case is above, this is the use case.
    assert errors(wrapper, with_enum("delivered.q == Quality.PRIME"))


# --- Dates --------------------------------------------------------------------


@pytest.mark.parametrize(
    "declaration",
    [
        "  delDue: Date := Date.add(effDate, delDays, days);\n",
        "  delDue := Date.add(effDate, delDays, days);\n",
    ],
)
def test_standalone_value_declaration_rejected(wrapper: SymboleoWrapper, declaration: str) -> None:
    # No base-typed or untyped variables: a date must be an attribute of a
    # domain type. Both forms the prompt calls out are covered.
    code = sub(contract(), "Obligations", declaration + "Obligations")
    assert errors(wrapper, code)


@pytest.mark.parametrize(
    "comparison",
    [
        "delivered.delDueDate == Date.add(effDate, delDays, days)",
        "delivered.delDueDate <= Date.add(effDate, delDays, days)",
        "Happens(delivered) and delivered.delDueDate == Date.add(effDate, delDays, days)",
    ],
)
def test_date_add_rejected_in_comparison(wrapper: SymboleoWrapper, comparison: str) -> None:
    assert errors(wrapper, contract(consequent=comparison))


@pytest.mark.parametrize(
    "consequent",
    [
        "WhappensBefore(delivered, Date.add(effDate, delDays, days))",
        "ShappensBefore(delivered, Date.add(effDate, delDays, days))",
        "HappensAfter(delivered, Date.add(effDate, delDays, days))",
        "HappensWithin(delivered, Interval(effDate, Date.add(effDate, delDays, days)))",
        "WhappensBefore(delivered, delivered.delDueDate)",
    ],
)
def test_date_add_accepted_in_time_point_positions(
    wrapper: SymboleoWrapper, consequent: str
) -> None:
    assert errors(wrapper, contract(consequent=consequent)) == []


@pytest.mark.parametrize(
    "literal",
    [
        'Date("2026-01-31 00:00:00")',  # isolates the slashes requirement
        'Date("2026/01/31")',  # isolates the time requirement
        'Date("2026-01-31")',  # both wrong
    ],
)
def test_date_literal_requires_slashes_and_time(wrapper: SymboleoWrapper, literal: str) -> None:
    assert errors(wrapper, sub(contract(), "Date.add(effDate, delDays, days)", literal))


def test_date_literal_full_format_accepted(wrapper: SymboleoWrapper) -> None:
    code = sub(contract(), "Date.add(effDate, delDays, days)", 'Date("2026/01/31 00:00:00")')
    assert errors(wrapper, code) == []


def test_date_constructor_rejects_an_existing_date_value(wrapper: SymboleoWrapper) -> None:
    # `Date(...)` takes a quoted literal, never wraps a Date you already hold.
    # The failure is maximally opaque (a parse error plus a validator crash),
    # which is why the prompt states the rule rather than leaving it to the loop.
    assert errors(wrapper, sub(contract(), "Date.add(effDate, delDays, days)", "Date(effDate)"))


# --- Obligation vs power consequents ------------------------------------------


@pytest.mark.parametrize("action", ["Suspended", "Resumed", "Terminated", "Triggered"])
def test_state_change_rejected_as_obligation_consequent(
    wrapper: SymboleoWrapper, action: str
) -> None:
    extra = f"  o2: O(seller, buyer, true, {action}(obligations.o1));\n"
    assert errors(wrapper, contract(extra=extra))


@pytest.mark.parametrize("action", ["Suspended", "Resumed", "Terminated", "Triggered"])
def test_state_change_accepted_as_power_consequent(wrapper: SymboleoWrapper, action: str) -> None:
    extra = f"Powers\n  p1: P(seller, buyer, true, {action}(obligations.o1));\n"
    assert errors(wrapper, contract(extra=extra)) == []


def test_norm_reference_requires_its_literal_prefix(wrapper: SymboleoWrapper) -> None:
    # `obligations.` / `powers.` are literal tokens in the grammar, not an
    # optional qualifier on the norm's name.
    powers = "Powers\n  p1: P(seller, buyer, true, {c});\n"
    assert errors(wrapper, contract(extra=powers.format(c="Suspended(o1)")))
    assert errors(wrapper, contract(extra=powers.format(c="Suspended(obligations.o1)"))) == []

    # Same rule for a power referenced from a predicate.
    two = powers.format(c="Suspended(obligations.o1)")
    p2 = "  p2: P(seller, buyer, Happens(Exerted({ref})), Terminated(self));\n"
    assert errors(wrapper, contract(extra=two + p2.format(ref="p1")))
    assert errors(wrapper, contract(extra=two + p2.format(ref="powers.p1"))) == []


def test_bare_assignment_rejected_as_obligation_consequent(wrapper: SymboleoWrapper) -> None:
    assert errors(wrapper, contract(consequent="goods.owner := buyer"))


@pytest.mark.parametrize(
    "consequent",
    [
        "Assign(goods.owner := buyer)",
        "HappensAssign(delivered, goods.qty := 2)",
        "Assign(goods.owner := buyer; goods.qty := 2)",  # several updates: semicolons
    ],
)
def test_wrapped_assignment_accepted_as_obligation_consequent(
    wrapper: SymboleoWrapper, consequent: str
) -> None:
    assert errors(wrapper, contract(consequent=consequent)) == []


def test_multiple_assignments_rejected_with_commas(wrapper: SymboleoWrapper) -> None:
    # Showing only the single-assignment form left the separator to guesswork,
    # and a comma is the natural guess.
    assert errors(wrapper, contract(consequent="Assign(goods.owner := buyer, goods.qty := 2)"))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # domain type attributes
        (
            "Goods isAn Asset with qty: Number, owner: Seller;",
            "Goods isAn Asset with qty: Number; owner: Seller;",
        ),
        # contract parameters
        (
            "Contract C (sellerP: Seller, buyerP: Buyer, effDate: Date, delDays: Number)",
            "Contract C (sellerP: Seller; buyerP: Buyer; effDate: Date; delDays: Number)",
        ),
    ],
)
def test_other_lists_reject_semicolons(wrapper: SymboleoWrapper, old: str, new: str) -> None:
    # The prompt widened the rule to name every comma-separated site, so each
    # one needs a probe; otherwise the widened half is asserted and unchecked.
    assert errors(wrapper, sub(contract(), old, new))


def test_enum_members_reject_semicolons(wrapper: SymboleoWrapper) -> None:
    semis = sub(contract(), "endDomain", "  Quality isAn Enumeration(PRIME; AAA);\nendDomain")
    assert errors(wrapper, semis)


def test_happens_assign_multiple_updates_use_semicolons(wrapper: SymboleoWrapper) -> None:
    # The prompt names HappensAssign alongside Assign for the semicolon rule,
    # but the existing case is single-update only.
    legal = "HappensAssign(delivered, goods.qty := 2; goods.owner := buyer)"
    illegal = "HappensAssign(delivered, goods.qty := 2, goods.owner := buyer)"
    assert errors(wrapper, contract(consequent=legal)) == []
    assert errors(wrapper, contract(consequent=illegal))


def test_declaration_with_list_is_comma_separated(wrapper: SymboleoWrapper) -> None:
    # The other half of the separator rule. Stating `Assign`'s semicolon on its
    # own got it carried into declaration `with` lists, where the grammar wants
    # commas — so both sites are pinned together, as the prompt states them.
    semicolons = sub(
        contract(),
        "goods: Goods with qty := 1, owner := seller;",
        "goods: Goods with qty := 1; owner := seller;",
    )
    assert errors(wrapper, semicolons)
    # Redundant with test_base_contract_is_valid — BASE already uses the comma
    # form — but kept so the contrast is readable in place.
    assert errors(wrapper, contract()) == []


def test_happens_of_obligation_state_is_legal(wrapper: SymboleoWrapper) -> None:
    # Pinned as LEGAL: `Suspended` inside `Happens(...)` is an obligation
    # *event*, a different construct from the power consequent above, so the
    # prompt's "powers alone" rule must not be read as covering it.
    extra = "  o2: O(seller, buyer, Happens(Suspended(obligations.o1)), true);\n"
    assert errors(wrapper, contract(extra=extra)) == []
