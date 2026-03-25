"""
DTGS — Ingestion Graph Nodes.

Implements the 5 ingest-side nodes for Graph 1:
  clone_repo → discover_files → fan_out_analysis → analyze_file → store_registry
"""
from __future__ import annotations

import warnings
from pathlib import Path

from langgraph.types import Send

from toolmaker.graphs.state import FileAnalysisState, IngestionState
from toolmaker.ingestion.github import cleanup_repo
from toolmaker.ingestion.github import clone_repo as _clone_repo
from toolmaker.ingestion.github import find_java_files


# ── Node 1: clone_repo ────────────────────────────────────────────────────

def clone_repo(state: IngestionState) -> dict:
    """
    Clone the GitHub repo given by ``state["github_url"]``.

    Returns:
        ``repo_path`` on success, or ``error`` on failure.
    """
    url: str = state["github_url"]
    try:
        repo_path = _clone_repo(url)
        return {"repo_path": str(repo_path), "error": None}
    except RuntimeError as exc:
        return {"error": str(exc), "repo_path": ""}


# ── Node 2: discover_files ────────────────────────────────────────────────

def discover_files(state: IngestionState) -> dict:
    """
    Walk the cloned repo and collect all .java file paths.
    """
    root = Path(state["repo_path"])
    java_files = [str(p) for p in find_java_files(root)]
    return {"java_files": java_files}


# ── Node 3: fan_out_analysis (conditional edge function) ──────────────────

def fan_out_analysis(state: IngestionState) -> list[Send] | str:
    """
    Fan out one ``Send("analyze_file", ...)`` per discovered Java file.
    LangGraph will execute all analyze_file calls in parallel.

    Returns END if no java_files are present (merges the empty-files guard).
    """
    from langgraph.graph import END

    files = state.get("java_files", [])
    if not files:
        return END

    return [
        Send(
            "analyze_file",
            FileAnalysisState(
                file_path=f,
                registry_path=state.get("registry_path", "dtgs.db"),
                namespace=state.get("namespace", "default"),
                base_url=state.get("base_url", ""),
            ),
        )
        for f in files
    ]


# ── Node 4: analyze_file ─────────────────────────────────────────────────

def analyze_file(state: FileAnalysisState) -> dict:
    """
    Parse a single Java file with tree-sitter and return serialised methods.

    Results are accumulated into ``IngestionState.analyzed_methods`` via the
    ``operator.add`` reducer declared in the state schema.
    """
    from toolmaker.analyzer.java_analyzer import analyze_file as _analyze

    path = Path(state["file_path"])
    try:
        methods = _analyze(path)
        return {"analyzed_methods": [m.model_dump() for m in methods]}
    except Exception as exc:
        warnings.warn(f"[DTGS] Failed to analyze {path}: {exc}", stacklevel=2)
        return {"analyzed_methods": []}


# ── Node 5: store_registry ────────────────────────────────────────────────

def store_registry(state: IngestionState) -> dict:
    """
    Persist all tool schemas (with optional embeddings) into SQLite registry.
    Cleans up the temporary repo clone when done.
    """
    from toolmaker.registry.sqlite_registry import ToolRegistry

    registry = ToolRegistry(state.get("registry_path", "dtgs.db"))

    schemas = state.get("tool_schemas", [])
    embeddings = state.get("embeddings", [])

    # Build method metadata for richer registry records
    methods_raw = state.get("analyzed_methods", [])
    method_meta = [
        {
            "source_file": m.get("source_file", ""),
            "class_name": m.get("class_name", ""),
            "method_name": m.get("method_name", ""),
            "is_rest": bool(m.get("rest_annotations")),
        }
        for m in methods_raw
    ]

    # Align meta list with schemas (schemas may be fewer if filtered)
    aligned_meta = method_meta[: len(schemas)]
    aligned_emb = embeddings if embeddings else None

    ids = registry.upsert_many(
        schemas=schemas,
        namespace=state.get("namespace", "default"),
        base_url=state.get("base_url", ""),
        embeddings=aligned_emb,
        method_meta=aligned_meta,
    )

    # Clean up the temporary git clone
    if state.get("repo_path"):
        cleanup_repo(Path(state["repo_path"]))

    summary = (
        f"Stored {len(ids)} tools from "
        f"{len(set(m.get('source_file','') for m in methods_raw))} Java files "
        f"into registry '{state.get('registry_path', 'dtgs.db')}'."
    )
    return {"registry_ids": ids, "summary": summary}
