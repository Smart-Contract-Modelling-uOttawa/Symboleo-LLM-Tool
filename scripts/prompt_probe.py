"""Run the prompt-regression matrix and census what the models did with it.

Run from the repo root:
    uv run python scripts/prompt_probe.py CONTRACT [CONTRACT ...] [--config PATH] [--csv PATH]
    uv run python scripts/prompt_probe.py --census output/suite_20260807_101500

One suite per contract, so every arm and candidate of that contract runs
concurrently; the suite file (default ``configs/prompt_probe.yaml``) owns the
arms. Contracts are listed explicitly and have no default: the matrix costs
``contracts x arms x candidates x (1 + max_iterations)`` LLM calls, which is not
a thing to launch by pressing enter.

The table is read back from the persisted run directories rather than from the
in-memory results, so what it reports and what the archive holds cannot
disagree, and ``--census`` can re-read any past run without spending a token.

**It classifies nothing.** ``errors`` is the ERROR-severity count at each
iteration and ``stalled`` says only that the last correction reduced nothing;
every non-converged candidate then prints its final blocking errors verbatim,
and reading those is the analysis. An earlier version scored each candidate
against a hand-written catalog of known traps, and that was a mistake twice
over: it missed the dominant failure of the very next run it was used on --
reported as a clean ``-`` -- and having categories to slice on invited a
convergence-rate comparison that turned out to measure contract difficulty.
The validator's own output is complete by construction and needs no upkeep;
a catalog is neither.
"""

from __future__ import annotations

import argparse
import csv
import json
import threading
from pathlib import Path
from typing import Any

from symboleo_llm_tool.config.loader import load_suite_config
from symboleo_llm_tool.experiments.runner import run_suite
from symboleo_llm_tool.output.writer import write_suite_results
from symboleo_llm_tool.symboleo.models import SymboleoIssue

COLUMNS = ["run", "contract", "candidate", "converged", "iters", "errors", "stalled"]
DEFAULT_CONFIG = Path("configs/prompt_probe.yaml")
_STALL_LINES = 6

_print_lock = threading.Lock()


def _progress(
    experiment: int, candidate: int, iteration: int, errors: list[SymboleoIssue], _c: int, _i: int
) -> None:
    # Fires from worker threads once max_concurrency > 1. A lock-guarded single
    # print, like the CLI's: buffering or reordering here would re-coordinate
    # concurrency at the wrong altitude.
    blocking = sum(1 for issue in errors if issue.is_error)
    with _print_lock:
        print(f"    exp {experiment} cand {candidate} iter {iteration}: {blocking} error(s)")


def _run_matrix(contracts: list[Path], config_path: Path) -> list[Path]:
    suite_dirs = []
    for contract_path in contracts:
        contract_text = contract_path.read_text(encoding="utf-8")
        suite = load_suite_config(config_path, contract_text)
        print(f"\n=== {contract_path.name}: {len(suite.experiments)} arm(s) ===")
        result = run_suite(suite, input_file=str(contract_path), on_progress=_progress)
        suite_dir = write_suite_results(result, suite)
        print(f"  -> {suite_dir}")
        suite_dirs.append(suite_dir)
    return suite_dirs


def _rows_for_report(report_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    # Relative to the repo root, so a single run and a suite's experiment
    # subdirectory both read as a path you can paste back into --census.
    directory = report_path.parent
    try:
        run = directory.relative_to(Path.cwd()).as_posix()
    except ValueError:
        run = directory.as_posix()
    contract = Path(report.get("input_file") or "?").stem
    rows: list[dict[str, Any]] = []
    stalls: list[str] = []
    for candidate in report.get("candidates", []):
        history = candidate.get("error_history") or []
        last = history[-1] if history else {}
        counts = [_error_count(record) for record in history]
        rows.append(
            {
                "run": run,
                "contract": contract,
                "candidate": candidate.get("candidate_id", ""),
                "converged": "yes" if candidate.get("converged") else "no",
                "iters": candidate.get("iterations_used", ""),
                # The whole series, because its shape is the finding: a steady
                # descent that ran out of budget and a file frozen behind a
                # masking parse error are both "did not converge" and want
                # opposite responses.
                "errors": ">".join(str(count) for count in counts) or "-",
                "stalled": "yes" if _stalled(candidate, counts) else "-",
            }
        )
        if not candidate.get("converged"):
            stalls.append(_stall(run, contract, candidate, last))
    return rows, stalls


def _error_count(record: dict[str, Any]) -> int:
    return sum(1 for issue in record.get("errors", []) if issue.get("severity") == "ERROR")


def _stalled(candidate: dict[str, Any], counts: list[int]) -> bool:
    """Did the last correction reduce nothing?

    Deliberately the narrowest claim the data supports, and no attempt to say
    why. A candidate cut short by a provider failure is not stalled -- it never
    got to try.
    """
    if candidate.get("converged") or candidate.get("failure") or len(counts) < 2:
        return False
    return counts[-1] >= counts[-2]


def _stall(run: str, contract: str, candidate: dict[str, Any], last: dict[str, Any]) -> str:
    failure = candidate.get("failure")
    header = f"--- {contract} [{run}] candidate {candidate.get('candidate_id', '')}"
    if failure:
        return f"{header}\n    cut short: {failure[:120]}"
    lines = (last.get("code") or "").splitlines()
    out = [header]
    for issue in last.get("errors", []):
        if issue.get("severity") != "ERROR":
            continue
        number = issue.get("line")
        source = lines[number - 1].strip()[:80] if number and number <= len(lines) else "?"
        out.append(f"    L{number}: {(issue.get('message') or '')[:90]}\n         | {source}")
        if len(out) > _STALL_LINES:
            break
    return "\n".join(out)


def _census(roots: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    stalls: list[str] = []
    for root in roots:
        for report_path in sorted(root.rglob("report.json")):
            try:
                found, stalled = _rows_for_report(report_path)
            except Exception as exc:  # any bad artifact skips, never aborts
                print(f"skipping {report_path}: {exc}")
                continue
            rows.extend(found)
            stalls.extend(stalled)
    return rows, stalls


def _print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("no candidates found")
        return
    cells = [[str(row[column]) for column in COLUMNS] for row in rows]
    widths = [
        max(len(column), *(len(line[i]) for line in cells)) for i, column in enumerate(COLUMNS)
    ]
    print("  ".join(column.ljust(widths[i]) for i, column in enumerate(COLUMNS)))
    for line in cells:
        print("  ".join(value.ljust(widths[i]) for i, value in enumerate(line)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("contracts", nargs="*", type=Path, help="contract .txt files to run")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help="suite file naming the arms"
    )
    parser.add_argument(
        "--census", nargs="+", type=Path, default=None, help="census these dirs, run nothing"
    )
    parser.add_argument("--csv", type=Path, default=None, help="also write rows to PATH")
    args = parser.parse_args()

    if args.census:
        roots = list(args.census)
    elif args.contracts:
        roots = _run_matrix(args.contracts, args.config)
    else:
        parser.error("name at least one contract to run, or --census a directory to read")

    rows, stalls = _census(roots)
    print()
    _print_table(rows)
    for stall in stalls:
        print(f"\n{stall}")

    if args.csv is not None:
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwrote {args.csv} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
