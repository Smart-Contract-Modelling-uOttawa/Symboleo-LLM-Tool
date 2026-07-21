import json
from datetime import datetime
from pathlib import Path

import yaml

from symboleo_llm_tool.config.models import (
    Experiment,
    LLMConfig,
    OutputConfig,
    PipelineConfig,
    StageConfig,
    SuiteConfig,
)
from symboleo_llm_tool.output.models import (
    CandidateResult,
    ExperimentResult,
    IterationRecord,
    PipelineResult,
    SuiteResult,
)
from symboleo_llm_tool.output.writer import write_results, write_suite_results
from tests.helpers import make_issue, make_usage


def _stage() -> StageConfig:
    return StageConfig(llm=LLMConfig(provider="openai", model="gpt-4o-mini"), strategy="zero_shot")


def _config(tmp_path: Path, *, save_intermediates: bool = False) -> PipelineConfig:
    return PipelineConfig(
        generation=_stage(),
        correction=_stage(),
        output=OutputConfig(directory=tmp_path / "output", save_intermediates=save_intermediates),
    )


def _result(*, num_candidates: int = 1) -> PipelineResult:
    return PipelineResult(
        success=True,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        input_file="test.txt",
        candidates=[
            CandidateResult(
                candidate_id=i,
                final_code=f"Contract C{i}() {{}}",
                converged=True,
                iterations_used=0,
                error_history=[],
            )
            for i in range(num_candidates)
        ],
    )


def test_write_results_creates_timestamped_directory(tmp_path: Path) -> None:
    run_dir = write_results(_result(), _config(tmp_path))
    assert run_dir.name == "run_20260101_120000"


def test_write_results_writes_report_and_config(tmp_path: Path) -> None:
    run_dir = write_results(_result(), _config(tmp_path))

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["success"] is True
    config_data = yaml.safe_load((run_dir / "config.yaml").read_text(encoding="utf-8"))
    assert config_data["generation"]["strategy"] == "zero_shot"


def test_write_results_single_candidate_no_suffix(tmp_path: Path) -> None:
    run_dir = write_results(_result(num_candidates=1), _config(tmp_path))

    assert (run_dir / "contract_final.symboleo").exists()
    assert not (run_dir / "contract_candidate_0_final.symboleo").exists()


def test_write_results_multi_candidate_uses_suffix(tmp_path: Path) -> None:
    run_dir = write_results(_result(num_candidates=2), _config(tmp_path))

    assert (run_dir / "contract_candidate_0_final.symboleo").exists()
    assert (run_dir / "contract_candidate_1_final.symboleo").exists()
    assert not (run_dir / "contract_final.symboleo").exists()


def test_write_results_saves_intermediates_when_enabled(tmp_path: Path) -> None:
    error = make_issue(message="err")
    result = PipelineResult(
        success=True,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        input_file="test.txt",
        candidates=[
            CandidateResult(
                candidate_id=0,
                final_code="Contract Fixed() {}",
                converged=True,
                iterations_used=1,
                error_history=[
                    IterationRecord(iteration=0, code="bad code", errors=[error]),
                    IterationRecord(iteration=1, code="Contract Fixed() {}", errors=[]),
                ],
            )
        ],
    )

    run_dir = write_results(result, _config(tmp_path, save_intermediates=True))

    inter_dir = run_dir / "intermediates"
    assert (inter_dir / "iteration_0.symboleo").read_text(encoding="utf-8") == "bad code"
    assert (inter_dir / "iteration_1.symboleo").read_text(encoding="utf-8") == "Contract Fixed() {}"


def _suite(tmp_path: Path) -> SuiteConfig:
    return SuiteConfig(
        contract_text="Seller shall deliver the goods.",
        experiments=[
            Experiment(name="zero-shot", config=_config(tmp_path)),
            Experiment(name="cot run", config=_config(tmp_path)),  # space → slugged dir
        ],
    )


def _experiment_result(
    name: str,
    *,
    converged: bool,
    iterations_used: int,
    prompt: int,
    completion: int,
    cost: float | None,
) -> ExperimentResult:
    return ExperimentResult(
        name=name,
        result=PipelineResult(
            success=converged,
            timestamp=datetime(2026, 1, 1, 12, 0, 0),
            input_file="test.txt",
            candidates=[
                CandidateResult(
                    candidate_id=0,
                    final_code="Contract C0() {}",
                    converged=converged,
                    iterations_used=iterations_used,
                    error_history=[
                        IterationRecord(
                            iteration=0,
                            code="",
                            errors=[],
                            usage=make_usage(
                                prompt_tokens=prompt, completion_tokens=completion, cost_usd=cost
                            ),
                        )
                    ],
                )
            ],
        ),
    )


def _suite_result() -> SuiteResult:
    # Every CSV cell differs from every other, and the two rows exercise opposite
    # branches of both conditional columns (a value vs. the empty-cell fallback),
    # so a column swap or a wrong branch fails the exact-row assertions.
    return SuiteResult(
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        input_file="test.txt",
        experiments=[
            _experiment_result(
                "zero-shot", converged=True, iterations_used=2, prompt=30, completion=12, cost=0.005
            ),
            _experiment_result(
                "cot run", converged=False, iterations_used=4, prompt=80, completion=7, cost=None
            ),
        ],
    )


def test_write_suite_creates_suite_dir_with_reports(tmp_path: Path) -> None:
    suite_dir = write_suite_results(_suite_result(), _suite(tmp_path))

    assert suite_dir.name == "suite_20260101_120000"
    assert (suite_dir / "suite_report.json").exists()
    assert (suite_dir / "suite.yaml").exists()
    assert (suite_dir / "summary.csv").exists()


def test_write_suite_creates_per_experiment_subdirs(tmp_path: Path) -> None:
    suite_dir = write_suite_results(_suite_result(), _suite(tmp_path))

    # Index-prefixed, name-slugged, each in the single-run layout.
    assert (suite_dir / "0_zero-shot" / "report.json").exists()
    assert (suite_dir / "0_zero-shot" / "config.yaml").exists()
    assert (suite_dir / "0_zero-shot" / "contract_final.symboleo").exists()
    assert (suite_dir / "1_cot_run" / "contract_final.symboleo").exists()


def test_write_suite_yaml_is_reloadable_without_contract(tmp_path: Path) -> None:
    suite_dir = write_suite_results(_suite_result(), _suite(tmp_path))

    data = yaml.safe_load((suite_dir / "suite.yaml").read_text(encoding="utf-8"))
    assert "contract_text" not in data
    assert [e["name"] for e in data["experiments"]] == ["zero-shot", "cot run"]


def test_write_suite_summary_csv_mirrors_frontend_columns(tmp_path: Path) -> None:
    suite_dir = write_suite_results(_suite_result(), _suite(tmp_path))

    lines = (suite_dir / "summary.csv").read_text(encoding="utf-8").strip().split("\n")
    assert lines[0] == "experiment,converged,iterations_to_convergence,total_tokens,cost_usd"
    # Derived from the fixture: converged → "true" and the candidate's
    # iterations_used (2); tokens are prompt + completion (30 + 12).
    assert lines[1] == "zero-shot,true,2,42,0.005"
    # Not converged → "false", an empty iterations cell, and an empty cost cell
    # (None means "not reported", which is distinct from 0.0).
    assert lines[2] == "cot run,false,,87,"
    assert len(lines) == 3  # header + 2 experiments
