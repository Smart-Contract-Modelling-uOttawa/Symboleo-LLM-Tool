"""Judge archived runs for semantic fidelity against the curated inventories.

Usage (repo root; judge calls cost money — the cache makes re-runs free).
List roots explicitly: PowerShell does not expand ``*`` for native commands,
so a glob argument silently enumerates nothing:
    uv run python scripts/fidelity_sweep.py output/suite_<t1> output/suite_<t2>
    uv run python scripts/fidelity_sweep.py output --score-only

Walks every ``report.json`` under the given roots, judges each candidate's
``final_code`` whose contract has an inventory in ``contracts/inventories/``
(candidates of un-inventoried contracts are skipped silently), and prints
converged-only per-contract coverage cells; non-converged rows are judged too
but reach you only via ``--csv``. The judgment itself — instructions, payload,
verdict arithmetic — lives in ``symboleo_llm_tool/output/fidelity.py``; this
script only walks directories and spends judge calls.

Reads raw report dicts, never ``model_validate``: the archive spans schema
eras and the auditor must not crash on what it audits. Interpretation caveats:
coverage on a non-converged candidate (in the CSV) describes whatever text the
run ended with; cells are comparable within one contract only (different inventories,
different denominators); and the numbers are only as good as the judge —
calibrated for ``gpt-5.6-luna`` (CLAUDE.md, *Convergence ≠ fidelity*), so a
different ``--judge`` needs its own calibration before its numbers are
trusted.
"""

from __future__ import annotations

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml

from symboleo_llm_tool.config.models import LLMConfig
from symboleo_llm_tool.llm.factory import create_adapter
from symboleo_llm_tool.output.fidelity import build_payload, coverage, parse_judge_json

INVENTORY_DIR = Path("contracts/inventories")


def load_inventories() -> dict[str, dict[str, Any]]:
    """Inventories keyed by their source contract's lowercase stem."""
    inventories: dict[str, dict[str, Any]] = {}
    for path in sorted(INVENTORY_DIR.glob("*.yaml")):
        inventory = yaml.safe_load(path.read_text(encoding="utf-8"))
        source = Path(inventory["source"])
        inventory["_source_text"] = source.read_text(encoding="utf-8")
        inventories[source.stem.lower()] = inventory
    return inventories


def enumerate_candidates(
    roots: list[Path], inventories: dict[str, dict[str, Any]], cache: Path
) -> list[dict[str, Any]]:
    work: list[dict[str, Any]] = []
    for root in roots:
        for report_path in sorted(root.rglob("report.json")):
            report = json.loads(report_path.read_text(encoding="utf-8"))
            key = Path(report.get("input_file") or "?").stem.lower()
            if key not in inventories:
                continue
            arm = report_path.parent.name
            for candidate in report.get("candidates", []):
                code = candidate.get("final_code") or ""
                if not code.strip():
                    continue
                tag = f"{report_path.parent.parent.name}_{arm}_{candidate.get('candidate_id')}"
                work.append(
                    {
                        "tag": tag,
                        "out": cache / f"{tag}.json",
                        "arm": arm,
                        "contract": key,
                        "candidate": candidate.get("candidate_id"),
                        "converged": bool(candidate.get("converged")),
                        "code": code,
                    }
                )
    return work


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("roots", nargs="+", type=Path, help="run/suite dirs to judge")
    parser.add_argument("--judge", default="gpt-5.6-luna")
    parser.add_argument("--provider", default="openai")
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="unset by default — the seated judge is a reasoning model",
    )
    parser.add_argument("--max-tokens", type=int, default=16000)
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("output/fidelity_cache"),
        help="per-candidate judgments; existing entries are never re-judged",
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()

    inventories = load_inventories()
    args.cache.mkdir(parents=True, exist_ok=True)
    work = enumerate_candidates(args.roots, inventories, args.cache)
    pending = [w for w in work if not w["out"].exists()]

    if pending and not args.score_only:
        adapter = create_adapter(
            LLMConfig(
                provider=args.provider,
                model=args.judge,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )
        )

        def judge(item: dict[str, Any]) -> str:
            inventory = inventories[item["contract"]]
            text = adapter.generate(
                build_payload(inventory, inventory["_source_text"], item["code"])
            ).generated_text
            parsed = parse_judge_json(text)
            item["out"].write_text(
                json.dumps(parsed or {"error": text[:2000]}, indent=1), encoding="utf-8"
            )
            return item["tag"]

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(judge, item) for item in pending]
            for future in as_completed(futures):
                try:
                    print(f"  judged {future.result()}")
                except Exception as exc:  # noqa: BLE001 — one failure costs one candidate
                    print(f"  JUDGE FAILURE: {exc}")

    rows = []
    for item in work:
        if not item["out"].exists():
            continue
        result = json.loads(item["out"].read_text(encoding="utf-8"))
        if "error" in result:
            continue
        cov, inventions = coverage(result, len(inventories[item["contract"]]["items"]))
        rows.append(
            {
                "arm": item["arm"],
                "contract": item["contract"],
                "candidate": item["candidate"],
                "converged": item["converged"],
                "coverage": round(cov, 3),
                "inventions": inventions,
            }
        )

    print(
        f"\nSCANNED {len(rows)} judged candidates ({len(work)} enumerated, {len(pending)} were new)"
    )
    if not rows:
        return
    if args.csv is not None:
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {args.csv} ({len(rows)} rows)")

    def cell(cell_rows: list[dict[str, Any]]) -> str:
        if not cell_rows:
            return "-"
        covs = sorted(r["coverage"] for r in cell_rows)
        inventions = sum(r["inventions"] for r in cell_rows)
        return (
            f"{covs[len(covs) // 2]:.2f} [{covs[0]:.2f}-{covs[-1]:.2f}] "
            f"n={len(covs)} inv={inventions}"
        )

    for key in sorted({r["contract"] for r in rows}):
        print(f"\n=== {key} (converged candidates)")
        for arm in sorted({r["arm"] for r in rows if r["contract"] == key}):
            conv = [r for r in rows if r["arm"] == arm and r["contract"] == key and r["converged"]]
            print(f"  {arm:<26} {cell(conv)}")
    print(
        "\n(median [min-max]; inv = total inventions across the cell; "
        "cells comparable within one contract only)"
    )


if __name__ == "__main__":
    main()
