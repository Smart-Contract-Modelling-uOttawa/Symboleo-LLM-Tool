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


def test_write_results_uniquifies_a_colliding_directory(tmp_path: Path) -> None:
    # Timestamps are second-granular, so two back-to-back runs can share a name.
    # The second must land in a suffixed sibling — never interleave into the
    # first, where report.json would silently be last-writer-wins.
    first = write_results(_result(), _config(tmp_path))
    (first / "marker.txt").write_text("first", encoding="utf-8")

    second = write_results(_result(), _config(tmp_path))
    third = write_results(_result(), _config(tmp_path))

    assert first.name == "run_20260101_120000"
    assert second.name == "run_20260101_120000_2"
    assert third.name == "run_20260101_120000_3"
    assert (first / "marker.txt").read_text(encoding="utf-8") == "first"
    assert not (second / "marker.txt").exists()


def test_write_results_persists_contract_text_when_provided(tmp_path: Path) -> None:
    run_dir = write_results(_result(), _config(tmp_path), contract_text="Seller shall deliver.")

    assert (run_dir / "contract.txt").read_text(encoding="utf-8") == "Seller shall deliver."


def test_write_results_omits_contract_file_when_text_not_provided(tmp_path: Path) -> None:
    run_dir = write_results(_result(), _config(tmp_path))

    assert not (run_dir / "contract.txt").exists()


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


def test_write_results_saves_a_rejected_response_beside_the_duplicate_iteration(
    tmp_path: Path,
) -> None:
    # A refused correction retains the previous code, so its .symboleo duplicates
    # its predecessor. Without the companion file, diffing the intermediates
    # directory — the entire point of save_intermediates — cannot tell a refusal
    # from a correction that changed nothing.
    error = make_issue(message="err")
    result = PipelineResult(
        success=False,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        input_file="test.txt",
        candidates=[
            CandidateResult(
                candidate_id=0,
                final_code="bad code",
                converged=False,
                iterations_used=1,
                error_history=[
                    IterationRecord(iteration=0, code="bad code", errors=[error]),
                    IterationRecord(
                        iteration=1,
                        code="bad code",
                        errors=[error],
                        rejected_response="I cannot fix this.",
                    ),
                ],
            )
        ],
    )

    run_dir = write_results(result, _config(tmp_path, save_intermediates=True))

    inter_dir = run_dir / "intermediates"
    assert (inter_dir / "iteration_1.symboleo").read_text(encoding="utf-8") == "bad code"
    assert (inter_dir / "iteration_1_rejected.txt").read_text(encoding="utf-8") == (
        "I cannot fix this."
    )
    # `.txt`, so a downstream *.symboleo glob never picks up a non-contract.
    assert not (inter_dir / "iteration_1_rejected.symboleo").exists()
    assert not (inter_dir / "iteration_0_rejected.txt").exists()


def _prompt_result(*, num_candidates: int = 1, with_prompts: bool = True) -> PipelineResult:
    def history(candidate: int) -> list[IterationRecord]:
        return [
            IterationRecord(
                iteration=0,
                code="bad code",
                errors=[make_issue()],
                prompt=f"GEN PROMPT c{candidate}" if with_prompts else None,
            ),
            IterationRecord(
                iteration=1,
                code="Contract Fixed() {}",
                errors=[],
                prompt=f"CORR PROMPT c{candidate}" if with_prompts else None,
            ),
        ]

    return PipelineResult(
        success=True,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        input_file="test.txt",
        candidates=[
            CandidateResult(
                candidate_id=i,
                final_code="Contract Fixed() {}",
                converged=True,
                iterations_used=1,
                error_history=history(i),
            )
            for i in range(num_candidates)
        ],
    )


def test_write_results_saves_prompts_even_without_intermediates(tmp_path: Path) -> None:
    # Prompts are always on — not gated behind save_intermediates — because the
    # rendered prompt is not otherwise recoverable from the artifact.
    run_dir = write_results(_prompt_result(), _config(tmp_path, save_intermediates=False))

    prompts_dir = run_dir / "prompts"
    assert (prompts_dir / "iteration_0_prompt.txt").read_text(encoding="utf-8") == "GEN PROMPT c0"
    assert (prompts_dir / "iteration_1_prompt.txt").read_text(encoding="utf-8") == "CORR PROMPT c0"
    assert not (run_dir / "intermediates").exists()


def test_write_results_multi_candidate_prompts_use_suffix(tmp_path: Path) -> None:
    run_dir = write_results(_prompt_result(num_candidates=2), _config(tmp_path))

    assert (run_dir / "prompts_candidate_0" / "iteration_0_prompt.txt").read_text(
        encoding="utf-8"
    ) == "GEN PROMPT c0"
    assert (run_dir / "prompts_candidate_1" / "iteration_1_prompt.txt").read_text(
        encoding="utf-8"
    ) == "CORR PROMPT c1"
    assert not (run_dir / "prompts").exists()


def test_write_results_writes_no_prompts_dir_for_pre_prompt_era_records(tmp_path: Path) -> None:
    # A result reloaded from an archived report carries no prompts; an empty
    # prompts/ directory would misread as "this run sent empty prompts".
    run_dir = write_results(_prompt_result(with_prompts=False), _config(tmp_path))

    assert not (run_dir / "prompts").exists()


def test_prompt_never_reaches_report_json(tmp_path: Path) -> None:
    # `IterationRecord.prompt` is serialization-excluded: report.json travels
    # whole in the terminal SSE event, and grammar-bearing prompts are an order
    # of magnitude larger than the code the report already carries. The files
    # written beside it are the prompts' only home.
    run_dir = write_results(_prompt_result(), _config(tmp_path))

    raw = (run_dir / "report.json").read_text(encoding="utf-8")
    assert "GEN PROMPT c0" not in raw
    report = json.loads(raw)
    # Key-level too — "prompt" must not appear even as null (usage's
    # prompt_tokens is a different key and untouched).
    assert "prompt" not in report["candidates"][0]["error_history"][0]


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


def test_write_suite_uniquifies_a_colliding_directory(tmp_path: Path) -> None:
    first = write_suite_results(_suite_result(), _suite(tmp_path))

    second = write_suite_results(_suite_result(), _suite(tmp_path))

    assert first.name == "suite_20260101_120000"
    assert second.name == "suite_20260101_120000_2"


def test_write_suite_persists_one_top_level_contract(tmp_path: Path) -> None:
    suite_dir = write_suite_results(_suite_result(), _suite(tmp_path))

    contract = (suite_dir / "contract.txt").read_text(encoding="utf-8")
    assert contract == "Seller shall deliver the goods."
    # One suite-level copy only: the experiments share one contract by design,
    # and `suite contract.txt --config suite.yaml` replays the whole directory.
    assert not (suite_dir / "0_zero-shot" / "contract.txt").exists()


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
    assert (
        lines[0]
        == "experiment,converged,iterations_to_convergence,failed_candidates,total_tokens,cost_usd"
    )
    # Derived from the fixture: converged → "true" and the candidate's
    # iterations_used (2); no candidate was cut short, so 0; tokens are prompt +
    # completion (30 + 12).
    assert lines[1] == "zero-shot,true,2,0,42,0.005"
    # Not converged → "false", an empty iterations cell, and an empty cost cell
    # (None means "not reported", which is distinct from 0.0). The 0 in
    # failed_candidates is what separates this from an experiment whose
    # candidates all died on a provider timeout.
    assert lines[2] == "cot run,false,,0,87,"
    assert len(lines) == 3  # header + 2 experiments


def test_failed_candidate_with_no_code_writes_no_symboleo_file(tmp_path: Path) -> None:
    # An empty final_code means the first call died before producing anything.
    # Writing it would leave a 0-byte file that a `*.symboleo` glob reads as a
    # contract — the same hazard the rejected-response `.txt` extension avoids.
    result = PipelineResult(
        success=False,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        input_file="test.txt",
        candidates=[
            CandidateResult(
                candidate_id=0,
                final_code="",
                converged=False,
                iterations_used=0,
                error_history=[],
                failure="Timeout: provider died",
            )
        ],
    )
    run_dir = write_results(result, _config(tmp_path))

    assert not (run_dir / "contract_final.symboleo").exists()
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["candidates"][0]["failure"] == "Timeout: provider died"
