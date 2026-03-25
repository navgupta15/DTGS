"""
Tests for the DTGS Ingestion Pipeline (LangGraph Graph 1).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_JAVA = FIXTURE_DIR / "SampleController.java"


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_initial_state(repo_path: str = "", error=None) -> dict:
    return {
        "github_url": "https://github.com/example/repo",
        "registry_path": ":memory:",
        "repo_path": repo_path,
        "error": error,
        "java_files": [],
        "analyzed_methods": [],
        "tool_schemas": [],
        "embeddings": [],
        "registry_ids": [],
        "summary": "",
    }


# ── Node unit tests ────────────────────────────────────────────────────────

class TestCloneRepoNode:
    def test_returns_error_on_git_failure(self):
        from toolmaker.graphs.nodes.ingest_nodes import clone_repo

        with patch(
            "toolmaker.graphs.nodes.ingest_nodes._clone_repo",
            side_effect=RuntimeError("git not found"),
        ):
            state = _make_initial_state()
            result = clone_repo(state)

        assert result["error"] == "git not found"
        assert result["repo_path"] == ""

    def test_returns_repo_path_on_success(self, tmp_path):
        from toolmaker.graphs.nodes.ingest_nodes import clone_repo

        with patch(
            "toolmaker.graphs.nodes.ingest_nodes._clone_repo",
            return_value=tmp_path,
        ):
            state = _make_initial_state()
            result = clone_repo(state)

        assert result["error"] is None
        assert result["repo_path"] == str(tmp_path)


class TestDiscoverFilesNode:
    def test_discovers_java_fixtures(self):
        from toolmaker.graphs.nodes.ingest_nodes import discover_files

        state = _make_initial_state(repo_path=str(FIXTURE_DIR))
        result = discover_files(state)

        assert len(result["java_files"]) >= 1
        assert any("SampleController.java" in f for f in result["java_files"])

    def test_returns_empty_list_for_empty_dir(self, tmp_path):
        from toolmaker.graphs.nodes.ingest_nodes import discover_files

        state = _make_initial_state(repo_path=str(tmp_path))
        result = discover_files(state)

        assert result["java_files"] == []


class TestFanOutAnalysis:
    def test_returns_send_per_file(self):
        from langgraph.types import Send
        from toolmaker.graphs.nodes.ingest_nodes import fan_out_analysis

        state = _make_initial_state()
        state["java_files"] = ["/a/Foo.java", "/b/Bar.java"]
        result = fan_out_analysis(state)

        assert len(result) == 2
        assert all(isinstance(s, Send) for s in result)
        assert all(s.node == "analyze_file" for s in result)

    def test_returns_empty_for_no_files(self):
        from langgraph.graph import END
        from toolmaker.graphs.nodes.ingest_nodes import fan_out_analysis

        state = _make_initial_state()
        state["java_files"] = []
        result = fan_out_analysis(state)

        assert result == END


class TestAnalyzeFileNode:
    def test_analyzes_fixture_file(self):
        from toolmaker.graphs.nodes.ingest_nodes import analyze_file

        result = analyze_file({"file_path": str(FIXTURE_JAVA), "registry_path": ":memory:"})
        methods = result["analyzed_methods"]

        assert len(methods) >= 7
        names = [m["method_name"] for m in methods]
        assert "greet" in names
        assert "factorial" in names

    def test_returns_empty_on_bad_path(self):
        from toolmaker.graphs.nodes.ingest_nodes import analyze_file
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = analyze_file({"file_path": "/nonexistent/Foo.java", "registry_path": ":memory:"})

        assert result["analyzed_methods"] == []


# ── Graph integration tests ────────────────────────────────────────────────

class TestIngestionGraphRouting:
    def test_graph_routes_to_end_on_clone_error(self):
        from toolmaker.graphs.ingestion_graph import build_ingestion_graph

        graph = build_ingestion_graph()

        with patch(
            "toolmaker.graphs.nodes.ingest_nodes._clone_repo",
            side_effect=RuntimeError("network error"),
        ):
            state = _make_initial_state()
            result = graph.invoke(state)

        assert result["error"] is not None
        assert result["registry_ids"] == []

    def test_graph_routes_to_end_with_no_java_files(self, tmp_path):
        from toolmaker.graphs.ingestion_graph import build_ingestion_graph

        graph = build_ingestion_graph()

        with patch(
            "toolmaker.graphs.nodes.ingest_nodes._clone_repo",
            return_value=tmp_path,
        ):
            state = _make_initial_state()
            result = graph.invoke(state)

        # No Java files → registry_ids should be empty
        assert result["registry_ids"] == []

    def test_full_ingestion_with_fixture_dir(self, tmp_path):
        from toolmaker.graphs.ingestion_graph import build_ingestion_graph

        graph = build_ingestion_graph()
        db_path = str(tmp_path / "test.db")

        with patch(
            "toolmaker.graphs.nodes.ingest_nodes._clone_repo",
            return_value=FIXTURE_DIR,
        ), patch(
            "toolmaker.graphs.nodes.ingest_nodes.cleanup_repo",
        ):
            state = _make_initial_state()
            state["registry_path"] = db_path
            result = graph.invoke(state)

        assert len(result["registry_ids"]) >= 7
        assert result["error"] is None
        assert "Stored" in result["summary"]
