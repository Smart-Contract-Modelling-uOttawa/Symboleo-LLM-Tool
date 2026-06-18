from pathlib import Path

from symboleo_llm_tool.config.models import PipelineConfig
from symboleo_llm_tool.output.models import PipelineResult


def write_results(result: PipelineResult, config: PipelineConfig, config_path: Path) -> Path:
    timestamp = result.timestamp.strftime("%Y%m%d_%H%M%S")
    run_dir = config.output.directory / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "report.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )
    (run_dir / "config.yaml").write_text(
        config_path.read_text(encoding="utf-8"), encoding="utf-8"
    )

    multi = len(result.candidates) > 1
    for candidate in result.candidates:
        suffix = f"_candidate_{candidate.candidate_id}" if multi else ""
        (run_dir / f"contract{suffix}_final.symboleo").write_text(
            candidate.final_code, encoding="utf-8"
        )

        if config.output.save_intermediates and candidate.error_history:
            inter_dir = run_dir / f"intermediates{suffix}"
            inter_dir.mkdir(exist_ok=True)
            for record in candidate.error_history:
                (inter_dir / f"iteration_{record.iteration}.symboleo").write_text(
                    record.code, encoding="utf-8"
                )

    return run_dir
