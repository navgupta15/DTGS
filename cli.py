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

# Load .env file automatically for LLM configurations
from dotenv import load_dotenv
load_dotenv()

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

def _read_include_file(file_path: Path | None) -> list[str] | None:
    if not file_path:
        return None
    if not file_path.exists():
        console.print(f"[bold yellow]Warning:[/] Include file not found: {file_path}")
        return None
    patterns = [line.strip() for line in file_path.read_text().splitlines() if line.strip()]
    return patterns if patterns else None


def _run_analysis(root: Path, public_only: bool, output: Path | None, include_patterns: list[str] | None = None) -> None:
    from toolmaker.analyzer.java_analyzer import analyze_directory
    from toolmaker.analyzer.schema_generator import methods_to_tool_schemas

    console.print(f"[bold cyan]Scanning Java files in:[/] {root}")
    if include_patterns:
        console.print(f"[dim]Filtering using {len(include_patterns)} patterns.[/]")
        
    methods, classes = analyze_directory(root, include_patterns=include_patterns)

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

    classes_registry = {c.class_name: c for c in classes}
    schemas = methods_to_tool_schemas(methods, classes_registry=classes_registry)
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
    include_file: Path | None = typer.Option(None, "--include-file", help="Text file containing list of package paths/patterns to scan"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose trace logging"),
) -> None:
    """Clone a GitHub repo and print Java tool schemas (no registry)."""
    from toolmaker.logger import setup_logger
    logger = setup_logger(level="DEBUG" if verbose else "INFO")
    
    from toolmaker.ingestion.github import clone_repo, cleanup_repo

    includes = _read_include_file(include_file)
    console.print(f"[bold]Cloning[/] {github_url} ...")
    try:
        repo_path = clone_repo(github_url)
    except RuntimeError as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

    console.print(f"[green]OK[/] Cloned to {repo_path}")
    try:
        _run_analysis(repo_path, public_only=public_only, output=output, include_patterns=includes)
    finally:
        if not keep:
            cleanup_repo(repo_path)
            console.print("[dim]Cleaned up temporary clone.[/]")


@app.command()
def delete(
    namespace: str = typer.Argument(..., help="Namespace to delete from the registry"),
    registry: Path = typer.Option(Path("dtgs.db"), "--registry", "-r", help="SQLite registry path"),
) -> None:
    """Delete all tools for a given namespace from the registry."""
    from toolmaker.registry.sqlite_registry import ToolRegistry

    if not registry.exists():
        console.print(f"[bold red]Error:[/] Registry {registry} not found.")
        raise typer.Exit(code=1)

    db = ToolRegistry(str(registry))
    count_before = db.count(namespace=namespace)
    
    if count_before == 0:
        console.print(f"[yellow]No tools found for namespace '{namespace}'.[/]")
        return
        
    db.delete_namespace(namespace)
    console.print(f"[bold green]Deleted {count_before} tools from namespace '{namespace}'.[/]")


@app.command(name="analyze-local")
def analyze_local(
    path: Path = typer.Argument(..., help="Local Java project path"),
    output: Path | None = typer.Option(None, "--output", "-o"),
    public_only: bool = typer.Option(False, "--public-only"),
    include_file: Path | None = typer.Option(None, "--include-file", help="Text file containing list of package paths/patterns to scan"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose trace logging"),
) -> None:
    """Analyze a local Java codebase and print tool schemas (no registry)."""
    from toolmaker.logger import setup_logger
    logger = setup_logger(level="DEBUG" if verbose else "INFO")
    if not path.exists():
        console.print(f"[bold red]Error:[/] Path does not exist: {path}")
        raise typer.Exit(code=1)
        
    includes = _read_include_file(include_file)
    _run_analysis(path, public_only=public_only, output=output, include_patterns=includes)


@app.command()
def ingest(
    github_url: str = typer.Argument(..., help="Public GitHub repo URL to ingest"),
    registry: Path = typer.Option(Path("dtgs.db"), "--registry", "-r", help="SQLite registry path"),
    namespace: str = typer.Option("default", "--namespace", help="Multi-tenant namespace for these tools"),
    base_url: str = typer.Option("", "--base-url", help="Base URL where this API runs (e.g. https://api.myapp.com)"),
    enhance: bool = typer.Option(True, "--enhance/--no-enhance", help="Use LLM to rewrite and enhance tool descriptions"),
    include_file: Path | None = typer.Option(None, "--include-file", help="Text file containing list of package paths/patterns to scan"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose trace logging"),
) -> None:
    """
    Clone, analyze, and store tools into the SQLite registry (Graph 1).

    This runs the full LangGraph Ingestion Pipeline.
    """
    from toolmaker.logger import setup_logger
    logger = setup_logger(level="DEBUG" if verbose else "INFO")
    
    from toolmaker.graphs.ingestion_graph import run_ingestion

    includes = _read_include_file(include_file)

    console.print(f"[bold]Running DTGS Ingestion Graph[/] for {github_url}")
    console.print(f"[dim]Namespace:[/] {namespace}")
    console.print(f"[dim]Base URL:[/]  {base_url or '(none)'}")
    console.print(f"[dim]Enhance:[/]   {'Yes (LLM)' if enhance else 'No'}")
    console.print(f"[dim]Registry:[/]  {registry}")
    if includes:
        console.print(f"[dim]Includes:[/]  Loaded {len(includes)} patterns")

    result = run_ingestion(
        github_url=github_url,
        registry_path=str(registry),
        namespace=namespace,
        base_url=base_url,
        enhance_descriptions=enhance,
        include_patterns=includes,
    )

    if result.get("error"):
        console.print(f"[bold red]Ingestion failed:[/] {result['error']}")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Done![/] {result.get('summary', '')}")
    console.print(f"[dim]Stored {len(result.get('registry_ids', []))} tool schemas.[/]")


@app.command(name="ingest-local")
def ingest_local(
    path: Path = typer.Argument(..., help="Local Java project path to ingest"),
    registry: Path = typer.Option(Path("dtgs.db"), "--registry", "-r", help="SQLite registry path"),
    namespace: str = typer.Option("default", "--namespace", help="Multi-tenant namespace for these tools"),
    base_url: str = typer.Option("", "--base-url", help="Base URL where this API runs (e.g. https://api.myapp.com)"),
    enhance: bool = typer.Option(True, "--enhance/--no-enhance", help="Use LLM to rewrite and enhance tool descriptions"),
    include_file: Path | None = typer.Option(None, "--include-file", help="Text file containing list of package paths/patterns to scan"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose trace logging"),
) -> None:
    """
    Analyze and store tools from a local folder into the SQLite registry (Graph 1).
    """
    from toolmaker.logger import setup_logger
    logger = setup_logger(level="DEBUG" if verbose else "INFO")
    
    if not path.exists():
        console.print(f"[bold red]Error:[/] Path does not exist: {path}")
        raise typer.Exit(code=1)

    from toolmaker.graphs.ingestion_graph import run_ingestion

    includes = _read_include_file(include_file)

    console.print(f"[bold]Running DTGS Local Ingestion Graph[/] for {path}")
    console.print(f"[dim]Namespace:[/] {namespace}")
    console.print(f"[dim]Base URL:[/]  {base_url or '(none)'}")
    console.print(f"[dim]Enhance:[/]   {'Yes (LLM)' if enhance else 'No'}")
    console.print(f"[dim]Registry:[/]  {registry}")
    if includes:
        console.print(f"[dim]Includes:[/]  Loaded {len(includes)} patterns")

    result = run_ingestion(
        local_path=str(path),
        registry_path=str(registry),
        namespace=namespace,
        base_url=base_url,
        enhance_descriptions=enhance,
        include_patterns=includes,
    )

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


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Host IP to bind to"),
    port: int = typer.Option(8000, "--port", help="Port to bind to"),
    registry: Path = typer.Option(Path("dtgs.db"), "--registry", "-r", help="SQLite registry path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose trace logging"),
) -> None:
    """
    Start the DTGS FastAPI Catalog Server.
    
    Exposes extracted tools as OpenAPI schemas at: 
    GET /api/v1/{namespace}/openapi.json
    """
    from toolmaker.logger import setup_logger
    logger = setup_logger(level="DEBUG" if verbose else "INFO")
    
    import uvicorn
    from toolmaker.server.catalog import app as catalog_app

    # Inject the registry path into FastAPI state so it knows which db to read
    catalog_app.state.registry_path = str(registry)
    
    console.print(f"[bold green]Starting DTGS Catalog Server[/] on {host}:{port}")
    console.print(f"[dim]Registry:[/] {registry}")
    console.print(f"[dim]Endpoints:[/] GET /api/v1/{{namespace}}/openapi.json")
    
    uvicorn.run(catalog_app, host=host, port=port)


@app.command()
def export(
    namespace: str = typer.Option("default", "--namespace", help="Namespace to export"),
    output: Path = typer.Option(Path("openapi.json"), "--output", "-o", help="Output JSON file path"),
    registry: Path = typer.Option(Path("dtgs.db"), "--registry", "-r", help="SQLite registry path"),
) -> None:
    """
    Offline Generator: Extracts OpenAPI JSON specifications from the SQLite DB.
    
    Creates a strict openapi.json file for the given namespace. Helpful to bypass
    FastAPI browser truncations or statically host the Swagger payload.
    """
    from toolmaker.registry.sqlite_registry import ToolRegistry
    from toolmaker.registry.openapi_generator import generate_openapi_spec
    
    if not registry.exists():
        console.print(f"[bold red]Error:[/] Registry {registry} not found.")
        raise typer.Exit(code=1)
        
    db = ToolRegistry(str(registry))
    schemas = db.get_all(namespace=namespace, limit=10000)
    
    if not schemas:
        console.print(f"[bold yellow]Warning:[/] No tools found for '{namespace}' in {registry}")
        raise typer.Exit(code=1)
        
    # Get base_url from first matching record
    base_url = ""
    with db._connect() as conn:
        row = conn.execute("SELECT base_url FROM tools WHERE namespace = ? LIMIT 1", (namespace,)).fetchone()
        if row and row["base_url"]:
            base_url = row["base_url"]
            
    spec = generate_openapi_spec(namespace, schemas, base_url)
    
    output.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    
    console.print(f"[bold green]Success![/] Extracted [cyan]{len(spec['paths'])}[/] REST endpoints.")
    console.print(f"[dim]Saved OpenAPI 3.1.0 spec to:[/] {output.absolute()}")


@app.command()
def chat(
    namespace: str = typer.Option("default", "--namespace", "-n", help="Namespace to load tools from"),
    dtgs_url: str = typer.Option("http://127.0.0.1:8000", "--dtgs-url", help="DTGS catalog server URL"),
    dry_run: bool = typer.Option(True, "--dry-run/--live", help="Dry-run mode (no real HTTP calls) or live mode"),
    provider: str = typer.Option("", "--provider", help="LLM provider: openai, ollama, gemini (overrides DTGS_PROVIDER env)"),
    model: str = typer.Option("", "--model", help="LLM model name (overrides DTGS_MODEL env)"),
) -> None:
    """
    Interactive chat agent that uses DTGS-discovered APIs as LLM tools.

    Fetches the OpenAPI spec from the running DTGS server, converts operations
    to LLM tools, and lets you chat naturally. The LLM will call the target
    backend APIs on your behalf.

    Start the DTGS server first: dtgs serve
    """
    import httpx
    from toolmaker.agent.openapi_to_tools import openapi_to_tools
    from toolmaker.agent.http_executor import execute_api_call

    # Override env vars if provided
    if provider:
        os.environ["DTGS_PROVIDER"] = provider
    if model:
        os.environ["DTGS_MODEL"] = model

    # 1. Fetch the OpenAPI spec from the DTGS server
    spec_url = f"{dtgs_url.rstrip('/')}/api/v1/{namespace}/openapi.json"
    console.print(f"[bold cyan]Fetching API spec from:[/] {spec_url}")

    try:
        resp = httpx.get(spec_url, timeout=10)
        resp.raise_for_status()
        spec = resp.json()
    except httpx.ConnectError:
        console.print(f"[bold red]Error:[/] Could not connect to DTGS server at {dtgs_url}")
        console.print("[dim]Start the server first with:[/] uv run python cli.py serve")
        raise typer.Exit(code=1)
    except httpx.HTTPStatusError as e:
        console.print(f"[bold red]Error:[/] {e.response.status_code} — {e.response.text}")
        raise typer.Exit(code=1)

    # 2. Convert OpenAPI spec to LLM tools
    tools = openapi_to_tools(spec)
    if not tools:
        console.print("[yellow]No API operations found in the spec.[/]")
        raise typer.Exit(code=1)

    console.print(f"[green]Loaded {len(tools)} API tools[/] from namespace [cyan]{namespace}[/]")
    for t in tools:
        fn = t["function"]
        console.print(f"  [dim]•[/] [bold]{fn['name']}[/] — {fn['description'].split(chr(10))[0][:80]}")

    mode_label = "[yellow]DRY-RUN[/]" if dry_run else "[green]LIVE[/]"
    console.print(f"\n[bold]Mode:[/] {mode_label}")
    if dry_run:
        console.print("[dim]Using --dry-run: API calls will be simulated. Use --live to make real HTTP requests.[/]")
    console.print("[dim]Type 'quit' or 'exit' to end the session.[/]\n")

    # 3. Set up the LLM with tools
    from toolmaker.graphs.nodes.agent_nodes import _get_chat_model
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    try:
        llm = _get_chat_model()
    except Exception as e:
        console.print(f"[bold red]Error loading LLM:[/] {e}")
        console.print("[dim]Set DTGS_PROVIDER and required API keys (OPENAI_API_KEY, GOOGLE_API_KEY, etc.)[/]")
        raise typer.Exit(code=1)

    base_url = spec.get("servers", [{}])[0].get("url", "")
    system_prompt = f"""You are DTGS Agent, an AI assistant that discovers and calls REST APIs.

You currently have access to {len(tools)} API tools that represent real API endpoints for the service '{namespace}'.
The target backend is at: {base_url}

When the user asks you to do something:
1. Identify which API tool to call.
2. Call it with the correct arguments based on the OpenAPI schema.
3. Interpret the result and give a clear answer.

If no tool matches, say so clearly. Do not make up tool names or arguments."""

    llm_with_tools = llm.bind_tools(tools)
    messages = [SystemMessage(content=system_prompt)]

    # 4. Interactive chat loop
    while True:
        try:
            user_input = console.input("[bold cyan]You:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye![/]")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            console.print("[dim]Bye![/]")
            break

        if not user_input:
            continue

        messages.append(HumanMessage(content=user_input))

        # LLM response (may include tool calls)
        try:
            response: AIMessage = llm_with_tools.invoke(messages)
        except Exception as e:
            console.print(f"[bold red]LLM Error:[/] {e}")
            messages.pop()  # Remove failed user message
            continue

        messages.append(response)

        # Process tool calls if any
        if response.tool_calls:
            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                tool_id = tc["id"]

                console.print(f"\n[bold magenta]🔧 Calling:[/] {tool_name}")
                console.print(f"[dim]   Args: {json.dumps(tool_args, indent=2)}[/]")

                # Execute the API call
                result = execute_api_call(
                    spec=spec,
                    operation_id=tool_name,
                    arguments=tool_args,
                    dry_run=dry_run,
                )

                console.print(f"[dim]   {result['method']} {result['url']}[/]")

                if dry_run:
                    console.print(f"[yellow]   ↳ DRY RUN result:[/]")
                else:
                    status = result.get("status_code", -1)
                    status_color = "green" if 200 <= status < 300 else "red"
                    console.print(f"[{status_color}]   ↳ HTTP {status}[/{status_color}]")

                result_str = json.dumps(result.get("body", ""), indent=2) if isinstance(result.get("body"), (dict, list)) else str(result.get("body", ""))
                console.print(f"[dim]   {result_str[:500]}[/]")

                # Feed the result back to the LLM
                tool_msg = ToolMessage(content=result_str, tool_call_id=tool_id)
                messages.append(tool_msg)

            # Get the LLM's final synthesis after tool results
            try:
                synthesis: AIMessage = llm_with_tools.invoke(messages)
                messages.append(synthesis)
                console.print(f"\n[bold green]Agent:[/] {synthesis.content}")
            except Exception as e:
                console.print(f"[bold red]LLM Error during synthesis:[/] {e}")
        else:
            # Direct response (no tool call)
            console.print(f"\n[bold green]Agent:[/] {response.content}")

        console.print()  # Blank line between turns


if __name__ == "__main__":
    app()


