"""
Tests for the DTGS Agent Query Pipeline (LangGraph Graph 2).

These tests mock LLM and registry calls to avoid requiring API keys.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from langchain_core.messages import AIMessage


# ── Helpers ────────────────────────────────────────────────────────────────

SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "SampleController_greet",
            "description": "Returns a greeting message for the given user name.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "String name"}},
                "required": ["name"],
            },
        },
    }
]


def _make_agent_state(**overrides) -> dict:
    base = {
        "messages": [],
        "query": "greet a user named Alice",
        "registry_path": ":memory:",
        "retrieved_tools": [],
        "tool_call": None,
        "tool_result": None,
        "iterations": 0,
        "max_iterations": 5,
    }
    base.update(overrides)
    return base


def _mock_model(side_effect=None, return_value=None):
    """Build a mock chat model that patches _get_chat_model."""
    m = MagicMock()
    m.bind_tools.return_value = m
    if return_value is not None:
        m.invoke.return_value = return_value
    if side_effect is not None:
        m.invoke.side_effect = side_effect
    return m


# ── Node unit tests ────────────────────────────────────────────────────────

class TestReceiveQueryNode:
    def test_sets_messages_and_resets_counters(self):
        from toolmaker.graphs.nodes.agent_nodes import receive_query

        state = _make_agent_state(query="find all pets")
        result = receive_query(state)

        messages = result["messages"]
        assert len(messages) == 2
        assert messages[0].__class__.__name__ == "SystemMessage"
        assert messages[1].__class__.__name__ == "HumanMessage"
        assert "find all pets" in messages[1].content
        assert result["iterations"] == 0
        assert result["tool_call"] is None


class TestSearchToolsNode:
    def test_returns_tools_from_keyword_search(self, tmp_path):
        from toolmaker.registry.sqlite_registry import ToolRegistry
        from toolmaker.graphs.nodes.agent_nodes import search_tools

        # Pre-populate a real SQLite registry
        db_path = str(tmp_path / "test.db")
        registry = ToolRegistry(db_path)
        registry.upsert_many(SAMPLE_TOOLS)

        state = _make_agent_state(query="greet", registry_path=db_path)
        result = search_tools(state)

        assert len(result["retrieved_tools"]) >= 1
        func_name = result["retrieved_tools"][0]["function"]["name"]
        assert "greet" in func_name.lower()

    def test_returns_empty_list_for_empty_registry(self, tmp_path):
        from toolmaker.graphs.nodes.agent_nodes import search_tools

        db_path = str(tmp_path / "empty.db")
        state = _make_agent_state(query="anything", registry_path=db_path)
        result = search_tools(state)

        assert result["retrieved_tools"] == []


class TestLLMSelectToolNode:
    def test_captures_tool_call_when_llm_selects_tool(self):
        from toolmaker.graphs.nodes.agent_nodes import llm_select_tool
        from langchain_core.messages import SystemMessage, HumanMessage

        mock_tool_call = {
            "name": "SampleController_greet",
            "args": {"name": "Alice"},
            "id": "call_abc123",
            "type": "tool_call",
        }
        mock_response = AIMessage(content="", tool_calls=[mock_tool_call])
        mock_model = _mock_model(return_value=mock_response)

        with patch("toolmaker.graphs.nodes.agent_nodes._get_chat_model", return_value=mock_model):
            state = _make_agent_state(
                messages=[SystemMessage(content="sys"), HumanMessage(content="greet Alice")],
                retrieved_tools=SAMPLE_TOOLS,
            )
            result = llm_select_tool(state)

        assert result["tool_call"] is not None
        assert result["tool_call"]["name"] == "SampleController_greet"
        assert result["tool_call"]["args"]["name"] == "Alice"
        assert result["iterations"] == 1

    def test_sets_tool_call_to_none_on_direct_answer(self):
        from toolmaker.graphs.nodes.agent_nodes import llm_select_tool
        from langchain_core.messages import SystemMessage, HumanMessage

        mock_response = AIMessage(content="Hello, Alice!", tool_calls=[])
        mock_model = _mock_model(return_value=mock_response)

        with patch("toolmaker.graphs.nodes.agent_nodes._get_chat_model", return_value=mock_model):
            state = _make_agent_state(
                messages=[SystemMessage(content="sys"), HumanMessage(content="greet Alice")],
                retrieved_tools=SAMPLE_TOOLS,
            )
            result = llm_select_tool(state)

        assert result["tool_call"] is None
        assert result["iterations"] == 1


class TestExecuteToolNode:
    def test_returns_simulated_result_with_tool_info(self):
        from toolmaker.graphs.nodes.agent_nodes import execute_tool
        import json

        state = _make_agent_state(
            tool_call={"name": "SampleController_greet", "args": {"name": "Alice"}, "id": "c1"}
        )
        result = execute_tool(state)

        raw = json.loads(result["tool_result"])
        assert raw["status"] == "simulated"
        assert raw["tool"] == "SampleController_greet"
        assert raw["args"]["name"] == "Alice"

        msgs = result["messages"]
        assert len(msgs) == 1
        assert msgs[0].__class__.__name__ == "ToolMessage"

    def test_returns_safe_message_when_no_tool_call(self):
        from toolmaker.graphs.nodes.agent_nodes import execute_tool

        state = _make_agent_state(tool_call=None)
        result = execute_tool(state)

        assert result["tool_result"] == "No tool was selected."


# ── Graph routing tests ────────────────────────────────────────────────────

class TestAgentGraphRouting:
    def test_graph_ends_immediately_on_direct_answer(self):
        from toolmaker.graphs.agent_graph import build_agent_graph

        mock_response = AIMessage(content="I can help with that directly.", tool_calls=[])
        mock_model = _mock_model(return_value=mock_response)

        with patch("toolmaker.graphs.nodes.agent_nodes._get_chat_model", return_value=mock_model), \
             patch("toolmaker.graphs.nodes.agent_nodes.ToolRegistry") as MockReg:
            MockReg.return_value.search.return_value = SAMPLE_TOOLS
            graph = build_agent_graph()
            result = graph.invoke(_make_agent_state())

        assert result["tool_call"] is None
        assert result["tool_result"] is None

    def test_graph_executes_tool_when_llm_selects_one(self):
        from toolmaker.graphs.agent_graph import build_agent_graph

        mock_tool_call = {
            "name": "SampleController_greet",
            "args": {"name": "Bob"},
            "id": "call_xyz",
            "type": "tool_call",
        }
        first_response = AIMessage(content="", tool_calls=[mock_tool_call])
        second_response = AIMessage(content="Done! Bob was greeted.", tool_calls=[])

        mock_model = _mock_model(side_effect=[first_response, second_response, second_response])

        with patch("toolmaker.graphs.nodes.agent_nodes._get_chat_model", return_value=mock_model), \
             patch("toolmaker.graphs.nodes.agent_nodes.ToolRegistry") as MockReg:
            MockReg.return_value.search.return_value = SAMPLE_TOOLS
            graph = build_agent_graph()
            result = graph.invoke(_make_agent_state(max_iterations=3))

        assert result["tool_result"] is not None
        assert "SampleController_greet" in result["tool_result"]

    def test_graph_respects_max_iterations(self):
        from toolmaker.graphs.agent_graph import build_agent_graph

        mock_tool_call = {
            "name": "SampleController_greet",
            "args": {"name": "Eve"},
            "id": "call_loop",
            "type": "tool_call",
        }
        synthesize_response = AIMessage(content="Synthesized.", tool_calls=[])
        tool_response = AIMessage(content="", tool_calls=[mock_tool_call])

        # Alternating: tool_call then synthesize per iteration
        mock_model = _mock_model(side_effect=[tool_response, synthesize_response] * 10)

        with patch("toolmaker.graphs.nodes.agent_nodes._get_chat_model", return_value=mock_model), \
             patch("toolmaker.graphs.nodes.agent_nodes.ToolRegistry") as MockReg:
            MockReg.return_value.search.return_value = SAMPLE_TOOLS
            graph = build_agent_graph()
            result = graph.invoke(_make_agent_state(max_iterations=2))

        assert result["iterations"] <= 2
