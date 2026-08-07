"""Manual smoke test for the failed-call gate (CLAUDE.md, Failed external calls).

Run from the repo root:  uv run python scripts/smoke_provider_failure.py

Exercises the CLI, config loader, pipeline, **real SymboleoAC JAR**, writer, and
`report.json` end to end. Only the LLM is faked, and necessarily so: a provider
timeout is an external event that cannot be provoked on demand. The scripted
trajectory mirrors the one observed on 2026-07-31 — a completed generation of a
draft the JAR rejects, then a `litellm.Timeout` on the first correction.

Two arms, so the data preserved is a measured contrast between real directories
rather than an assertion about intent: with the catch live the run writes its
artifact, and with it disabled the exception escapes and nothing reaches disk —
which is what every such run did before this change. Requires Java 17 on PATH.

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
from symboleo_llm_tool.llm.base import GenerationResult, LLMAdapter, LLMCallError
from symboleo_llm_tool.output.models import TokenUsage
from symboleo_llm_tool.pipeline import pipeline

REPO = Path(__file__).resolve().parent.parent

# A contract the JAR accepts, so the generation pass is real work worth losing.
VALID = (REPO / "tests" / "fixtures" / "valid.symboleo").read_text(encoding="utf-8")

# The message LiteLLM produced on 2026-07-31, wrapped as the adapter now wraps it.
TIMEOUT = "Timeout: CohereException - Connection timed out after 120.0 seconds"


class FailingAdapter(LLMAdapter):
    """Succeeds once, then raises — the shape that used to destroy the run."""

    def __init__(self, first_response: str) -> None:
        self._first = first_response
        self.calls = 0

    def generate(self, prompt: str) -> GenerationResult:
        self.calls += 1
        if self.calls > 1:
            raise LLMCallError(TIMEOUT)
        return GenerationResult(
            generated_text=self._first,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=10, cost_usd=0.001),
        )


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
        print(f"  [{mark}] {label}" + (f"  - {detail}" if detail else ""))


def _write_config(out_dir: Path) -> Path:
    """A real config file on disk, so the CLI's own loader is exercised.

    `provider: mock` is inert — `create_adapter` is patched before the CLI runs —
    and is the safe value to leave here: a *failed* patch degrades to the mock
    adapter rather than billing a real call.
    """
    cfg = {
        # A valid contract would converge in one pass and never reach the
        # correction call that fails, so the staged generation is deliberately
        # broken and max_iterations must allow a second call.
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


def _run_cli(root: Path, name: str, *, catch_live: bool) -> tuple[Path, int]:
    """Invoke the real CLI end to end; return its output dir and exit code."""
    out_dir = root / name
    cfg_path = _write_config(out_dir)
    contract = out_dir / "contract.txt"
    contract.write_text("Seller shall deliver the goods to Buyer.", encoding="utf-8")

    # A code the JAR reports errors on, so the loop reaches a correction call.
    broken = VALID.replace("endContract", "endContrct")
    adapter = FailingAdapter(broken)

    patches = [patch.object(pipeline, "create_adapter", lambda *a, **k: adapter)]
    if not catch_live:
        # Reproduce pre-fix behaviour by making the caught type unreachable.
        # Both ways this can rot are loud: a rename makes patch.object raise,
        # and a widened catch makes the control arm's checks fail.
        patches.append(patch.object(pipeline, "LLMCallError", _Unreachable))

    runner = CliRunner()
    with patches[0]:
        if len(patches) > 1:
            with patches[1]:
                result = runner.invoke(app, ["run", str(contract), "--config", str(cfg_path)])
        else:
            result = runner.invoke(app, ["run", str(contract), "--config", str(cfg_path)])
    return out_dir, result.exit_code


class _Unreachable(Exception):
    """A type nothing raises, so the pipeline's except never matches."""


def _run_dir(out_dir: Path) -> Path | None:
    dirs = sorted(p for p in out_dir.glob("run_*") if p.is_dir())
    return dirs[-1] if dirs else None


def main() -> int:
    check = Checks()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        print("\nArm A - catch live (the fix):")
        out_dir, exit_code = _run_cli(root, "live", catch_live=True)
        run_dir = _run_dir(out_dir)
        check(run_dir is not None, "a run directory was written")
        if run_dir is not None:
            report_path = run_dir / "report.json"
            check(report_path.exists(), "report.json exists")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            candidate = report["candidates"][0]
            check(
                candidate.get("failure") is not None and "timed out" in candidate["failure"],
                "the failure reason is recorded",
                str(candidate.get("failure"))[:60],
            )
            check(
                len(candidate["error_history"]) == 1,
                "the completed generation pass survived",
                f"{len(candidate['error_history'])} iteration(s)",
            )
            check(candidate["converged"] is False, "not reported as converged")
            check(candidate["iterations_used"] == 0, "iterations_used is not negative")
            check(
                candidate["total_tokens"] == 110,
                "the tokens already spent are still counted",
                str(candidate["total_tokens"]),
            )
            check(
                (run_dir / "intermediates").exists(),
                "intermediates for the completed pass are on disk",
            )
            check(exit_code == 0, "exit code 0 - the run produced an artifact")

        if check.failed:
            # Arm B only means something if arm A worked. Without this gate a
            # whole-stack breakage (no Java, missing JAR) prints arm B's checks
            # as PASS, since "no directory" is then true for the wrong reason.
            print("\nArm B - SKIPPED (arm A failed, so the contrast is meaningless)")
            print(f"\n{check.total - len(check.failed)}/{check.total} checks passed")
            print("FAILED: " + ", ".join(check.failed))
            return 1

        print("\nArm B - catch disabled (pre-fix behaviour):")
        out_dir_b, exit_code_b = _run_cli(root, "control", catch_live=False)
        run_dir_b = _run_dir(out_dir_b)
        check(
            run_dir_b is None,
            "no artifact at all - the contrast this change removes",
            "a directory WAS written; the arms are not distinguishing anything"
            if run_dir_b is not None
            else "",
        )
        check(exit_code_b != 0, "the CLI reported a fatal error", str(exit_code_b))

    print(f"\n{check.total - len(check.failed)}/{check.total} checks passed")
    if check.failed:
        print("FAILED: " + ", ".join(check.failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
