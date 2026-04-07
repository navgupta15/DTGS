"""
DTGS — LangGraph State Schemas.

IngestionState: used by the Ingestion Pipeline (Graph 1).
AgentState:     used by the Agent Query Pipeline (Graph 2).
"""
from __future__ import annotations

import operator
from typing import Annotated, Any
from typing_extensions import TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


# ── Ingestion Pipeline State ───────────────────────────────────────────────

class IngestionState(TypedDict):
    """Shared state for the Java repo ingestion pipeline."""

    # ── Input ─────────────────────────────────────────────────────────────
    github_url: str | None           # e.g. "https://github.com/owner/repo"
    local_path: str | None           # local path to directory (for ingest-local)
    registry_path: str               # path to the SQLite DB file
    namespace: str                   # multi-tenant namespace (e.g. "service_a")
    base_url: str                    # target API base URL (e.g. "https://api.myapp.com")
    include_patterns: list[str] | None # list of strings to filter file paths

    # ── After clone_repo ──────────────────────────────────────────────────
    repo_path: str                   # temp directory with cloned repo
    error: str | None                # set on failure; triggers early exit

    # ── After discover_files ──────────────────────────────────────────────
    java_files: list[str]            # absolute paths to .java files

    # ── Fan-out: analyze_file → accumulated by operator.add ───────────────
    # Each parallel analyze_file node appends its results here.
    analyzed_methods: Annotated[list[dict], operator.add]
    analyzed_classes: Annotated[list[dict], operator.add]

    # ── After generate_schemas ────────────────────────────────────────────
    tool_schemas: list[dict]         # serialised ToolSchema dicts

    # ── After embed_tools ─────────────────────────────────────────────────
    embeddings: list[list[float]]    # one per tool schema; empty if no API key

    # ── After store_registry ──────────────────────────────────────────────
    registry_ids: list[str]
    summary: str


# ── Per-file sub-state used by the Send API ────────────────────────────────

class FileAnalysisState(TypedDict):
    """Minimal state dispatched to each analyze_file node via Send."""
    file_path: str
    registry_path: str               # forwarded through so store_registry can use it
    namespace: str                   # forwarded to store_registry
    base_url: str                    # forwarded to store_registry
    include_patterns: list[str] | None


# ── Agent Query Pipeline State ────────────────────────────────────────────

class AgentState(TypedDict):
    """Shared state for the agent tool-discovery and invocation pipeline."""

    # ── Conversation history (auto-merged via add_messages) ───────────────
    messages: Annotated[list[AnyMessage], add_messages]

    # ── Tool discovery ────────────────────────────────────────────────────
    query: str                       # user's natural-language request
    registry_path: str               # path to the SQLite DB
    retrieved_tools: list[dict]      # top-K tool schemas from the registry

    # ── Tool invocation ───────────────────────────────────────────────────
    tool_call: dict | None           # LLM's chosen tool_call dict
    tool_result: Any                 # raw result from execute_tool

    # ── Loop guard ────────────────────────────────────────────────────────
    iterations: int                  # number of llm_select_tool calls so far
    max_iterations: int              # default 5; configurable
