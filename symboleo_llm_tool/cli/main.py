from pathlib import Path
from typing import NoReturn

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from symboleo_llm_tool.config.loader import load_config
from symboleo_llm_tool.output.writer import write_results
from symboleo_llm_tool.pipeline import pipeline
from symboleo_llm_tool.symboleo.models import SymboleoIssue

load_dotenv()

app = typer.Typer(help="LLM-assisted SymboleoAC contract generation and correction.")
console = Console()


def _fatal(message: str) -> NoReturn:
    console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(1)


@app.command()
def run(
    input_file: Path = typer.Argument(..., help="Path to the .txt legal contract"),
    config_file: Path = typer.Option(
        ..., "--config", "-c", help="Path to YAML config file"
    ),
) -> None:
    if not input_file.exists():
        _fatal(f"Input file not found: {input_file}")
    if not config_file.exists():
        _fatal(f"Config file not found: {config_file}")

    try:
        config = load_config(config_file)
    except Exception as e:
        _fatal(f"Config error: {e}")

    try:
        contract_text = input_file.read_text(encoding="utf-8")
    except Exception as e:
        _fatal(f"Could not read input file: {e}")

    num_candidates = config.pipeline.num_candidates
    max_iterations = config.pipeline.max_iterations

    def _progress(candidate_id: int, iteration: int, errors: list[SymboleoIssue]) -> None:
        prefix = (
            f"[bold]Candidate {candidate_id + 1}/{num_candidates}[/bold] "
            if num_candidates > 1
            else ""
        )
        if iteration == 0:
            console.print(f"  {prefix}Generated — {len(errors)} error(s)")
        elif errors:
            console.print(
                f"  {prefix}Correction {iteration}/{max_iterations}"
                f" — {len(errors)} error(s) remaining"
            )
        else:
            console.print(
                f"  {prefix}Correction {iteration}/{max_iterations} — converged"
            )

    console.print("[bold green]Running pipeline...[/bold green]")
    try:
        result = pipeline.run(
            contract_text, config, str(input_file), on_progress=_progress
        )
    except Exception as e:
        _fatal(str(e))

    try:
        run_dir = write_results(result, config, config_file)
    except Exception as e:
        _fatal(f"Could not write results: {e}")

    status = (
        "[green]Success[/green]" if result.success else "[red]Failed to converge[/red]"
    )
    console.print(f"\n[bold]Result:[/bold] {status}")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Candidate")
    table.add_column("Converged")
    table.add_column("Iterations Used")

    for c in result.candidates:
        table.add_row(
            str(c.candidate_id + 1),
            "[green]Yes[/green]" if c.converged else "[red]No[/red]",
            str(c.iterations_used),
        )

    console.print(table)
    console.print(f"\n[dim]Output written to: {run_dir}[/dim]")

    if config.observability.langsmith.enabled:
        try:
            from langsmith import Client
            Client().flush()
        except Exception:
            pass


def main() -> None:
    app()
