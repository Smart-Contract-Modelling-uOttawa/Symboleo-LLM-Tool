"""Detect violations of the rules the prompt teaches, in generated code.

``scan(code)`` returns the labels of every taught rule the text breaks. It is
the third instrument around the placement rules, and the only one that looks at
live model output: ``tests/integration/test_placement_rules.py`` pins what the
JAR accepts, ``_PLACEMENT_RULES`` in ``tests/unit/test_prompts.py`` pins that
the prompt still says it, and this says whether models obeyed. A rule can pass
both fences and still be ignored by every model, which is the case a prompt
change exists to move.

Scope is deliberately *taught* rules only -- each label corresponds to a
placement rule in ``_output_format.j2`` or a prohibition in
``_reserved_names.j2``. A failure class we have not taught (string
concatenation, negative ``Date.add`` offsets) is not a violation and does not
belong here; those surface as stall messages instead. Adding a placement rule
is therefore the moment to add a label.

The word families come from ``grammar.rule_literals`` rather than a hand-list.
That is not tidiness: the three families overlap enough to look interchangeable
and are not -- ``Violated`` is an obligation *event* but not a ``PowerFunction``,
``Exerted`` is a power event only -- and a hand-list got it wrong on first
writing, in the direction that reports a valid contract as a violation.

Pure text -> labels, like ``richness.py``, and lexical for the same reason: the
JAR is the oracle for legality, but it cannot be asked "which taught rule is
this", and half these forms are parse errors that mask everything after them.
Accepted caveats, all in the direction of under-reporting: comments and string
literals are not stripped, so a rule quoted inside one counts; enum member
detection assumes the ALL_CAPS convention the prompt's examples use; and only
``P(...)``/``Power(...)`` consequents are parsed structurally, everything else
being a regex over the whole text.
"""

from __future__ import annotations

import re
from functools import lru_cache

from symboleo_llm_tool.prompts.grammar import reserved_names, rule_literals

# What may stand in a power's consequent -- the rule the Power production names.
_POWER_FUNCTIONS = rule_literals("PowerFunction")
# What may stand inside `Happens(...)` applied to a norm or the contract. Three
# rules because powers, obligations, and the contract each have their own events.
_NORM_EVENTS = (
    set(rule_literals("PowerEventName"))
    | set(rule_literals("ObligationEventName"))
    | set(rule_literals("ContractEventName"))
)
_BASE_TYPES = "|".join(rule_literals("BaseType"))
_ONTOLOGY = "|".join(rule_literals("OntologyType"))
# The four norm-state actions carry a `norm` argument, so they are the ones that
# can appear unprefixed or in an obligation's consequent.
_NORM_ACTION_SET = frozenset(_POWER_FUNCTIONS) - {"self"}
_NORM_ACTIONS = "|".join(sorted(_NORM_ACTION_SET))

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # "never the base word itself (`supplierP: Role` does not parse)"
    ("base_type_reference", re.compile(rf":\s*(?:{_ONTOLOGY})\b\s*[,;)]")),
    # "the alias only renames, so `isA Number with <attrs>` does not parse"
    ("alias_with_attributes", re.compile(rf"\bisA\s+(?:{_BASE_TYPES})\s+with\b")),
    # "`<name>: <Type> := <value>` does not parse"
    ("wholesale_assignment", re.compile(r"^\s*\w+\s*:\s*\w+\s*:=", re.MULTILINE)),
    # "a literal in a predicate is a parse error"
    (
        "date_literal_in_predicate",
        re.compile(
            r"(?:WhappensBefore|ShappensBefore|HappensAfter|HappensWithin|Occurs)\([^)]*Date\("
        ),
    ),
    # "`obligations.` there is a required literal prefix"
    (
        "unprefixed_norm_reference",
        re.compile(rf"\b(?:{_NORM_ACTIONS})\(\s*(?!obligations\.|powers\.|self\b)[a-z]"),
    ),
    # "the dot form `CargoGrade.PREMIUM` is never legal in any position"
    ("dotted_enum_member", re.compile(r"\b[A-Z]\w*\.[A-Z][A-Z0-9_]+\b")),
]

# "a predicate takes that instance and never applies its type to it"
_HAPPENS_ARGUMENT = re.compile(r"Happens\(\s*([A-Z]\w*)\s*\(")
# "a name you invent may not be a reserved word" -- the whole family at once,
# since the escape (`SuspensionEvent`, `ControllerRole`) is the same for each.
_DECLARED_TYPE = re.compile(r"\b(\w+)\s+isAn?\b")
_POWER_CLAUSE = re.compile(r"\b(?:P|Power)\s*\(")
_OBLIGATION_CLAUSE = re.compile(r"\b(?:O|Obligation)\s*\(")
_CALLED_NAME = re.compile(r"^(\w+)\s*\(")


@lru_cache(maxsize=1)
def _reserved() -> frozenset[str]:
    return frozenset(reserved_names())


def _consequents(code: str, clause: re.Pattern[str]) -> list[str]:
    """The last top-level argument of every clause ``clause`` opens.

    Balanced-paren parsing rather than a regex: the earlier arguments are
    predicates carrying their own parentheses to arbitrary depth
    (``Happens(Violated(obligations.x))`` is two), so any bounded-nesting
    pattern silently misses the deep cases. An unterminated clause (a truncated
    response) yields nothing rather than a partial argument.
    """
    consequents: list[str] = []
    for match in clause.finditer(code):
        index, depth, start = match.end(), 1, match.end()
        arguments: list[str] = []
        while index < len(code) and depth:
            char = code[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    arguments.append(code[start:index])
            elif char == "," and depth == 1:
                arguments.append(code[start:index])
                start = index + 1
            index += 1
        if depth == 0 and len(arguments) >= 2:
            consequents.append(arguments[-1].strip())
    return consequents


def scan(code: str) -> list[str]:
    """Labels of every taught rule ``code`` breaks, sorted and deduplicated."""
    found = {label for label, pattern in _PATTERNS if pattern.search(code)}

    if any(name not in _NORM_EVENTS for name in _HAPPENS_ARGUMENT.findall(code)):
        found.add("type_applied_to_instance")
    if any(name in _reserved() for name in _DECLARED_TYPE.findall(code)):
        found.add("reserved_type_name")
    # An allow-list, not a list of known-bad forms: the rule is that a state
    # change is *all* a power's consequent can be, so anything else is a
    # violation whether or not we have seen a model write it.
    for consequent in _consequents(code, _POWER_CLAUSE):
        called = _CALLED_NAME.match(consequent)
        if called is None or called.group(1) not in _POWER_FUNCTIONS:
            found.add("non_state_power_consequent")
            break
    # "those state changes belong to powers alone" — a deny-list here, because
    # an obligation's consequent is otherwise open (`Assign`, `Happens`, a
    # comparison), so only the norm-state actions are excluded.
    if any(
        (called := _CALLED_NAME.match(consequent)) and called.group(1) in _NORM_ACTION_SET
        for consequent in _consequents(code, _OBLIGATION_CLAUSE)
    ):
        found.add("state_change_in_obligation")
    return sorted(found)
