"""
DTGS — Agent Query Pipeline (Graph 2).

Flow:
  receive_query → search_tools → llm_select_tool
                                      ↓
                              tool_call?  ──no──→ END
                                      ↓ yes
                              execute_tool → synthesize_result
                                      ↓
                              more steps? / limit? → llm_select_tool or END
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from toolmaker.graphs.state import AgentState
from toolmaker.graphs.nodes.agent_nodes import (
    execute_tool,
    llm_select_tool,
    receive_query,
    search_tools,
    synthesize_result,
)


# ── Routing helpers ────────────────────────────────────────────────────────

def _route_after_llm(state: AgentState) -> str:
    """
    If the LLM issued a tool_call → execute_tool.
    Otherwise (direct answer) → END.
    """
    if state.get("tool_call"):
        return "execute_tool"
    return END


def _route_after_synthesis(state: AgentState) -> str:
    """
    After synthesising a result, allow the LLM to continue (multi-step)
    up to max_iterations. Then stop.
    """
    max_iter = state.get("max_iterations", 5)
    if state.get("iterations", 0) < max_iter:
        return "llm_select_tool"
    return END


# ── Graph builder ──────────────────────────────────────────────────────────

def build_agent_graph() -> StateGraph:
    """
    Build and compile the DTGS Agent Query Pipeline StateGraph.

    Returns a compiled graph ready to be invoked with an AgentState dict.
    """
    builder = StateGraph(AgentState)

    # Register nodes
    builder.add_node("receive_query", receive_query)
    builder.add_node("search_tools", search_tools)
    builder.add_node("llm_select_tool", llm_select_tool)
    builder.add_node("execute_tool", execute_tool)
    builder.add_node("synthesize_result", synthesize_result)

    # Linear path up to LLM selection
    builder.add_edge(START, "receive_query")
    builder.add_edge("receive_query", "search_tools")
    builder.add_edge("search_tools", "llm_select_tool")

    # Conditional: does the LLM want to call a tool?
    builder.add_conditional_edges(
        "llm_select_tool",
        _route_after_llm,
        {"execute_tool": "execute_tool", END: END},
    )

    # After executing, synthesize
    builder.add_edge("execute_tool", "synthesize_result")

    # Conditional loop: continue or stop
    builder.add_conditional_edges(
        "synthesize_result",
        _route_after_synthesis,
        {"llm_select_tool": "llm_select_tool", END: END},
    )

    return builder.compile()


# ── Convenience runner ─────────────────────────────────────────────────────

def run_agent(
    query: str,
    registry_path: str = "dtgs.db",
    max_iterations: int = 5,
) -> dict:
    """
    Convenience wrapper: run the agent pipeline for a single query.

    Args:
        query:          Natural language query.
        registry_path:  Path to the SQLite registry.
        max_iterations: Maximum tool-call iterations before forcing stop.

    Returns:
        Final AgentState dict (check ``messages`` for the conversation).
    """
    graph = build_agent_graph()
    initial: AgentState = {
        "messages": [],
        "query": query,
        "registry_path": registry_path,
        "retrieved_tools": [],
        "tool_call": None,
        "tool_result": None,
        "iterations": 0,
        "max_iterations": max_iterations,
    }
    return graph.invoke(initial)
