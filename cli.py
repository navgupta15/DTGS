"""
DTGS CLI — Dynamic Tool Generation System.

Commands:
  analyze       Analyze a GitHub Java repo (raw JSON, no registry)
  analyze-local Analyze a local Java project (raw JSON, no registry)
  ingest        Clone + analyze + store into SQLite registry (Graph 1)
  run-agent     Query the registry with an LLM agent (Graph 2)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Force UTF-8 on Windows consoles before importing Rich
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="dtgs",
    help="Dynamic Tool Generation System (DTGS) — auto-discover LLM tools from Java codebases.",
    no_args_is_help=True,
)

console = Console()


# ── Shared helpers ─────────────────────────────────────────────────────────

def _run_analysis(root: Path, public_only: bool, output: Path | None) -> None:
    from toolmaker.analyzer.java_analyzer import analyze_directory
    from toolmaker.analyzer.schema_generator import methods_to_tool_schemas

    console.print(f"[bold cyan]Scanning Java files in:[/] {root}")
    methods = analyze_directory(root)

    if not methods:
        console.print("[yellow]No Java methods found.[/]")
        raise typer.Exit(code=1)

    if public_only:
        methods = [m for m in methods if m.is_public]
        console.print("[dim]Filtered to public methods only.[/]")

    file_count = len({m.source_file for m in methods})
    console.print(f"[green]OK[/] Found [bold]{len(methods)}[/] methods across [bold]{file_count}[/] files.")

    table = Table(title="Discovered Methods", show_lines=True)
    table.add_column("Class", style="cyan")
    table.add_column("Method", style="green")
    table.add_column("Params", justify="right")
    table.add_column("REST", style="magenta")
    table.add_column("Javadoc", style="dim")

    for m in methods[:50]:
        javadoc_preview = (
            (m.javadoc[:60] + "...") if m.javadoc and len(m.javadoc) > 60 else (m.javadoc or "-")
        )
        table.add_row(
            m.class_name,
            m.method_name,
            str(len(m.parameters)),
            ", ".join(m.rest_annotations) or "-",
            javadoc_preview,
        )
    if len(methods) > 50:
        table.caption = f"...and {len(methods) - 50} more"
    console.print(table)

    schemas = methods_to_tool_schemas(methods)
    schemas_json = [s.model_dump() for s in schemas]

    if output:
        output.write_text(json.dumps(schemas_json, indent=2), encoding="utf-8")
        console.print(f"\n[bold green]Saved {len(schemas)} tool schemas ->[/] {output}")
    else:
        console.print("\n[bold]Tool Schemas (JSON):[/]")
        console.print_json(json.dumps(schemas_json))


# ── Commands ───────────────────────────────────────────────────────────────

@app.command()
def analyze(
    github_url: str = typer.Argument(..., help="Public GitHub repo URL"),
    output: Path | None = typer.Option(None, "--output", "-o"),
    public_only: bool = typer.Option(False, "--public-only"),
    keep: bool = typer.Option(False, "--keep", help="Keep cloned repo"),
) -> None:
    """Clone a GitHub repo and print Java tool schemas (no registry)."""
    from toolmaker.ingestion.github import clone_repo, cleanup_repo

    console.print(f"[bold]Cloning[/] {github_url} ...")
    try:
        repo_path = clone_repo(github_url)
    except RuntimeError as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

    console.print(f"[green]OK[/] Cloned to {repo_path}")
    try:
        _run_analysis(repo_path, public_only=public_only, output=output)
    finally:
        if not keep:
            cleanup_repo(repo_path)
            console.print("[dim]Cleaned up temporary clone.[/]")


@app.command(name="analyze-local")
def analyze_local(
    path: Path = typer.Argument(..., help="Local Java project path"),
    output: Path | None = typer.Option(None, "--output", "-o"),
    public_only: bool = typer.Option(False, "--public-only"),
) -> None:
    """Analyze a local Java codebase and print tool schemas (no registry)."""
    if not path.exists():
        console.print(f"[bold red]Error:[/] Path does not exist: {path}")
        raise typer.Exit(code=1)
    _run_analysis(path, public_only=public_only, output=output)


@app.command()
def ingest(
    github_url: str = typer.Argument(..., help="Public GitHub repo URL to ingest"),
    registry: Path = typer.Option(Path("dtgs.db"), "--registry", "-r", help="SQLite registry path"),
) -> None:
    """
    Clone, analyze, and store tools into the SQLite registry (Graph 1).

    This runs the full LangGraph Ingestion Pipeline.
    """
    from toolmaker.graphs.ingestion_graph import run_ingestion

    console.print(f"[bold]Running DTGS Ingestion Graph[/] for {github_url}")
    console.print(f"[dim]Registry:[/] {registry}")

    result = run_ingestion(github_url=github_url, registry_path=str(registry))

    if result.get("error"):
        console.print(f"[bold red]Ingestion failed:[/] {result['error']}")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Done![/] {result.get('summary', '')}")
    console.print(f"[dim]Stored {len(result.get('registry_ids', []))} tool schemas.[/]")


@app.command(name="run-agent")
def run_agent_cmd(
    query: str = typer.Argument(..., help="Natural language query for the agent"),
    registry: Path = typer.Option(Path("dtgs.db"), "--registry", "-r", help="SQLite registry path"),
    max_iter: int = typer.Option(5, "--max-iter", help="Maximum tool-call iterations"),
) -> None:
    """
    Query the tool registry with an LLM agent (Graph 2).

    Requires OPENAI_API_KEY to be set in the environment.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        console.print("[bold red]Error:[/] OPENAI_API_KEY environment variable is not set.")
        raise typer.Exit(code=1)

    if not registry.exists():
        console.print(f"[bold red]Error:[/] Registry not found: {registry}. Run 'dtgs ingest' first.")
        raise typer.Exit(code=1)

    from toolmaker.graphs.agent_graph import run_agent

    console.print(f"[bold]Running DTGS Agent Graph[/]")
    console.print(f"[dim]Query:[/] {query}")
    console.print(f"[dim]Registry:[/] {registry}\n")

    result = run_agent(query=query, registry_path=str(registry), max_iterations=max_iter)

    # Print the final assistant message
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.__class__.__name__ == "AIMessage":
            console.print("\n[bold cyan]Agent Response:[/]")
            console.print(msg.content)
            break


if __name__ == "__main__":
    app()
