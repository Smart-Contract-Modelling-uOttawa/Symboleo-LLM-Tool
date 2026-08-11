"""Fences for the fidelity instrument's pure pieces and its tracked fixtures.

The judge itself is a live LLM and is not tested here; what these pin is the
calibration-critical instruction *phrases*, the payload *section order*, and
the verdict arithmetic — plus the inventory fixtures' shape. A full-text pin
of the instructions would be the string twice; the phrases are the parts whose
loss demonstrably changes verdicts.
"""

from collections import Counter
from pathlib import Path

import yaml

from symboleo_llm_tool.output.fidelity import (
    INSTRUCTIONS,
    VERDICTS,
    build_payload,
    coverage,
    parse_judge_json,
)

INVENTORY_DIR = Path("contracts/inventories")


def _inventories() -> dict[Path, dict]:
    return {
        path: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(INVENTORY_DIR.glob("*.yaml"))
    }


def test_every_contract_has_exactly_one_inventory() -> None:
    # A contract without an inventory silently drops out of every fidelity
    # sweep — absence must be a red test, not a smaller denominator. Counter,
    # not set: two inventories naming one source would silently shadow each
    # other in the sweep's stem-keyed dict.
    sources = Counter(inv["source"] for inv in _inventories().values())
    contracts = Counter(f"contracts/{p.name}" for p in Path("contracts").glob("*.txt"))
    assert sources == contracts


def test_inventories_are_well_formed() -> None:
    for path, inventory in _inventories().items():
        assert Path(inventory["source"]).exists(), f"{path.name}: source missing"
        items = inventory["items"]
        assert items, f"{path.name}: empty inventory"
        ids = [item["id"] for item in items]
        assert len(ids) == len(set(ids)), f"{path.name}: duplicate item ids"
        for item in items:
            for field in ("id", "kind", "clause", "expects"):
                assert item.get(field), f"{path.name}/{item.get('id')}: missing {field}"


def test_coverage_scores_present_full_partial_half_miscoded_zero() -> None:
    result = {
        "items": [
            {"id": "a", "verdict": "present"},
            {"id": "b", "verdict": "partial"},
            {"id": "c", "verdict": "miscoded"},
            {"id": "d", "verdict": "absent"},
        ],
        "inventions": [{"construct": "X"}],
    }
    cov, inventions = coverage(result, 4)
    assert cov == (1.0 + 0.5) / 4
    assert inventions == 1


def test_coverage_denominator_is_the_inventory_not_the_judge() -> None:
    # A judge that omits items must lose their credit; a shrinking denominator
    # would reward incomplete answers.
    cov, _ = coverage({"items": [{"id": "a", "verdict": "present"}]}, 5)
    assert cov == 1.0 / 5


def test_parse_judge_json_tolerates_fences_and_prose() -> None:
    text = 'Here you go:\n```json\n{"items": [], "inventions": []}\n```\nHope that helps!'
    assert parse_judge_json(text) == {"items": [], "inventions": []}


def test_parse_judge_json_rejects_non_dict_and_garbage() -> None:
    assert parse_judge_json("no json here") is None
    assert parse_judge_json("[1, 2]") is None


def test_payload_layout_matches_the_calibrated_shape() -> None:
    # The payload layout is part of what was calibrated; sections must appear
    # in the calibrated order with the inventory items as the checklist.
    inventory = {
        "items": [{"id": "x", "kind": "obligation", "clause": "1", "expects": "something"}]
    }
    payload = build_payload(inventory, "SOURCE TEXT", "CODE")
    positions = [
        payload.find(marker)
        for marker in (
            INSTRUCTIONS[:40],
            "## Checklist",
            "id: x",
            "## Source contract text",
            "SOURCE TEXT",
            "## Generated SymboleoAC",
            "CODE",
        )
    ]
    assert all(p >= 0 for p in positions)
    assert positions == sorted(positions)


def test_instructions_carry_the_calibration_critical_phrases() -> None:
    # Editing INSTRUCTIONS invalidates the 2026-08-11 judge calibration
    # (CLAUDE.md, Convergence != fidelity). These phrases are the discriminator
    # rules that separated a real judge from a syntax-checker; if this test
    # reds, either revert the edit or re-run the calibration before trusting
    # any new numbers.
    for phrase in (
        'a "may" modeled as an obligation is miscoded',
        "a consequence triggered by success where the text says failure is miscoded",
        "not merely encoded in an identifier's name",
        "Reasonable scaffolding is NOT an invention",
    ):
        assert phrase in INSTRUCTIONS
    for verdict in VERDICTS:
        assert f"- {verdict}:" in INSTRUCTIONS
