"""Richness counters for SymboleoAC contract text.

``converged`` says nothing about how *much* contract a run produced, so these
counts sit beside it — analysis-side for now (``scripts/richness_sweep.py``
walks the ``output/`` archive); the promotion path and its gate live in
CLAUDE.md (Richness Instrumentation).

The counters are regex-level, not a parse: they accept any text — including
non-contract prose and code the JAR rejects — and report what they match, so
a count is only meaningful read beside ``converged``. One accepted false
positive: a user-invented type literally named ``O`` or ``P`` applied
call-style would count as a norm; unobserved across the archive, the example
corpus, and the fixtures at design time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN = re.compile(r'"[^"\r\n]*"|/\*.*?\*/|//[^\r\n]*', re.DOTALL)
_OBLIGATION_CLAUSE = re.compile(r"\b(?:Obligation|O)\s*\(")
_POWER_CLAUSE = re.compile(r"\b(?:Power|P)\s*\(")
_SURVIVING_HEADER = re.compile(r"\bSurviving\s+Obligations\b")


@dataclass(frozen=True)
class RichnessCounts:
    loc: int
    obligations: int
    surviving_obligations: int
    powers: int


def _blank_token(match: re.Match[str]) -> str:
    token = match.group()
    if token.startswith('"'):
        return '""'
    return "\n" * token.count("\n")


def _strip(code: str) -> str:
    """Mask string literals and comments, preserving line structure.

    One leftmost-match pass, not sequential per-construct passes: leftmost
    match is what lets each construct hide the others' openers (a ``/*``
    inside a ``//`` comment, a ``//`` inside a ``/*`` comment — sequential
    stripping gets one of those wrong whichever order it runs, since the
    first needs line-before-block and the second the reverse). Strings are
    masked to
    ``""`` rather than deleted so removal cannot splice the surrounding text
    into a clause match (``O "note" (`` must not become ``O  (``) and a
    string-only line stays non-blank for ``loc``; block comments become their
    own newlines so surrounding lines stay separate.
    """
    return _TOKEN.sub(_blank_token, code)


def measure(code: str) -> RichnessCounts:
    """Count non-blank lines and obligation/power clauses in ``code``.

    Obligation clauses split at the ``Surviving Obligations`` header (grammar
    section order puts every match after it in that section); conflating them
    would hide a model dumping norms into the wrong section.
    """
    stripped = _strip(code)
    header = _SURVIVING_HEADER.search(stripped)
    boundary = header.start() if header else len(stripped)
    return RichnessCounts(
        loc=sum(1 for line in stripped.splitlines() if line.strip()),
        obligations=len(_OBLIGATION_CLAUSE.findall(stripped, 0, boundary)),
        surviving_obligations=len(_OBLIGATION_CLAUSE.findall(stripped, boundary)),
        powers=len(_POWER_CLAUSE.findall(stripped)),
    )
