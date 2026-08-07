"""Pins the JAR-verified rules the prompt guidance asserts: the placement
rules in `_output_format.j2`, and the reserved-name boundaries in
`_reserved_names.j2` (the state words, and the access-control keyword
`Controller`).

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
        # The `with` forms. Models reach for these once the `:=` form is
        # refused, and the earlier version of this case pinned only the two
        # above — the same blind spot the bullet had, so the fence agreed with
        # the prompt instead of checking it. All four base types, since the
        # bullet now generalises across them rather than naming Date.
        "  fee: Number;\n",
        "  fee: Number with := 5;\n",
        "  fee: Number with fee := 5;\n",
        '  note: String with note := "";\n',
        "  flag: Boolean with flag := false;\n",
        '  due: Date with due := Date("2026/01/31 00:00:00");\n',
    ],
)
def test_standalone_value_declaration_rejected(wrapper: SymboleoWrapper, declaration: str) -> None:
    # No base-typed or untyped variables: the value must be an attribute of a
    # domain type, or a contract parameter.
    code = sub(contract(), "Obligations", declaration + "Obligations")
    assert errors(wrapper, code)


def test_a_value_that_belongs_to_no_instance_is_a_contract_parameter(
    wrapper: SymboleoWrapper,
) -> None:
    # The legal home the bullet now names, and the half that makes the rule
    # actionable: without it the prompt refuses every form a model can write
    # and offers nothing in their place. `delDays: Number` in BASE already
    # proves base-typed parameters parse; this pins that a proposition may use
    # one directly, with no declaration standing between.
    code = sub(
        sub(
            contract(consequent="goods.qty == lateFee"),
            "delDays: Number)",
            "delDays: Number, lateFee: Number)",
        ),
        "",
        "",
    )
    assert errors(wrapper, code) == []


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


# --- Reserved names (## Reserved Names) ---------------------------------------


def test_state_word_as_event_type_name_fails_opaquely(wrapper: SymboleoWrapper) -> None:
    # `Suspended isAn Event` cannot parse - the participle is a grammar keyword
    # - and the message never says the name is the problem, which is
    # why `_reserved_names.j2` prevents rather than relying on recovery.
    code = sub(contract(), "Delivered isAn Event", "Suspended isAn Event")
    code = sub(code, "delivered: Delivered with", "delivered: Suspended with")
    msgs = errors(wrapper, code)
    assert msgs
    assert any("mismatched input 'Suspended'" in m for m in msgs)


def test_suffixed_state_word_event_name_is_legal(wrapper: SymboleoWrapper) -> None:
    # The escape the guidance prescribes: `SuspensionEvent isAn Event`.
    code = sub(contract(), "Delivered isAn Event", "SuspensionEvent isAn Event")
    code = sub(code, "delivered: Delivered with", "delivered: SuspensionEvent with")
    assert errors(wrapper, code) == []


def test_controller_as_role_type_name_fails_opaquely(wrapper: SymboleoWrapper) -> None:
    # The AC keyword as a Role type name — the natural vocabulary of a
    # data-processing contract (GDPR Controller/Processor). Froze three
    # candidates for all five corrections on 2026-08-06; like the state words,
    # the parse error quotes the token but never says the name is the problem.
    code = sub(contract(), "Buyer isA Role", "Controller isA Role")
    code = sub(code, "buyerP: Buyer,", "buyerP: Controller,")
    code = sub(code, "buyer: Buyer with", "buyer: Controller with")
    msgs = errors(wrapper, code)
    assert msgs
    assert any("'Controller'" in m for m in msgs)


def test_suffixed_controller_role_name_is_legal(wrapper: SymboleoWrapper) -> None:
    # The escape the guidance prescribes: `ControllerRole isA Role`.
    code = sub(contract(), "Buyer isA Role", "ControllerRole isA Role")
    code = sub(code, "buyerP: Buyer,", "buyerP: ControllerRole,")
    code = sub(code, "buyer: Buyer with", "buyer: ControllerRole with")
    assert errors(wrapper, code) == []


# --- Type references and declaration form -------------------------------------

# Every word of `OntologyType` (Symboleo.xtext), so the prompt's list cannot
# drift from the grammar's: a word added upstream fails here as an unpinned
# legal form, and one dropped from the prompt fails as an untaught trap.
ONTOLOGY_WORDS = ["Role", "Asset", "Event", "Contract", "DataTransfer"]


@pytest.mark.parametrize("word", ONTOLOGY_WORDS)
def test_base_type_as_attribute_type_fails(wrapper: SymboleoWrapper, word: str) -> None:
    # An ontology base word as an attribute type — `performer: Role` froze 2/3
    # Cohere baseline runs for all 5 corrections. These words are legal only to
    # the right of isA/isAn (the legal side is BASE itself). Primitive-typed
    # attributes like `qty: Number` stay legal; the rule is these words only.
    assert errors(wrapper, sub(contract(), "performer: Seller;", f"performer: {word};"))


@pytest.mark.parametrize("word", ONTOLOGY_WORDS)
def test_base_type_as_parameter_type_fails(wrapper: SymboleoWrapper, word: str) -> None:
    # The same words in a contract-parameter type position, the shape both CoT
    # candidates wrote. `effDate: Date` in BASE pins that primitive-typed
    # parameters remain legal.
    assert errors(wrapper, sub(contract(), "sellerP: Seller,", f"sellerP: {word},"))


def test_wholesale_declaration_assignment_fails(wrapper: SymboleoWrapper) -> None:
    # `decl: Type := value` — written by 3/3 Cohere baseline runs and frozen to
    # the end (`mismatched input ':=' expecting ';'`); the with-list is the
    # only way values enter a declaration.
    assert errors(
        wrapper,
        sub(
            contract(),
            "goods: Goods with qty := 1, owner := seller;",
            "goods: Goods := sellerP;",
        ),
    )


def test_date_literal_in_predicate_time_position_fails(wrapper: SymboleoWrapper) -> None:
    # The asymmetry the 2026-08-06 battery found: Date.add is legal in this
    # exact position (test_date_add_accepted_in_time_point_positions), a
    # literal is not — it stalled 3 of 9 Atos candidates that day.
    assert errors(
        wrapper,
        contract(consequent='WhappensBefore(delivered, Date("2026/10/01 00:00:00"))'),
    )


def test_date_literal_in_declaration_binding_is_legal(wrapper: SymboleoWrapper) -> None:
    # The literal's one legal home, and the form the amended bullet prescribes.
    code = sub(contract(), "Date.add(effDate, delDays, days)", 'Date("2026/10/01 00:00:00")')
    assert errors(wrapper, code) == []


# --- Power consequents and base-type aliases (2026-08-07 sweep) ---------------

# The legal side of the power-consequent boundary — P(..., Terminated(self)) —
# is already pinned by test_state_word_applied_to_norm_stays_legal's fixture.


def test_assign_in_power_consequent_fails(wrapper: SymboleoWrapper) -> None:
    # Both models over-applied the O-side Assign teaching here in the
    # cross-contract sweep and froze on the opaque message. The Power rule's
    # consequent is PowerFunction, which admits only the state-change forms.
    power = "Powers\n  p1: P(buyer, seller, true, Assign(goods.qty := 2));\n"
    msgs = errors(wrapper, contract(extra=power))
    assert msgs
    assert any("no viable alternative at input 'Assign'" in m for m in msgs)


def test_happens_in_power_consequent_fails(wrapper: SymboleoWrapper) -> None:
    # The other over-application observed: an awaited event as a P consequent.
    power = "Powers\n  p1: P(buyer, seller, true, Happens(delivered));\n"
    assert errors(wrapper, contract(extra=power))


def test_proposition_in_power_consequent_fails(wrapper: SymboleoWrapper) -> None:
    # A full proposition fares no better than a lone predicate.
    power = "Powers\n  p1: P(buyer, seller, true, Happens(delivered) and goods.qty == 1);\n"
    assert errors(wrapper, contract(extra=power))


def test_alias_with_attributes_fails(wrapper: SymboleoWrapper) -> None:
    # `Quantity isA Number with amount: Number` froze a Vaccine run for all
    # five corrections; an alias renames a base type and takes no with-list.
    code = sub(
        contract(),
        "Goods isAn Asset",
        "Amount isA Number with x: Number;\n  Goods isAn Asset",
    )
    msgs = errors(wrapper, code)
    assert msgs
    assert any("mismatched input 'with'" in m for m in msgs)


def test_bare_alias_is_legal(wrapper: SymboleoWrapper) -> None:
    # The form the bullet prescribes, pinned so the pair brackets the boundary.
    code = sub(contract(), "Goods isAn Asset", "Amount isA Number;\n  Goods isAn Asset")
    assert errors(wrapper, code) == []


# --- Predicate arguments and the AC attribute requirements --------------------


def test_event_type_applied_to_instance_in_predicate_fails(wrapper: SymboleoWrapper) -> None:
    # `Happens(Delivered(delivered))` — the type applied to its own instance,
    # as if a constructor. Opaque (`no viable alternative at input '('`) and it
    # arrives in bulk: 12 instances in one 2026-08-06 candidate, frozen to the
    # iteration cap. The legal form is BASE's bare `Happens(delivered)`.
    msgs = errors(wrapper, contract(consequent="Happens(Delivered(delivered))"))
    assert msgs
    assert any("no viable alternative at input '('" in m for m in msgs)


def test_bare_event_type_in_predicate_fails(wrapper: SymboleoWrapper) -> None:
    # The other half of instance-vs-type confusion, which the bullet names
    # alongside the parenthesised form. Its message is actionable where the
    # other's is opaque, and that asymmetry is what this pins: if the JAR ever
    # made this one opaque too, the bullet would be under-warning about it.
    msgs = errors(wrapper, contract(consequent="Happens(Delivered)"))
    assert msgs
    assert any("cannot be used as an event here" in m for m in msgs)


def test_state_word_applied_to_norm_stays_legal(wrapper: SymboleoWrapper) -> None:
    # The norm form the bullet offers as the alternative to naming an instance
    # (`Happens(Violated(obligations.<name>))`), in a *consequent* alongside a
    # power — `test_happens_of_obligation_state_is_legal` pins the antecedent
    # position with a different state word. If this became illegal the bullet
    # would be prescribing an unparseable form.
    power = "Powers\n  p1: P(buyer, seller, true, Terminated(self));\n"
    code = contract(consequent="not Happens(Violated(obligations.o1))", extra=power)
    assert errors(wrapper, code) == []


def test_event_without_performer_fails(wrapper: SymboleoWrapper) -> None:
    # The entry point of the worst 2026-08-06 trap chain: omitting `performer`
    # yields a message reading "must declare a Role-typed 'performer'", the
    # model writes the literal `performer: Role`, and that parse error masks
    # the file. Prevention at generation is why the AC bullet exists despite
    # the message itself being actionable.
    code = sub(
        contract(),
        "Delivered isAn Event with delDueDate: Date, performer: Seller;",
        "Delivered isAn Event with delDueDate: Date;",
    )
    msgs = errors(wrapper, code)
    assert any("Role-typed 'performer'" in m for m in msgs)


def test_role_without_ac_attributes_fails(wrapper: SymboleoWrapper) -> None:
    # The other half of the same bullet: the access-control triple.
    code = sub(
        contract(),
        "Buyer isA Role with name: String, org: String, dept: String;",
        "Buyer isA Role with name: String;",
    )
    msgs = errors(wrapper, code)
    assert any("access-control attribute" in m for m in msgs)
