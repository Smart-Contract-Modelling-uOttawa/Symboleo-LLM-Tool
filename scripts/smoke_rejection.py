"""Manual smoke test for the contract-less-correction gate (CLAUDE.md, Correction Adoption).

Run from the repo root:  uv run python scripts/smoke_rejection.py

Exercises the CLI, config loader, pipeline, **real SymboleoAC JAR**, writer, and
`report.json` end to end. Only the LLM is faked, and necessarily so: a model
returning no contract is a rare degenerate event that cannot be provoked on
demand, so the responses are scripted from the trajectory actually observed in
`output/run_20260731_104538` — including its verbatim garbled echo. This proves
the pipeline handles such a response correctly; it says nothing about how often
one occurs, which only a real provider can answer.

Trajectory A runs twice — once with the gate live, once with it disabled — so
the damage prevented is a measured contrast between real files rather than an
assertion about intent. Trajectory B has no control arm: its scripted responses
recover either way, so the arms would differ only in a prompt, which A already
covers. Requires Java 17 on PATH.

Exits non-zero if any check fails.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from symboleo_llm_tool.cli.main import app
from symboleo_llm_tool.llm.base import GenerationResult, LLMAdapter
from symboleo_llm_tool.output.models import TokenUsage
from symboleo_llm_tool.pipeline import pipeline

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"

# Verbatim from output/run_20260731_104538 iteration 2: a 23-token response
# echoing the validator's own message back, misspelled ("mimatched", "endNAM").
# Not a contract and not meant as one — the input the gate exists for.
GARBAGE = "- Line 10, Column 5: mimatched input 'Terminated' expecting 'endNAM'"


class ScriptedAdapter(LLMAdapter):
    """Returns a fixed sequence of responses and records the prompts it was given.

    ``completion_tokens`` counts up per call so a token assertion can tell "the
    refused iteration recorded its own usage" from "it copied the previous
    record's" — a fixture with equal usage everywhere cannot.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._calls = 0
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> GenerationResult:
        text = self._responses[self._calls]
        usage = TokenUsage(prompt_tokens=100, completion_tokens=10 + self._calls, cost_usd=0.001)
        self._calls += 1
        self.prompts.append(prompt)
        return GenerationResult(generated_text=text, usage=usage)


class Checks:
    """Collects pass/fail results so one failure does not hide the rest."""

    def __init__(self) -> None:
        self.failed: list[str] = []
        self.total = 0

    def __call__(self, ok: bool, label: str, detail: str = "") -> None:
        self.total += 1
        if not ok:
            self.failed.append(label)
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {label}" + (f"  — {detail}" if detail else ""))


def _write_config(out_dir: Path) -> Path:
    """A real config file on disk, so the CLI's own loader is exercised.

    Paths are absolute: the smoke test must not depend on the caller's CWD, and
    `jar_path` otherwise defaults to a CWD-relative location.

    `provider: mock` is inert — `create_adapter` is patched before the CLI runs.
    It is the safe value to leave here because a *failed* patch then degrades to
    the mock adapter or an unknown-model error rather than billing a real call.
    Nothing here depends on `mock_adapter.py`, which is slated for deletion.
    """
    cfg = {
        "pipeline": {"num_candidates": 1, "max_iterations": 2},
        "generation": {
            "llm": {"provider": "mock", "model": "mock"},
            "strategy": "zero_shot",
            "include_grammar": False,
        },
        "correction": {
            "llm": {"provider": "mock", "model": "mock"},
            "strategy": "zero_shot",
            "include_grammar": False,
        },
        "symboleo": {"jar_path": str(REPO / "lib" / "symboleo-cli.jar")},
        "output": {"directory": str(out_dir), "save_intermediates": True},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "config.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return path


def _run_cli(
    root: Path, name: str, responses: list[str], *, gate_live: bool
) -> tuple[dict, Path, ScriptedAdapter]:
    """Invoke the real CLI end to end; return its report.json, run dir, and adapter."""
    out_dir = root / name
    cfg_path = _write_config(out_dir)

    adapter = ScriptedAdapter(responses)
    patches = [patch.object(pipeline, "create_adapter", lambda *a, **k: adapter)]
    if not gate_live:
        # Reproduce pre-fix behaviour by neutering the gate. Reaching into a
        # private symbol is deliberate, and both ways it can rot are loud: a
        # rename makes patch.object raise AttributeError, and a gate bypassed at
        # the call site makes the contrast checks in trajectory A fail.
        patches.append(patch.object(pipeline, "_has_contract_span", lambda _code: True))

    for p in patches:
        p.start()
    try:
        result = CliRunner().invoke(
            app, ["run", str(FIXTURES / "sample_contract.txt"), "--config", str(cfg_path)]
        )
    finally:
        for p in patches:
            p.stop()

    if result.exit_code != 0:
        print(result.output)
        raise SystemExit(f"[{name}] CLI exited {result.exit_code}")

    run_dirs = [d for d in out_dir.iterdir() if d.is_dir() and d.name.startswith("run_")]
    if len(run_dirs) != 1:
        raise SystemExit(f"[{name}] expected exactly 1 run dir, found {len(run_dirs)}")
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    return report, run_dirs[0], adapter


def _errors(record: dict) -> int:
    return sum(1 for e in record["errors"] if e["severity"] == "ERROR")


def _trajectory_stuck(root: Path, check: Checks, invalid: str) -> None:
    """Model refuses twice: the run cannot converge, but must not lose the contract."""
    print("\n=== Trajectory A — model gets stuck (refuses twice) ===")
    print("    gen -> 1-error contract | corr1 -> garbage | corr2 -> garbage\n")
    print("  With the gate LIVE:")

    report, run_dir, _ = _run_cli(root, "a_gate_live", [invalid, GARBAGE, GARBAGE], gate_live=True)
    cand = report["candidates"][0]
    hist = cand["error_history"]

    check(
        cand["final_code"].strip() == invalid.strip(),
        "final_code is the real contract, not the garbage",
        f"{len(cand['final_code'])} chars",
    )
    check(cand["converged"] is False, "converged is False — the ERROR was never fixed")
    check(len(hist) == 3, "all three iterations recorded", f"len={len(hist)}")
    check(hist[1]["rejected_response"] == GARBAGE, "the raw refused text was recorded")
    check(hist[1]["code"] == hist[0]["code"], "the refused iteration retained the previous code")
    check(hist[1]["errors"] == hist[0]["errors"], "the refused iteration carried errors forward")
    check(hist[0]["rejected_response"] is None, "generation (iteration 0) was NOT gated")
    # Distinct per call: a refused iteration that copied the previous record's
    # usage would read [10, 10, 12], which an equal-usage fixture cannot detect.
    completions = [r["usage"]["completion_tokens"] for r in hist]
    check(completions == [10, 11, 12], "each iteration recorded its OWN usage", str(completions))
    check(
        cand["total_tokens"] == 3 * 100 + 10 + 11 + 12,
        "total_tokens rolls up every billed call, refusals included",
        str(cand["total_tokens"]),
    )

    # Both corrections were refused, so both get a companion file. Nothing else
    # at any layer checks that it is written per refusal rather than once, and
    # the exact set also pins the .txt extension and the ungated iteration 0.
    inter = run_dir / "intermediates"
    companions = sorted(p.name for p in inter.iterdir() if "_rejected" in p.name)
    check(
        companions == ["iteration_1_rejected.txt", "iteration_2_rejected.txt"],
        "one rejected .txt per refused iteration, none for generation",
        str(companions),
    )
    check(
        (inter / "iteration_1_rejected.txt").read_text(encoding="utf-8") == GARBAGE,
        "the companion file holds the refused response",
    )

    print("\n  With the gate DISABLED (pre-fix behaviour, identical responses):")
    pre_report, _, _ = _run_cli(root, "a_gate_off", [invalid, GARBAGE, GARBAGE], gate_live=False)
    pre = pre_report["candidates"][0]
    check(
        pre["final_code"].strip() == GARBAGE,
        "pre-fix: the contract is DESTROYED — final_code is the garbage",
        f"{len(pre['final_code'])} chars",
    )
    # Narrative, not an oracle: the two checks above already pin both sides
    # exactly, so any ratio assertion here could only fail after one of them has.
    print(
        f"    -> gate live keeps {len(cand['final_code'])} chars; "
        f"gate off keeps {len(pre['final_code'])}"
    )


def _trajectory_recovers(root: Path, check: Checks, invalid: str, valid: str) -> None:
    """Model refuses once, then recovers: the retry must build on the retained code."""
    print("\n=== Trajectory B — model refuses once, then recovers ===")
    print("    gen -> 1-error contract | corr1 -> garbage | corr2 -> clean contract\n")
    print("  With the gate LIVE:")

    report, _, adapter = _run_cli(root, "b_recovers", [invalid, GARBAGE, valid], gate_live=True)
    cand = report["candidates"][0]
    hist = cand["error_history"]

    check(cand["converged"] is True, "converged after recovering from the refusal")
    check(cand["final_code"].strip() == valid.strip(), "final_code is the clean contract")
    used = cand["iterations_used"]
    check(used == 2, "the refused iteration still counts toward iterations_used", str(used))
    check(_errors(hist[0]) >= 1, "generation really did carry an ERROR (JAR-verified)")
    check(_errors(hist[2]) == 0, "the final iteration is ERROR-free (JAR-verified)")

    # prompts[2] is the second correction prompt. `endContrct` is the deliberate
    # typo in invalid.symboleo, so its presence proves the retry was built from
    # the retained contract rather than from the response that was refused.
    retry_prompt = adapter.prompts[2]
    check("endContrct" in retry_prompt, "the retry prompt was built from the RETAINED contract")
    check(GARBAGE not in retry_prompt, "the refused garbage never reached the retry prompt")


def main() -> int:
    invalid = (FIXTURES / "invalid.symboleo").read_text(encoding="utf-8")
    valid = (FIXTURES / "valid.symboleo").read_text(encoding="utf-8")

    check = Checks()
    root = Path(tempfile.mkdtemp(prefix="symboleo-smoke-"))
    _trajectory_stuck(root, check, invalid)
    _trajectory_recovers(root, check, invalid, valid)

    print("\n" + "=" * 62)
    print(f"{check.total - len(check.failed)}/{check.total} checks passed")
    if check.failed:
        print("\nFAILED:")
        for label in check.failed:
            print(f"  - {label}")
    print(f"\nArtifacts kept for inspection: {root}")
    return 1 if check.failed else 0


if __name__ == "__main__":
    sys.exit(main())
