"""Pins upstream validator features the bundled jar must provide.

`test_ac_enforcement.py` fences what the jar must *reject*; this file fences
what it must *accept*. Both directions are needed, because they fail on
opposite kinds of jar swap: an older jar that lost a check goes undetected by
every `== []` assertion in the suite, and an older jar that never gained a
feature goes undetected by every `assert errors(...)` one. Replacing
`lib/symboleo-cli.jar` with the 2026-07-08 build passed all 66 integration
tests before this file existed.

Scope is narrow by necessity. Of the three upstream commits the 2026-08-03
refresh picked up, only one is observable here:

  e3e9edd  codegen: transfer transaction per transferable resource (O4b)
           -- not observable; we invoke the validator, never Symboleo2SC.
  50b8234  L4: Date.add(eventVar, n, units) resolves to the event's
           occurrence time -- observable, and the single case below.
  82e94f6  fix NPE on specs with no ACPolicy section -- not observable;
           an ACPolicy-stripped contract validates clean on the jars either
           side of the fix, so the crash lives on the codegen half.

So one case is the correct size today, not an oversight. Add to this file when
a jar refresh lands a validator change that widens what parses or validates;
a rejection belongs in `test_ac_enforcement.py` instead.
"""

from pathlib import Path

import pytest

from symboleo_llm_tool.symboleo.wrapper import SymboleoWrapper

JAR_PATH = Path("./lib/symboleo-cli.jar")

# The varying `Date.add` sits in a *declaration initializer*, and that position
# is load-bearing: the first-argument type check is position-sensitive. The same
# `Date.add(delivered, ...)` written inside `WhappensBefore(paid, ...)` is
# accepted by every jar back to 2026-05-20, so a case built there passes
# everywhere and fences nothing. Verified by running this file against all three
# builds -- see the docstring. Keep new cases in a position where the old jar
# actually errors, and confirm it rather than assuming.
BASE = """Domain D
  Seller isA Role with name: String, org: String, dept: String;
  Buyer isA Role with name: String, org: String, dept: String;
  Delivered isAn Event with delDueDate: Date, performer: Seller;
  Paid isAn Event with payDueDate: Date, performer: Buyer;
endDomain

Contract C (sellerP: Seller, buyerP: Buyer, effDate: Date, delDays: Number)
Declarations
  seller: Seller with name := sellerP.name, org := sellerP.org, dept := sellerP.dept;
  buyer: Buyer with name := buyerP.name, org := buyerP.org, dept := buyerP.dept;
  delivered: Delivered with delDueDate := Date.add(effDate, delDays, days), performer := seller;
  paid: Paid with payDueDate := Date.add({first_arg}, delDays, days), performer := buyer;
Obligations
  o1: O(buyer, seller, true, WhappensBefore(paid, paid.payDueDate));
endContract
"""


@pytest.fixture(scope="module")
def wrapper() -> SymboleoWrapper:
    return SymboleoWrapper(jar_path=JAR_PATH)


def contract(first_arg: str) -> str:
    assert "{first_arg}" in BASE, "BASE lost its format slot"
    return BASE.format(first_arg=first_arg)


def errors(wrapper: SymboleoWrapper, code: str) -> list[str]:
    return [i.message for i in wrapper.validate(code) if i.is_error]


def test_date_add_accepts_a_date_typed_first_argument(wrapper: SymboleoWrapper) -> None:
    # The form both the old and new jars accept, and the one the prompt teaches.
    # Guards the case below: if BASE broke, that one would fail for the wrong
    # reason and read as a missing upstream feature.
    assert errors(wrapper, contract("effDate")) == []


def test_date_add_accepts_an_event_variable_as_first_argument(wrapper: SymboleoWrapper) -> None:
    # Upstream 50b8234 (L4). The jar bundled before 2026-08-03 rejects this with
    # "The first argument of 'Date.add' must be a Date, but the given expression
    # has type 'Delivered'", so this case is what distinguishes the two builds.
    #
    # Pinned as a jar capability, deliberately not taught in `_output_format.j2`:
    # the prompt's Date.add anchor stays the date-point form. If that guidance is
    # ever widened to cover event-relative deadlines, the bullet needs its own
    # case in `test_placement_rules.py` under the leaf-construct policy -- this
    # one fences the jar, not the prompt.
    assert errors(wrapper, contract("delivered")) == []
