"""Pins upstream validator features the bundled jar must provide.

`test_ac_enforcement.py` fences what the jar must *reject*; this file fences
what it must *accept*. Both directions are needed, because they fail on
opposite kinds of jar swap: an older jar that lost a check goes undetected by
every `== []` assertion in the suite, and an older jar that never gained a
feature goes undetected by every `assert errors(...)` one.

Scope is narrow by necessity. Of the three upstream commits the 2026-08-03
refresh picked up, only one is observable here:

  e3e9edd  codegen: transfer transaction per transferable resource (O4b)
           -- not observable; we invoke the validator, never Symboleo2SC.
  50b8234  L4: Date.add(eventVar, n, units) resolves to the event's
           occurrence time -- observable, and the single case below.
  82e94f6  fix NPE on specs with no ACPolicy section -- not observable here.
           The unguarded dereference sits in the validator's
           checkControllerType, but Xtext swallows exceptions raised inside a
           @Check, so it never reaches the CLI's issue list: an
           ACPolicy-stripped contract validates clean on the jars either side
           of the fix.

So the narrow scope is deliberate, not an oversight. Add to this file when
a jar refresh lands a validator change that widens what parses or validates;
a rejection belongs in `test_ac_enforcement.py` instead.
"""

from pathlib import Path

import pytest

from symboleo_llm_tool.symboleo.wrapper import SymboleoWrapper

JAR_PATH = Path("./lib/symboleo-cli.jar")

# A state change as an obligation's consequent: illegal on every jar, and the
# archive's most frequent stall. An upstream branch under development annotates
# exactly this with out-of-band guidance, which makes it the probe for whether
# the bundled jar carries the hint channel.
_STATE_CHANGE_IN_OBLIGATION = """Domain D
  Seller isA Role with name: String, org: String, dept: String;
  Buyer isA Role with name: String, org: String, dept: String;
  Delivered isAn Event with delDueDate: Date, performer: Seller;
endDomain

Contract C (sellerP: Seller, buyerP: Buyer)
Declarations
  seller: Seller with name := sellerP.name, org := sellerP.org, dept := sellerP.dept;
  buyer: Buyer with name := buyerP.name, org := buyerP.org, dept := buyerP.dept;
Obligations
  o1: O(seller, buyer, true, Terminated(self));
endContract
"""

# The varying `Date.add` sits in a *declaration initializer*, and that position
# is load-bearing: the first-argument type check is position-sensitive. The same
# `Date.add(delivered, ...)` written inside `WhappensBefore(paid, ...)` is
# accepted by every jar back to 2026-05-20, so a case built there passes
# everywhere and fences nothing. In this position the 2026-05-20 and 2026-07-08
# builds both error and the current one does not. Keep new cases in a position
# where the old jar actually errors, and confirm it rather than assuming.
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


def test_bundled_jar_does_not_yet_carry_the_hint_channel(wrapper: SymboleoWrapper) -> None:
    """Pins whether the bundled jar attaches out-of-band guidance to issues.

    The pipeline is plumbed for it end to end -- `SymboleoIssue.data` parses,
    `.hint` exposes, and every correction template renders it -- but the bundled
    jar is the plain upstream build and annotates nothing, so the whole path is
    currently inert.

    **This assertion is expected to fail the moment a hint-carrying jar is
    bundled, and that failure is the point.** Invert it then: assert that this
    contract yields at least one issue with a `.hint`, which turns this case
    into the regression fence for the channel silently going quiet -- a failure
    mode nothing else would catch, since every message assertion in the suite
    passes either way.

    Written as a state change in an obligation's consequent because that is the
    archive's most frequent stall and the first case the upstream branch
    annotates.
    """
    issues = wrapper.validate(_STATE_CHANGE_IN_OBLIGATION)
    assert any(i.is_error for i in issues), "probe must stay illegal to be a probe"
    assert [i.hint for i in issues if i.hint] == []
