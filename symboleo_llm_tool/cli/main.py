from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from symboleo_llm_tool.config.loader import load_config
from symboleo_llm_tool.output.writer import write_results
from symboleo_llm_tool.pipeline import pipeline

load_dotenv()

app = typer.Typer(help="LLM-assisted SymboleoAC contract generation and correction.")
console = Console()


@app.command()
def run(
    input_file: Path = typer.Argument(..., help="Path to the .txt legal contract"),
    config_file: Path = typer.Option(..., "--config", "-c", help="Path to YAML config file"),
) -> None:
    if not input_file.exists():
        console.print(f"[red]Error:[/red] Input file not found: {input_file}")
        raise typer.Exit(1)
    if not config_file.exists():
        console.print(f"[red]Error:[/red] Config file not found: {config_file}")
        raise typer.Exit(1)

    config = load_config(config_file)
    contract_text = input_file.read_text(encoding="utf-8")

    with console.status("[bold green]Running pipeline...[/bold green]"):
        result = pipeline.run(contract_text, config, str(input_file))

    run_dir = write_results(result, config, config_file)

    status = "[green]Success[/green]" if result.success else "[red]Failed to converge[/red]"
    console.print(f"\n[bold]Result:[/bold] {status}")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Candidate")
    table.add_column("Converged")
    table.add_column("Iterations Used")

    for c in result.candidates:
        table.add_row(
            str(c.candidate_id),
            "[green]Yes[/green]" if c.converged else "[red]No[/red]",
            str(c.iterations_used),
        )

    console.print(table)
    console.print(f"\n[dim]Output written to: {run_dir}[/dim]")


def main() -> None:
    app()
