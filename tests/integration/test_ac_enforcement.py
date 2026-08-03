"""Pins the access-control `@Check` rules the JAR must enforce.

Distinct from `test_placement_rules.py`, which fences the *prompt*: every case
there corresponds to a bullet in `_output_format.j2`. Nothing here does. These
cases fence the *validator* — they assert that a JAR sitting in `lib/` still
rejects contracts the access-control layer is supposed to reject, whatever the
prompt happens to say.

The gap this closes is specific, and it has already bitten once. An AC check
that goes missing makes the validator *more permissive*, and permissiveness is
invisible to every other test in this suite: `valid.symboleo` still validates
clean, `invalid.symboleo` still fails on its `endContrct` typo, and the
placement rules still hold. The suite gets greener, not redder. The jar built
2026-05-20 shipped the AC grammar (`ACPolicy`, `Grant`/`Revoke` all parsed) with
only one AC `@Check` behind it, so it silently accepted events declaring no
`performer` and roles missing the `name`/`org`/`dept` triple.

So the load-bearing direction here is `assert errors(...)` — it catches "this
became legal again". Legal counterparts are pinned with `== []` where BASE does
not already exercise them, so a JAR that over-tightens fails too rather than
silently narrowing what the tool can generate.
"""

from pathlib import Path

import pytest

from symboleo_llm_tool.symboleo.wrapper import SymboleoWrapper

JAR_PATH = Path("./lib/symboleo-cli.jar")

# Mirrors `test_placement_rules.BASE` plus the ACPolicy section that file omits.
# `seller` owns `goods`, so the rule's granting role has evident authority over
# the resource and `checkPermissionGiver` stays quiet. That note is INFO
# severity and `errors()` keeps only ERRORs, so it could not change an outcome
# either way; BASE models an uncontested grant because that is the shape the
# prompt teaches, not to keep the assertions clean.
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
  o1: O(seller, buyer, true, Happens(delivered));
ACPolicy with Controller seller
  Rule1: Grant read To buyer On goods.qty by seller;
endContract
"""


@pytest.fixture(scope="module")
def wrapper() -> SymboleoWrapper:
    return SymboleoWrapper(jar_path=JAR_PATH)


def sub(code: str, old: str, new: str) -> str:
    """Replace ``old`` once, asserting it was there.

    Same guard as `test_placement_rules.sub`, and it matters more here: a silent
    no-op returns BASE, BASE is valid, and the ``assert errors(...)`` half —
    which is the half this file exists for — would then fail loudly rather than
    pass. That is the safe direction, but the assertion makes the cause obvious
    instead of presenting as a validator regression.
    """
    assert old in code, f"code no longer contains {old!r}"
    return code.replace(old, new, 1)


def errors(wrapper: SymboleoWrapper, code: str) -> list[str]:
    return [i.message for i in wrapper.validate(code) if i.is_error]


def test_base_contract_is_valid(wrapper: SymboleoWrapper) -> None:
    # Guards every case below: a broken BASE would satisfy the "illegal"
    # assertions for the wrong reason.
    assert errors(wrapper, BASE) == []


# --- ACPolicy controller ------------------------------------------------------


def test_acpolicy_requires_a_controller_clause(wrapper: SymboleoWrapper) -> None:
    # `with Controller` is grammar-mandatory inside ACPolicy, so its absence is a
    # syntax error rather than a `@Check`. Pinned anyway: "lack of a controller"
    # has two readings and both must stay fatal.
    assert errors(wrapper, sub(BASE, "ACPolicy with Controller seller", "ACPolicy"))


def test_acpolicy_controller_must_be_role_typed(wrapper: SymboleoWrapper) -> None:
    # `checkControllerType` — the method upstream's no-ACPolicy NPE fix modified,
    # so this is the case most exposed to that guard being scoped too widely.
    # `goods` is an Asset: a declared variable, resolvable, simply not a Role.
    assert errors(wrapper, sub(BASE, "with Controller seller", "with Controller goods"))


def test_acpolicy_accepts_several_role_controllers(wrapper: SymboleoWrapper) -> None:
    # The legal counterpart BASE does not reach: the grammar's comma-separated
    # controller list. Pins that the type check applies per entry without the
    # list form itself becoming illegal.
    code = sub(BASE, "with Controller seller", "with Controller seller, buyer")
    assert errors(wrapper, code) == []


def test_acpolicy_rejects_a_non_role_among_several_controllers(wrapper: SymboleoWrapper) -> None:
    # A per-entry check that only inspected the first controller would pass the
    # case above and this one would catch it.
    assert errors(wrapper, sub(BASE, "with Controller seller", "with Controller seller, goods"))


# --- Rule participants --------------------------------------------------------


def test_rule_granting_role_must_be_role_typed(wrapper: SymboleoWrapper) -> None:
    # `checkAccessedRoleAndControllerInRule`, the "By ..." half.
    assert errors(wrapper, sub(BASE, "by seller;", "by goods;"))


def test_rule_accessed_role_must_be_role_typed(wrapper: SymboleoWrapper) -> None:
    # The "To ..." half. Both are one `@Check`, so they are pinned separately —
    # a regression that dropped only one branch would otherwise stay hidden.
    assert errors(wrapper, sub(BASE, "To buyer On", "To goods On"))


# --- Role access-control triple -----------------------------------------------


def role_type(attributes: str) -> str:
    """Inject a role type that is never instantiated.

    Dropping an attribute from `Seller` instead would break the `Declarations`
    entry that binds it, and those cascading "couldn't resolve reference" errors
    would keep the test green even if the AC-triple check disappeared entirely.
    An unreferenced type can only fail for the reason under test.
    """
    return sub(BASE, "endDomain", f"  Auditor isA Role with {attributes};\nendDomain")


@pytest.mark.parametrize(
    "attributes",
    [
        "name: String",  # org, dept missing
        "name: String, org: String",  # dept missing
        "name: String, dept: String",  # org missing
        "org: String, dept: String",  # name missing
    ],
)
def test_role_missing_any_ac_attribute_rejected(wrapper: SymboleoWrapper, attributes: str) -> None:
    # One case per omission: the generated `authenticate()` matches on all three,
    # so a check that only looked for, say, `name` would wave three of these
    # through.
    assert errors(wrapper, role_type(attributes))


def test_role_with_the_full_triple_accepted(wrapper: SymboleoWrapper) -> None:
    assert errors(wrapper, role_type("name: String, org: String, dept: String")) == []


# --- Event performer ----------------------------------------------------------


def event_type(body: str) -> str:
    """Inject an event type that is never instantiated (see `role_type`)."""
    return sub(BASE, "endDomain", f"  Inspected isAn Event{body};\nendDomain")


def test_event_type_without_a_performer_rejected(wrapper: SymboleoWrapper) -> None:
    # `performer` is a base-language requirement for event authenticity, not an
    # AC addition, but it is enforced by the same validator.
    assert errors(wrapper, event_type(""))


def test_event_performer_must_be_role_typed(wrapper: SymboleoWrapper) -> None:
    # Distinct from the case above: the attribute is present, its type is wrong.
    assert errors(wrapper, event_type(" with performer: Goods"))


def test_event_with_a_role_typed_performer_accepted(wrapper: SymboleoWrapper) -> None:
    assert errors(wrapper, event_type(" with performer: Seller")) == []
