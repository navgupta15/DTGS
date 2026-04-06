"""
DTGS — Ingestion Pipeline (Graph 1).

Flow:
  clone_repo → discover_files → fan_out_analysis (Send)
              ↓ [parallel]
            analyze_file × N
              ↓ [fan-in, operator.add]
            generate_schemas → embed_tools → store_registry

Conditional edges:
  - clone_repo  → END   if error is set
  - discover_files → END if java_files is empty
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from toolmaker.graphs.state import IngestionState
from toolmaker.graphs.nodes.ingest_nodes import (
    analyze_file,
    clone_repo,
    discover_files,
    fan_out_analysis,
    store_registry,
)
from toolmaker.graphs.nodes.schema_nodes import embed_tools, enhance_descriptions, generate_schemas


# ── Routing helpers ────────────────────────────────────────────────────────

def _route_after_clone(state: IngestionState) -> str:
    """Route to END if cloning failed, else continue to discover_files."""
    if state.get("error"):
        return END
    return "discover_files"


# ── Graph builder ──────────────────────────────────────────────────────────

def build_ingestion_graph() -> StateGraph:
    """
    Build and compile the DTGS Ingestion Pipeline StateGraph.

    Returns a compiled graph ready to be invoked with an IngestionState dict.
    """
    builder = StateGraph(IngestionState)

    # Register nodes
    builder.add_node("clone_repo", clone_repo)
    builder.add_node("discover_files", discover_files)
    builder.add_node("analyze_file", analyze_file)
    builder.add_node("generate_schemas", generate_schemas)
    builder.add_node("enhance_descriptions", enhance_descriptions)
    builder.add_node("embed_tools", embed_tools)
    builder.add_node("store_registry", store_registry)

    # Entry point
    builder.add_edge(START, "clone_repo")

    # Conditional: abort on clone failure
    builder.add_conditional_edges(
        "clone_repo",
        _route_after_clone,
        {"discover_files": "discover_files", END: END},
    )

    # Conditional: abort if no .java files found; otherwise fan-out via Send
    # fan_out_analysis returns END when java_files is empty, else list[Send]
    builder.add_conditional_edges("discover_files", fan_out_analysis)

    # Fan-in: all analyze_file results accumulate, then flow to generate_schemas
    builder.add_edge("analyze_file", "generate_schemas")
    builder.add_edge("generate_schemas", "enhance_descriptions")
    builder.add_edge("enhance_descriptions", "embed_tools")
    builder.add_edge("embed_tools", "store_registry")
    builder.add_edge("store_registry", END)

    return builder.compile()


# ── Convenience runner ─────────────────────────────────────────────────────

def run_ingestion(
    github_url: str | None = None,
    local_path: str | None = None,
    registry_path: str = "dtgs.db",
    namespace: str = "default",
    base_url: str = "",
    enhance_descriptions: bool = True,
    include_patterns: list[str] | None = None,
) -> dict:
    """
    Convenience wrapper: clone, analyze, and store tools from a GitHub repo or local path.

    Args:
        github_url:    Public GitHub repo URL (if remote).
        local_path:    Path to local Java project (if local).
        registry_path: Path to the SQLite DB file (created if not exists).
        namespace:     Multi-tenant namespace (e.g. "service_a")
        base_url:      Target API base URL.
        include_patterns: Optional list of substrings to filter packages.

    Returns:
        Final IngestionState dict.
    """
    graph = build_ingestion_graph()
    initial: IngestionState = {
        "github_url": github_url,
        "local_path": local_path,
        "registry_path": registry_path,
        "namespace": namespace,
        "base_url": base_url,
        "enhance_descriptions": enhance_descriptions,
        "include_patterns": include_patterns,
        "repo_path": "",

        "error": None,
        "java_files": [],
        "analyzed_methods": [],
        "tool_schemas": [],
        "embeddings": [],
        "registry_ids": [],
        "summary": "",
    }
    return graph.invoke(initial)
