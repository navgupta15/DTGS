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
from toolmaker.logger import logger


# ── Node 1: clone_repo ────────────────────────────────────────────────────

def clone_repo(state: IngestionState) -> dict:
    """
    Clone the GitHub repo given by ``state["github_url"]``.

    Returns:
        ``repo_path`` on success, or ``error`` on failure.
    """
    if state.get("local_path"):
        return {"repo_path": state["local_path"], "error": None}

    url: str | None = state.get("github_url")
    if not url:
        return {"error": "Neither github_url nor local_path was provided", "repo_path": ""}
    
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
    logger.info(f"Discovered {len(java_files)} Java files to analyze.")
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
                include_patterns=state.get("include_patterns"),
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
    logger.debug(f"Parsing AST for Java file: {path.name}")
    try:
        methods, classes = _analyze(path)
        
        # Filter methods (so we only generate endpoints for target packages)
        patterns = state.get("include_patterns")
        if patterns:
            path_str = str(path).replace('\\', '/')
            if not any(pat in path_str or pat.replace('.', '/') in path_str for pat in patterns):
                methods = []

        return {
            "analyzed_methods": [m.model_dump() for m in methods],
            "analyzed_classes": [c.model_dump() for c in classes]
        }
    except Exception as exc:
        warnings.warn(f"[DTGS] Failed to analyze {path}: {exc}", stacklevel=2)
        return {"analyzed_methods": [], "analyzed_classes": []}


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

    # Clean up the temporary git clone if it is not a local ingestion
    if state.get("repo_path") and not state.get("local_path"):
        cleanup_repo(Path(state["repo_path"]))

    summary = (
        f"Stored {len(ids)} tools from "
        f"{len(set(m.get('source_file','') for m in methods_raw))} Java files "
        f"into registry '{state.get('registry_path', 'dtgs.db')}'."
    )
    logger.info(summary)
    return {"registry_ids": ids, "summary": summary}
