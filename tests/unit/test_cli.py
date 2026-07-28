from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from symboleo_llm_tool.cli.main import _format_progress, app
from symboleo_llm_tool.output.models import (
    CandidateResult,
    ExperimentResult,
    IterationRecord,
    PipelineResult,
    SuiteResult,
)
from tests.helpers import make_issue

runner = CliRunner()

_RUN_YAML = """
generation:
  llm: {provider: openai, model: gpt-4o-mini}
  strategy: zero_shot
correction:
  llm: {provider: openai, model: gpt-4o-mini}
  strategy: zero_shot
"""

_SUITE_YAML = """
experiments:
  - name: zero-shot
    config:
      generation:
        llm: {provider: openai, model: gpt-4o-mini}
        strategy: zero_shot
      correction:
        llm: {provider: openai, model: gpt-4o-mini}
        strategy: zero_shot
  - name: cot
    config:
      generation:
        llm: {provider: openai, model: gpt-4o-mini}
        strategy: cot
      correction:
        llm: {provider: openai, model: gpt-4o-mini}
        strategy: zero_shot
"""


def _fake_suite_result(names: list[str]) -> SuiteResult:
    return SuiteResult(
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        input_file="contract.txt",
        experiments=[
            ExperimentResult(
                name=name,
                result=PipelineResult(
                    success=True,
                    timestamp=datetime(2026, 1, 1, 12, 0, 0),
                    input_file="contract.txt",
                    candidates=[
                        CandidateResult(
                            candidate_id=0,
                            final_code="Contract C() {}",
                            converged=True,
                            iterations_used=1,
                            error_history=[],
                        )
                    ],
                ),
            )
            for name in names
        ],
    )


def test_generation_with_errors():
    msg = _format_progress(0, 0, [make_issue(message="err")], num_candidates=1, max_iterations=3)
    assert "Generated" in msg
    assert "1 error(s)" in msg
    # "remaining" belongs to correction iterations — nothing has been worked
    # down yet at generation.
    assert "remaining" not in msg


def test_generation_with_errors_and_warnings():
    issues = [make_issue(message="e"), make_issue(severity="WARNING", message="w")]
    msg = _format_progress(0, 0, issues, num_candidates=1, max_iterations=3)
    assert "Generated — 1 error(s), 1 warning(s)" in msg


def test_generation_converged_with_warnings():
    issues = [make_issue(severity="WARNING"), make_issue(severity="WARNING")]
    msg = _format_progress(0, 0, issues, num_candidates=1, max_iterations=3)
    assert "Generated — converged (2 warning(s))" in msg


def test_generation_converged():
    msg = _format_progress(0, 0, [], num_candidates=1, max_iterations=3)
    assert "Generated" in msg
    assert "converged" in msg


def test_correction_with_errors_remaining():
    errors = [make_issue(message="err"), make_issue(message="err")]
    msg = _format_progress(0, 2, errors, num_candidates=1, max_iterations=3)
    assert "Correction 2/3" in msg
    assert "2 error(s) remaining" in msg


def test_correction_converged():
    msg = _format_progress(0, 1, [], num_candidates=1, max_iterations=3)
    assert "Correction 1/3" in msg
    assert "converged" in msg


def test_correction_with_errors_and_warnings():
    # "remaining" belongs to the error count — the loop never targets warnings.
    issues = [make_issue(message="e"), make_issue(severity="WARNING", message="w")]
    msg = _format_progress(0, 1, issues, num_candidates=1, max_iterations=3)
    assert "1 error(s) remaining, 1 warning(s)" in msg


def test_correction_converged_with_warnings():
    # Warnings alone don't block, but the label must not pretend the output is
    # spotless.
    issues = [make_issue(severity="WARNING"), make_issue(severity="WARNING")]
    msg = _format_progress(0, 1, issues, num_candidates=1, max_iterations=3)
    assert "converged (2 warning(s))" in msg


def test_multi_candidate_shows_prefix():
    msg = _format_progress(1, 0, [], num_candidates=3, max_iterations=3)
    assert "Candidate 2/3" in msg


def test_single_candidate_no_prefix():
    msg = _format_progress(0, 0, [], num_candidates=1, max_iterations=3)
    assert "Candidate" not in msg


def test_suite_command_loads_runs_and_reports(tmp_path: Path) -> None:
    contract = tmp_path / "contract.txt"
    contract.write_text("Seller shall deliver the goods.", encoding="utf-8")
    config = tmp_path / "suite.yaml"
    config.write_text(_SUITE_YAML, encoding="utf-8")

    with (
        patch(
            "symboleo_llm_tool.cli.main.run_suite",
            return_value=_fake_suite_result(["zero-shot", "cot"]),
        ) as mock_run,
        patch(
            "symboleo_llm_tool.cli.main.write_suite_results",
            return_value=tmp_path / "output" / "suite_x",
        ) as mock_write,
    ):
        result = runner.invoke(app, ["suite", str(contract), "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert "zero-shot" in result.output
    assert "cot" in result.output
    # The loader bound the CLI contract and handed it to run_suite.
    suite_arg = mock_run.call_args.args[0]
    assert suite_arg.contract_text == "Seller shall deliver the goods."
    mock_write.assert_called_once()


def test_run_command_reports_the_candidate_warning_count(tmp_path: Path) -> None:
    # The only test that exercises the `run` command's summary table; without it
    # the Warnings column could be deleted with the suite still green. 4 warnings
    # is distinct from every other number the table prints (candidate 1, 1
    # iteration), so the assertion cannot pass on a neighbouring cell.
    contract = tmp_path / "contract.txt"
    contract.write_text("Seller shall deliver the goods.", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(_RUN_YAML, encoding="utf-8")
    result_with_warnings = PipelineResult(
        success=True,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        input_file="contract.txt",
        candidates=[
            CandidateResult(
                candidate_id=0,
                final_code="Contract C() {}",
                converged=True,
                iterations_used=1,
                error_history=[
                    IterationRecord(
                        iteration=0,
                        code="",
                        errors=[make_issue(severity="WARNING") for _ in range(4)],
                        usage=None,
                    )
                ],
            )
        ],
    )

    with (
        patch("symboleo_llm_tool.cli.main.run_pipeline", return_value=result_with_warnings),
        patch(
            "symboleo_llm_tool.cli.main.write_results",
            return_value=tmp_path / "output" / "run_x",
        ),
    ):
        result = runner.invoke(app, ["run", str(contract), "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert "Warnings" in result.output
    assert "4" in result.output


def test_suite_command_errors_on_missing_contract(tmp_path: Path) -> None:
    config = tmp_path / "suite.yaml"
    config.write_text(_SUITE_YAML, encoding="utf-8")

    result = runner.invoke(app, ["suite", str(tmp_path / "nope.txt"), "--config", str(config)])

    assert result.exit_code == 1
    assert "not found" in result.output
