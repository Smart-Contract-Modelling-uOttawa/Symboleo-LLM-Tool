import os
from pathlib import Path
from typing import NoReturn

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from symboleo_llm_tool.config.loader import load_config, load_suite_config
from symboleo_llm_tool.experiments import run_suite
from symboleo_llm_tool.llm.compatibility import pipeline_param_warnings, suite_param_warnings
from symboleo_llm_tool.output.writer import write_results, write_suite_results
from symboleo_llm_tool.pipeline import run as run_pipeline
from symboleo_llm_tool.symboleo.models import SymboleoIssue

try:
    from langsmith import Client as _LangSmithClient
except ImportError:
    _LangSmithClient = None  # type: ignore[misc, assignment]

load_dotenv()

app = typer.Typer(help="LLM-assisted SymboleoAC contract generation and correction.")
console = Console()


def _fatal(message: str) -> NoReturn:
    console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(1)


def _enable_langsmith(project: str) -> None:
    """Turn on LangSmith tracing for the process. Fatal if the flag is set but the
    optional package is absent — a config error, distinct from a runtime flush
    failure (see ``_flush_langsmith``). Shared by the ``run`` and ``suite`` commands.
    """
    if _LangSmithClient is None:
        _fatal("langsmith is not installed but LangSmith observability is enabled")
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_PROJECT"] = project


def _flush_langsmith() -> None:
    """Best-effort flush of buffered traces; a failure here warns but never fails
    the run (the results are already written)."""
    try:
        _LangSmithClient().flush()
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] LangSmith flush failed: {e}")


def _format_progress(
    candidate_id: int,
    iteration: int,
    errors: list[SymboleoIssue],
    num_candidates: int,
    max_iterations: int,
) -> str:
    prefix = (
        f"[bold]Candidate {candidate_id + 1}/{num_candidates}[/bold] " if num_candidates > 1 else ""
    )
    stage = "Generated" if iteration == 0 else f"Correction {iteration}/{max_iterations}"
    error_count = sum(1 for e in errors if e.is_error)
    warning_count = len(errors) - error_count
    if error_count:
        # "remaining" attaches to the error count alone — the loop works errors
        # down; warnings are reported, never targeted.
        body = f"{error_count} error(s)" + (" remaining" if iteration else "")
        if warning_count:
            body += f", {warning_count} warning(s)"
    elif warning_count:
        body = f"converged ({warning_count} warning(s))"
    else:
        body = "converged"
    return f"{prefix}{stage} — {body}"


@app.command()
def run(
    input_file: Path = typer.Argument(..., help="Path to the .txt legal contract"),
    config_file: Path = typer.Option(..., "--config", "-c", help="Path to YAML config file"),
) -> None:
    if not input_file.exists():
        _fatal(f"Input file not found: {input_file}")
    if not config_file.exists():
        _fatal(f"Config file not found: {config_file}")

    try:
        config = load_config(config_file)
    except Exception as e:
        _fatal(f"Config error: {e}")

    for warning in pipeline_param_warnings(config):
        console.print(f"[yellow]Warning:[/yellow] {warning}")

    try:
        contract_text = input_file.read_text(encoding="utf-8")
    except Exception as e:
        _fatal(f"Could not read input file: {e}")

    def _progress(
        candidate_id: int,
        iteration: int,
        errors: list[SymboleoIssue],
        num_candidates: int,
        max_iterations: int,
    ) -> None:
        console.print(
            "  " + _format_progress(candidate_id, iteration, errors, num_candidates, max_iterations)
        )

    if config.observability.langsmith.enabled:
        _enable_langsmith(config.observability.langsmith.project)

    console.print("[bold green]Running pipeline...[/bold green]")
    try:
        result = run_pipeline(contract_text, config, str(input_file), on_progress=_progress)
    except Exception as e:
        _fatal(str(e))

    try:
        run_dir = write_results(result, config)
    except Exception as e:
        _fatal(f"Could not write results: {e}")

    status = "[green]Success[/green]" if result.success else "[red]Failed to converge[/red]"
    console.print(f"\n[bold]Result:[/bold] {status}")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Candidate")
    table.add_column("Converged")
    table.add_column("Iterations Used")
    table.add_column("Warnings")

    for c in result.candidates:
        table.add_row(
            str(c.candidate_id + 1),
            "[green]Yes[/green]" if c.converged else "[red]No[/red]",
            str(c.iterations_used),
            str(c.final_warning_count),
        )

    console.print(table)

    num_candidates = config.pipeline.num_candidates
    if config.pipeline.stop_on_first_convergence and len(result.candidates) < num_candidates:
        skipped = num_candidates - len(result.candidates)
        console.print(
            f"Stopped after first convergence — {skipped} candidate(s) skipped.",
            style="dim",
        )

    console.print(f"\n[dim]Output written to: {run_dir}[/dim]")

    if config.observability.langsmith.enabled:
        _flush_langsmith()


@app.command()
def suite(
    input_file: Path = typer.Argument(..., help="Path to the .txt legal contract"),
    config_file: Path = typer.Option(..., "--config", "-c", help="Path to suite YAML config file"),
) -> None:
    """Run one contract against several named experiment configs and compare them."""
    if not input_file.exists():
        _fatal(f"Input file not found: {input_file}")
    if not config_file.exists():
        _fatal(f"Config file not found: {config_file}")

    try:
        contract_text = input_file.read_text(encoding="utf-8")
    except Exception as e:
        _fatal(f"Could not read input file: {e}")

    try:
        suite_config = load_suite_config(config_file, contract_text)
    except Exception as e:
        _fatal(f"Config error: {e}")

    # Per-experiment param warnings, from the same (name, warning) source the API
    # uses; the CLI just formats the pair with Rich markup.
    for name, warning in suite_param_warnings(suite_config):
        console.print(f"[yellow]Warning:[/yellow] [{name}] {warning}")

    # Observability is per-experiment; the LangSmith env is process-global, so
    # enable it once if any experiment opts in (project from the first such).
    traced = [e for e in suite_config.experiments if e.config.observability.langsmith.enabled]
    if traced:
        _enable_langsmith(traced[0].config.observability.langsmith.project)

    names = [e.name for e in suite_config.experiments]

    def _progress(
        experiment_index: int,
        candidate_id: int,
        iteration: int,
        errors: list[SymboleoIssue],
        num_candidates: int,
        max_iterations: int,
    ) -> None:
        # Thin, thread-safe append print. With max_concurrency > 1 this fires from
        # worker threads and lines interleave in time — accepted by design. We do
        # NOT buffer or reorder (that would re-coordinate concurrency at the wrong
        # altitude); Rich's Console lock keeps each line intact.
        label = _format_progress(candidate_id, iteration, errors, num_candidates, max_iterations)
        console.print(f"  [cyan]{names[experiment_index]}[/cyan] · {label}")

    console.print(f"[bold green]Running suite...[/bold green] ({len(names)} experiments)")
    try:
        result = run_suite(suite_config, input_file=str(input_file), on_progress=_progress)
    except Exception as e:
        _fatal(str(e))

    try:
        suite_dir = write_suite_results(result, suite_config)
    except Exception as e:
        _fatal(f"Could not write results: {e}")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Experiment")
    table.add_column("Converged")
    table.add_column("Iters→conv")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost (USD)", justify="right")
    for exp in result.experiments:
        r = exp.result
        itc = "-" if r.iterations_to_convergence is None else str(r.iterations_to_convergence)
        cost = "-" if r.total_cost_usd is None else f"${r.total_cost_usd:.4f}"
        table.add_row(
            exp.name,
            "[green]Yes[/green]" if r.success else "[red]No[/red]",
            itc,
            f"{r.total_tokens:,}",
            cost,
        )
    console.print(table)
    console.print(f"\n[dim]Output written to: {suite_dir}[/dim]")

    if traced:
        _flush_langsmith()


def main() -> None:
    app()
