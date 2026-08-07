"""The bundled Symboleo grammar, and the names derived from it.

Owns the grammar resource for the whole tool. It lives here rather than in
``pipeline/`` because the prompt layer needs the reserved names unconditionally
and ``prompts/`` cannot import from ``pipeline/`` without inverting the
dependency direction (cli/api -> pipeline -> llm/prompts/symboleo). Keeping one
owner also keeps the resource identity in one module rather than splitting it
across two load policies, the same argument ``prompts/examples.py`` makes for the
few-shot corpus. ``output/traps.py`` reads it too, which is a leaf importing a
leaf and so creates no cycle.

Everything here is cached: three strategy environments times N suite experiments
would otherwise re-read and re-scan a 13 KB file repeatedly.
"""

import re
from functools import lru_cache
from importlib import resources

_GRAMMAR_PACKAGE = "symboleo_llm_tool.resources"
_GRAMMAR_FILE = "Symboleo.xtext"

# Xtext turns every quoted literal into a keyword token, and a keyword can never
# be an ID -- so these are exactly the names a generated contract may not invent.
# BOTH quote styles are required: the grammar uses "Asset" (OntologyType) and
# 'Suspension' (PowerStateName), so a single-style scan silently drops the whole
# base-type category.
_QUOTED_LITERAL = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"")

# Only identifier-shaped literals can collide with a name. Punctuation (`:=`) and
# dotted calls (`Date.add`) are reserved too, but nothing could ever name a type
# that, so listing them would be prompt tokens spent for no coverage.
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@lru_cache(maxsize=1)
def load_grammar() -> str:
    try:
        grammar_file = resources.files(_GRAMMAR_PACKAGE).joinpath(_GRAMMAR_FILE)
        return grammar_file.read_text(encoding="utf-8")
    except Exception as e:
        raise RuntimeError(
            f"Failed to load Symboleo grammar resource: {e}. "
            f"Ensure {_GRAMMAR_FILE} is present in symboleo_llm_tool/resources/."
        ) from e


@lru_cache(maxsize=1)
def reserved_names() -> tuple[str, ...]:
    """Identifier-shaped keywords the grammar reserves, sorted and deduplicated.

    Derived rather than hand-listed so the list follows the grammar file: a
    hand-maintained copy would sit outside the jar/grammar atomic-change rule and
    fail silently, in exactly the way this guidance exists to prevent.

    Sorted because the rendered prompt is a research artifact and must be
    byte-reproducible across processes.
    """
    return _identifier_literals(load_grammar())


@lru_cache(maxsize=None)
def rule_literals(rule: str) -> tuple[str, ...]:
    """Identifier-shaped keywords one named rule admits, sorted and deduplicated.

    ``reserved_names`` asks which words a contract may not invent;
    this asks which words one position accepts -- e.g. ``PowerFunction`` is
    exactly what may stand in a power's consequent. Same lexical derivation, so
    it carries the same guarantee and the same limit: valid where the fact is
    purely grammatical, never a substitute for the JAR on what a contract must
    satisfy overall.

    Raises ``ValueError`` for a rule the grammar does not define. A refresh that
    renames one must fail loudly here: an empty tuple would silently turn every
    use of the position into a match, or none of them.
    """
    return _identifier_literals(_rule_body(load_grammar(), rule))


def _identifier_literals(text: str) -> tuple[str, ...]:
    names = {
        literal
        for match in _QUOTED_LITERAL.finditer(text)
        for literal in match.groups()
        if literal and _IDENTIFIER.fullmatch(literal)
    }
    return tuple(sorted(names))


def _rule_body(grammar: str, rule: str) -> str:
    """Text between a rule's ``:`` and its terminating ``;``.

    Scanned rather than matched with a lazy regex: rule bodies quote ``';'`` as a
    literal (statement terminators are part of the language), so the first `;` in
    the text is routinely not the rule's end.
    """
    header = re.search(rf"^{re.escape(rule)}\b[^:\n]*:", grammar, re.MULTILINE)
    if header is None:
        raise ValueError(f"Grammar defines no rule named {rule!r}")
    quote = ""
    for index in range(header.end(), len(grammar)):
        char = grammar[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == ";":
            return grammar[header.end() : index]
    raise ValueError(f"Rule {rule!r} is unterminated in the grammar")
