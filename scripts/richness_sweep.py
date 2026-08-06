"""Sweep the output/ archive for richness counts beside convergence.

Run from the repo root:
    uv run python scripts/richness_sweep.py [ROOT] [--csv PATH]

One row per candidate, for every ``report.json`` under ROOT (default:
``output/``) — single runs and suite experiment subdirectories alike. The
``gen_*`` count columns measure the generation pass (iteration 0), ``final_*``
the code the run ended with; ``contract_lines`` is the source contract's
non-blank line count and ``loc_ratio`` is ``final_loc / contract_lines``.
Reads raw dicts, not the current Pydantic models: the archive spans schema
eras, and the sweep must not crash on the artifacts it exists to audit.

Richness counts on a non-converged candidate describe whatever text the run
ended with — read them beside ``converged`` (and the era boundaries in
CLAUDE.md's Known Issues) before averaging anything.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import yaml

from symboleo_llm_tool.output.richness import measure

COLUMNS = [
    "run",
    "candidate",
    "gen_model",
    "gen_strategy",
    "converged",
    "iterations",
    "gen_loc",
    "gen_obligations",
    "gen_surviving",
    "gen_powers",
    "final_loc",
    "final_obligations",
    "final_surviving",
    "final_powers",
    "contract_lines",
    "loc_ratio",
]


def _non_blank_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _contract_lines(report_dir: Path) -> int | None:
    """Denominator from contract.txt — beside the report, or (for a suite
    experiment subdir) one level up. Absent from runs before 2026-08-05."""
    for directory in (report_dir, report_dir.parent):
        path = directory / "contract.txt"
        if path.is_file():
            return _non_blank_lines(path.read_text(encoding="utf-8"))
    return None


def _generation_identity(report_dir: Path) -> tuple[str, str]:
    config_path = report_dir / "config.yaml"
    if not config_path.is_file():
        return "", ""
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    generation = config.get("generation") or {}
    return (generation.get("llm") or {}).get("model", ""), generation.get("strategy", "")


def _rows_for_report(report_path: Path, root: Path) -> list[dict[str, Any]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    run = report_path.parent.relative_to(root).as_posix()
    model, strategy = _generation_identity(report_path.parent)
    contract_lines = _contract_lines(report_path.parent)
    rows: list[dict[str, Any]] = []
    for candidate in report.get("candidates", []):
        history = candidate.get("error_history") or []
        gen = measure(history[0].get("code") or "") if history else None
        final = measure(candidate.get("final_code") or "")
        rows.append(
            {
                "run": run,
                "candidate": candidate.get("candidate_id", ""),
                "gen_model": model,
                "gen_strategy": strategy,
                "converged": candidate.get("converged", ""),
                "iterations": candidate.get("iterations_used", ""),
                "gen_loc": gen.loc if gen else "",
                "gen_obligations": gen.obligations if gen else "",
                "gen_surviving": gen.surviving_obligations if gen else "",
                "gen_powers": gen.powers if gen else "",
                "final_loc": final.loc,
                "final_obligations": final.obligations,
                "final_surviving": final.surviving_obligations,
                "final_powers": final.powers,
                "contract_lines": contract_lines if contract_lines is not None else "",
                "loc_ratio": f"{final.loc / contract_lines:.2f}" if contract_lines else "",
            }
        )
    return rows


def _print_table(rows: list[dict[str, Any]]) -> None:
    cells = [[str(row[column]) for column in COLUMNS] for row in rows]
    widths = [
        max(len(column), *(len(line[i]) for line in cells)) if cells else len(column)
        for i, column in enumerate(COLUMNS)
    ]
    print("  ".join(column.ljust(widths[i]) for i, column in enumerate(COLUMNS)))
    for line in cells:
        print("  ".join(value.ljust(widths[i]) for i, value in enumerate(line)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", default=Path("output"), type=Path)
    parser.add_argument("--csv", type=Path, default=None, help="also write rows to PATH")
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for report_path in sorted(args.root.rglob("report.json")):
        try:
            rows.extend(_rows_for_report(report_path, args.root))
        except Exception as exc:  # any bad artifact skips, never aborts
            print(f"skipping {report_path}: {exc}")
    _print_table(rows)

    if args.csv is not None:
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwrote {args.csv} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
