"""
gt-finops CLI.

Three commands:
  gt-finops ingest   — read client data folder into DuckDB
  gt-finops analyze  — run one or all recipes, write findings
  gt-finops report   — produce HTML, Excel, and PowerPoint outputs
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

import click
import duckdb
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from gt_finops import __version__, initialize_schema, table_counts
from gt_finops.ingest import ingest_folder
from gt_finops.recipes import ALL_RECIPES, RECIPE_BY_ID, get_recipe
from gt_finops.recipes.base import save_findings, clear_findings
from gt_finops.aggregate import summarize
from gt_finops.report import (
    write_html_report, write_excel_workbook, write_findings_deck,
)


console = Console()


@click.group()
@click.version_option(__version__, prog_name="gt-finops")
def main():
    """Grant Thornton FinOps Quick-Wins Analyzer."""


@main.command()
@click.option("--source-dir", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Folder containing client data in the expected layout.")
@click.option("--output", "-o", "db_path", required=True,
              type=click.Path(path_type=Path),
              help="DuckDB file to write to.")
@click.option("--preserve/--no-preserve", default=False,
              help="Don't truncate before ingest (append mode).")
def ingest(source_dir: Path, db_path: Path, preserve: bool):
    """Ingest a client data folder into a DuckDB database."""
    console.print("[bold magenta]GT FinOps · ingest[/bold magenta]")
    console.print(f"source:  {source_dir}")
    console.print(f"output:  {db_path}\n")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists() and not preserve:
        db_path.unlink()

    conn = duckdb.connect(str(db_path))
    try:
        initialize_schema(conn)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console, transient=True,
        ) as progress:
            progress.add_task("Walking folder and ingesting…", total=None)
            report_obj = ingest_folder(conn, source_dir)

        console.print("[bold]Tables populated[/bold]")
        t = Table(show_header=True, header_style="bold magenta")
        t.add_column("Table"); t.add_column("Rows", justify="right")
        counts = table_counts(conn)
        for name in sorted(counts):
            if name in ("engagement_metadata", "findings"):
                continue
            if counts[name] > 0:
                t.add_row(name, f"{counts[name]:,}")
        console.print(t)

        if report_obj.files_missing:
            console.print("\n[yellow]Missing files (dependent recipes skipped):[/yellow]")
            for m in report_obj.files_missing:
                console.print(f"  • {m}")
        if report_obj.errors:
            console.print("\n[red]Errors:[/red]")
            for e in report_obj.errors:
                console.print(f"  • {e}")

        console.print(f"\n[green]✓[/green] Ingest complete — {report_obj.total_rows:,} rows.")
    finally:
        conn.close()


@main.command()
@click.option("--db", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--recipes", default="all",
              help="Comma-separated recipe IDs or 'all'.")
@click.option("--clear-first/--keep-findings", default=True)
def analyze(db: Path, recipes: str, clear_first: bool):
    """Run one or all recipes against a populated DuckDB."""
    console.print("[bold magenta]GT FinOps · analyze[/bold magenta]")
    console.print(f"db: {db}\n")

    conn = duckdb.connect(str(db))
    try:
        initialize_schema(conn)
        if clear_first:
            clear_findings(conn)

        if recipes == "all":
            recipe_ids = [r.id for r in ALL_RECIPES]
        else:
            recipe_ids = [r.strip() for r in recipes.split(",") if r.strip()]

        unknown = [r for r in recipe_ids if r not in RECIPE_BY_ID]
        if unknown:
            console.print(f"[red]Unknown recipes:[/red] {unknown}")
            raise click.Abort()

        results_table = Table(show_header=True, header_style="bold magenta")
        results_table.add_column("Recipe")
        results_table.add_column("Name")
        results_table.add_column("Status")
        results_table.add_column("Findings", justify="right")
        results_table.add_column("Capturable", justify="right")

        for rid in recipe_ids:
            recipe_cls = get_recipe(rid)
            recipe = recipe_cls()

            issues = recipe.preflight(conn)
            if issues:
                results_table.add_row(rid, recipe.name,
                                      "[yellow]SKIPPED[/yellow]", "-", "-")
                continue

            try:
                findings = recipe.run(conn)
                save_findings(conn, findings)
                total_cap = sum(f.capturable_annual_savings_usd for f in findings)
                status = "[green]OK[/green]" if findings else "[dim]none[/dim]"
                results_table.add_row(rid, recipe.name, status,
                                      str(len(findings)),
                                      f"${total_cap:,.0f}" if findings else "-")
            except Exception as e:
                results_table.add_row(rid, recipe.name,
                                      "[red]ERROR[/red]", "-", "-")
                console.print(f"[red]{rid} error:[/red] {e}")

        console.print(results_table)

        summary = summarize(conn)
        console.print(f"\n[bold]Total findings:[/bold] {summary.total_findings}")
        console.print(f"[bold]Gross:[/bold] ${summary.total_gross_usd:,.0f}")
        console.print(f"[bold]Capturable:[/bold] [green]${summary.total_capturable_usd:,.0f}[/green]")
    finally:
        conn.close()


@main.command()
@click.option("--db", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--client-name", required=True, type=str)
@click.option("--output", "-o", "output_dir", required=True,
              type=click.Path(path_type=Path))
@click.option("--formats", default="html,xlsx,pptx",
              help="Comma-separated: html, xlsx, pptx.")
@click.option("--engagement-end", default=None)
def report(db: Path, client_name: str, output_dir: Path,
           formats: str, engagement_end: str | None):
    """Produce findings artifacts."""
    console.print("[bold magenta]GT FinOps · report[/bold magenta]")
    console.print(f"client:  {client_name}")
    console.print(f"output:  {output_dir}\n")

    output_dir.mkdir(parents=True, exist_ok=True)
    requested = {f.strip() for f in formats.split(",")}

    conn = duckdb.connect(str(db))
    try:
        slug = client_name.replace(" ", "-").replace("/", "-")

        if "html" in requested:
            path = output_dir / f"{slug}-findings.html"
            with console.status("Writing HTML report…"):
                write_html_report(conn, path, client_name)
            console.print(f"[green]✓[/green] HTML: {path}")

        if "xlsx" in requested:
            path = output_dir / f"{slug}-findings-evidence.xlsx"
            with console.status("Writing Excel workbook…"):
                write_excel_workbook(conn, path, client_name)
            console.print(f"[green]✓[/green] Excel: {path}")

        if "pptx" in requested:
            path = output_dir / f"{slug}-findings-deck.pptx"
            with console.status("Writing PowerPoint deck…"):
                end = engagement_end or datetime.utcnow().strftime("%Y-%m-%d")
                write_findings_deck(conn, path, client_name,
                                    engagement_end=end)
            console.print(f"[green]✓[/green] PowerPoint: {path}")
    finally:
        conn.close()


@main.command("list-recipes")
def list_recipes():
    """List all registered recipes."""
    t = Table(show_header=True, header_style="bold magenta")
    t.add_column("ID"); t.add_column("Category"); t.add_column("Name")
    t.add_column("Sources")
    for r in ALL_RECIPES:
        t.add_row(r.id, r.category, r.name, ", ".join(r.sources))
    console.print(t)


if __name__ == "__main__":
    main()
