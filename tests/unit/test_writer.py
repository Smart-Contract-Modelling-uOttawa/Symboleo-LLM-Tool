import json
from datetime import datetime
from pathlib import Path

import yaml

from symboleo_llm_tool.config.models import LLMConfig, OutputConfig, PipelineConfig, StageConfig
from symboleo_llm_tool.output.models import CandidateResult, IterationRecord, PipelineResult
from symboleo_llm_tool.output.writer import write_results
from tests.helpers import make_issue


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
