import csv
import io
import re
from pathlib import Path

import yaml

from symboleo_llm_tool.config.models import PipelineConfig, SuiteConfig
from symboleo_llm_tool.output.models import PipelineResult, SuiteResult


def _write_run(result: PipelineResult, config: PipelineConfig, dest_dir: Path) -> None:
    """Write one pipeline run's artifacts into ``dest_dir`` (which must exist).

    Factored out of ``write_results`` so both the single-run writer (a timestamped
    directory) and the suite writer (a per-experiment subdirectory) produce the
    identical on-disk layout from one definition.
    """
    (dest_dir / "report.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    config_yaml = yaml.dump(
        config.model_dump(mode="json"), default_flow_style=False, sort_keys=False
    )
    (dest_dir / "config.yaml").write_text(config_yaml, encoding="utf-8")

    multi = len(result.candidates) > 1
    for candidate in result.candidates:
        suffix = f"_candidate_{candidate.candidate_id}" if multi else ""
        (dest_dir / f"contract{suffix}_final.symboleo").write_text(
            candidate.final_code, encoding="utf-8"
        )

        if config.output.save_intermediates and candidate.error_history:
            inter_dir = dest_dir / f"intermediates{suffix}"
            inter_dir.mkdir(exist_ok=True)
            for record in candidate.error_history:
                (inter_dir / f"iteration_{record.iteration}.symboleo").write_text(
                    record.code, encoding="utf-8"
                )


def write_results(result: PipelineResult, config: PipelineConfig) -> Path:
    timestamp = result.timestamp.strftime("%Y%m%d_%H%M%S")
    run_dir = config.output.directory / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_run(result, config, run_dir)
    return run_dir


def write_suite_results(result: SuiteResult, suite: SuiteConfig) -> Path:
    """Persist a suite run: a suite directory holding a suite-level report, a
    reloadable copy of the suite file, a comparison CSV, and one subdirectory per
    experiment (each in the single-run layout).
    """
    timestamp = result.timestamp.strftime("%Y%m%d_%H%M%S")
    suite_dir = suite.output_directory / f"suite_{timestamp}"
    suite_dir.mkdir(parents=True, exist_ok=True)

    (suite_dir / "suite_report.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )
    (suite_dir / "suite.yaml").write_text(_suite_file_yaml(suite), encoding="utf-8")
    (suite_dir / "summary.csv").write_text(_summary_csv(result), encoding="utf-8")

    # Pair each result with its source config by name, not by position — no
    # dependency on run_suite preserving experiment order. The lookup is total:
    # run_suite builds every ExperimentResult from these same experiments, so each
    # result name is present, and names are unique per suite (SuiteConfig validator).
    specs = {experiment.name: experiment for experiment in suite.experiments}
    for index, experiment in enumerate(result.experiments):
        exp_dir = suite_dir / f"{index}_{_slug(experiment.name)}"
        exp_dir.mkdir(exist_ok=True)
        _write_run(experiment.result, specs[experiment.name].config, exp_dir)

    return suite_dir


def _suite_file_yaml(suite: SuiteConfig) -> str:
    """Dump the suite as the reloadable input-file schema — everything except the
    contract, which is supplied as a CLI argument (and rejected in the file).
    """
    data = suite.model_dump(mode="json")
    data.pop("contract_text", None)
    suite_yaml: str = yaml.dump(data, default_flow_style=False, sort_keys=False)
    return suite_yaml


def _summary_csv(result: SuiteResult) -> str:
    """Comparison CSV, mirroring the frontend's ``buildSummaryCsv`` columns exactly."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        ["experiment", "converged", "iterations_to_convergence", "total_tokens", "cost_usd"]
    )
    for exp in result.experiments:
        r = exp.result
        writer.writerow(
            [
                exp.name,
                "true" if r.success else "false",
                "" if r.iterations_to_convergence is None else r.iterations_to_convergence,
                r.total_tokens,
                "" if r.total_cost_usd is None else r.total_cost_usd,
            ]
        )
    return buf.getvalue()


def _slug(name: str) -> str:
    """Filesystem-safe experiment-name slug. Names are unique per suite; the caller
    also prefixes an index, so slug collisions cannot clobber a sibling directory.
    """
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return slug or "experiment"
