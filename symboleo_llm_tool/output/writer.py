import csv
import io
import re
from pathlib import Path

import yaml

from symboleo_llm_tool.config.loader import dump_suite_file
from symboleo_llm_tool.config.models import PipelineConfig, SuiteConfig
from symboleo_llm_tool.output.models import PipelineResult, SuiteResult


def _write_run(result: PipelineResult, config: PipelineConfig, dest_dir: Path) -> None:
    """Write one pipeline run's artifacts into ``dest_dir`` (which must exist).

    Factored out of ``write_results`` so the single-run writer (a timestamped
    directory) and the suite writer (a per-experiment subdirectory) share one
    definition of the core layout. Callers add what differs: ``write_results``
    a per-run ``contract.txt``, the suite writer one shared copy at suite level.
    """
    (dest_dir / "report.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    config_yaml = yaml.dump(
        config.model_dump(mode="json"), default_flow_style=False, sort_keys=False
    )
    (dest_dir / "config.yaml").write_text(config_yaml, encoding="utf-8")

    multi = len(result.candidates) > 1
    for candidate in result.candidates:
        suffix = f"_candidate_{candidate.candidate_id}" if multi else ""
        # A candidate whose first call failed has no code; writing the empty
        # string would leave a file a downstream `*.symboleo` glob reads as a
        # contract. Same reasoning as the `_rejected.txt` extension below.
        if candidate.final_code:
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
                if record.rejected_response is not None:
                    # The .symboleo above duplicates the previous iteration —
                    # true, but on its own indistinguishable from a correction
                    # that changed nothing. `.txt`, not `.symboleo`: the content
                    # is by definition not a contract and must not be picked up
                    # by a downstream *.symboleo glob.
                    (inter_dir / f"iteration_{record.iteration}_rejected.txt").write_text(
                        record.rejected_response, encoding="utf-8"
                    )


def _unique_dir(parent: Path, base_name: str) -> Path:
    """Create and return ``parent/base_name``, suffixing ``_2``, ``_3``, … on
    collision.

    Directory names are second-granular timestamps, so two runs finishing within
    the same second would otherwise share a directory and silently interleave
    their files (report.json last-writer-wins). ``mkdir`` without ``exist_ok``
    is the atomic claim — race-safe across threads and processes.
    """
    parent.mkdir(parents=True, exist_ok=True)
    candidate = parent / base_name
    n = 2
    while True:
        try:
            candidate.mkdir()
        except FileExistsError:
            candidate = parent / f"{base_name}_{n}"
            n += 1
        else:
            return candidate


def write_results(
    result: PipelineResult, config: PipelineConfig, *, contract_text: str | None = None
) -> Path:
    timestamp = result.timestamp.strftime("%Y%m%d_%H%M%S")
    run_dir = _unique_dir(config.output.directory, f"run_{timestamp}")
    _write_run(result, config, run_dir)
    if contract_text is not None:
        (run_dir / "contract.txt").write_text(contract_text, encoding="utf-8")
    return run_dir


def write_suite_results(result: SuiteResult, suite: SuiteConfig) -> Path:
    """Persist a suite run: a suite directory holding a suite-level report, a
    reloadable copy of the suite file, the input contract, a comparison CSV, and
    one subdirectory per experiment (each in the single-run layout).
    """
    timestamp = result.timestamp.strftime("%Y%m%d_%H%M%S")
    suite_dir = _unique_dir(suite.output_directory, f"suite_{timestamp}")

    (suite_dir / "suite_report.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    # Not `minimal`: this is the record of a run, so it keeps values that merely
    # happen to equal a current default (see dump_suite_file).
    (suite_dir / "suite.yaml").write_text(dump_suite_file(suite), encoding="utf-8")
    # One suite-level copy (the experiments share one contract by design) —
    # together with suite.yaml this makes the directory directly replayable:
    # `symboleo-tool suite contract.txt --config suite.yaml`.
    (suite_dir / "contract.txt").write_text(suite.contract_text, encoding="utf-8")
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


def _summary_csv(result: SuiteResult) -> str:
    """Comparison CSV, mirroring the frontend's ``buildSummaryCsv`` columns exactly."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "experiment",
            "converged",
            "iterations_to_convergence",
            "failed_candidates",
            "total_tokens",
            "cost_usd",
        ]
    )
    for exp in result.experiments:
        r = exp.result
        writer.writerow(
            [
                exp.name,
                "true" if r.success else "false",
                "" if r.iterations_to_convergence is None else r.iterations_to_convergence,
                r.failed_candidate_count,
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
