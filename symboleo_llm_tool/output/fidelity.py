"""Checklist-anchored fidelity judging — the pure pieces.

The analysis-side sibling of ``richness.py``: this module owns what a fidelity
judgment *is* (the judge instructions, the payload layout, the verdict
arithmetic), while ``scripts/fidelity_sweep.py`` is the thin consumer that
walks run directories and spends judge calls. Nothing here calls an LLM.

The instrument is two-stage: a curated clause inventory per contract
(``contracts/inventories/*.yaml`` — complete by construction for its contract,
derived from its text) and a judge that fills one verdict per item plus an
inventions list. Coverage and inventions are deliberately separate axes:
coverage = (present + 0.5*partial) / items, inventions counted beside it,
never folded into one scalar and never averaged across contracts (different
denominators — the same confound as cross-contract convergence rates).

**Editing ``INSTRUCTIONS`` invalidates the judge calibration** (2026-08-11,
CLAUDE.md *Convergence ≠ fidelity*: gpt-5.6-luna seated at 39/42 against hand
labels, Cohere excluded). Re-run the calibration before trusting numbers from
a changed prompt or a different judge; ``test_fidelity.py`` pins the
calibration-critical phrases so an accidental edit fails a test rather than
silently de-calibrating the instrument.
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml

INSTRUCTIONS = """You are auditing whether a generated formal contract (SymboleoAC) faithfully represents its source contract text. Judge ONLY semantic fidelity — assume the code is syntactically valid.

For each checklist item, give a verdict:
- present: correctly represented — right parties and direction, right deontic type (an obligation for "shall", a power for discretionary "may"/"entitled"), temporal constraints enforced by predicates over dates or events (not merely encoded in an identifier's name).
- partial: represented but weakened or approximated — e.g. a deadline anchored to the wrong reference point, a dropped conjunct.
- miscoded: a construct clearly attempts this item but gets it wrong — wrong deontic type, wrong direction or parties, wrong trigger, a constraint that is named but never enforced.
- absent: nothing in the code represents this item.

Then list inventions: constructs with no basis in the source text — invented events, roles, attributes, enumerations, obligations, or machinery. Reasonable scaffolding is NOT an invention: role attribute triples (name/org/dept), event declarations for actions the text names, contract parameters, renamings.

Be strict about deontic type and triggers: a "may" modeled as an obligation is miscoded; a consequence triggered by success where the text says failure is miscoded.

Output ONLY a JSON object, no prose, no code fences:
{"items":[{"id":"<item id>","verdict":"present|partial|miscoded|absent","evidence":"<construct name or null>","note":"<max 25 words>"}],"inventions":[{"construct":"<name>","note":"<max 20 words>"}]}
Include every checklist item exactly once."""

VERDICTS = ("present", "partial", "miscoded", "absent")


def build_payload(inventory: dict[str, Any], source_text: str, code: str) -> str:
    """One blinded judge payload: instructions, checklist, source, code.

    Byte-identical layout to the calibration payloads — the payload shape is
    part of what was calibrated, so it lives here rather than in the script.
    """
    checklist = yaml.safe_dump(inventory["items"], sort_keys=False)
    return (
        f"{INSTRUCTIONS}\n\n## Checklist\n{checklist}\n"
        f"## Source contract text\n{source_text}\n"
        f"## Generated SymboleoAC\n{code}\n"
    )


def parse_judge_json(text: str) -> dict[str, Any] | None:
    """The judge's JSON, tolerating fences and stray prose; None if unusable."""
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def coverage(result: dict[str, Any], n_items: int) -> tuple[float, int]:
    """(clause coverage, invention count) from one judge result.

    Coverage counts only ``present`` (1.0) and ``partial`` (0.5); ``miscoded``
    deliberately scores zero — a wrong-direction or wrong-modality encoding is
    not partial credit, it is the class of flaw the 2026-07 audit failed the
    corpus for. The denominator is the *inventory's* item count, so a judge
    that omits items loses their credit rather than shrinking the denominator.
    """
    verdicts = [item.get("verdict") for item in result.get("items", [])]
    score = sum(1.0 for v in verdicts if v == "present")
    score += sum(0.5 for v in verdicts if v == "partial")
    return score / n_items, len(result.get("inventions", []))
