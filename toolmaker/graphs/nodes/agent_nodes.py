"""
DTGS — Agent Query Pipeline Nodes.

Implements 5 nodes for Graph 2:
  receive_query -> search_tools -> llm_select_tool -> execute_tool -> synthesize_result

Model backends (controlled via environment variables):
  DTGS_PROVIDER=openai   (default) -- uses ChatOpenAI, requires OPENAI_API_KEY
  DTGS_PROVIDER=ollama             -- uses ChatOllama, requires Ollama running locally
  DTGS_MODEL=<model>              -- model name (default: gpt-4o-mini / llama3.2)
  DTGS_BASE_URL=<url>             -- Ollama server URL (default: http://localhost:11434)
"""
from __future__ import annotations

import json
import os

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.language_models.chat_models import BaseChatModel

from toolmaker.graphs.state import AgentState
from toolmaker.registry.sqlite_registry import ToolRegistry


# ── Model factory ──────────────────────────────────────────────────────────

def _get_chat_model() -> BaseChatModel:
    """
    Return a chat model based on environment configuration.

    Environment variables:
      DTGS_PROVIDER  'openai' (default) or 'ollama'
      DTGS_MODEL     model name -- default 'gpt-4o-mini' (openai) / 'llama3.2' (ollama)
      DTGS_BASE_URL  Ollama server URL -- default 'http://localhost:11434'
      OPENAI_API_KEY required when DTGS_PROVIDER=openai
    """
    provider = os.environ.get("DTGS_PROVIDER", "openai").lower()

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        model = os.environ.get("DTGS_MODEL", "llama3.2")
        base_url = os.environ.get("DTGS_BASE_URL", "http://localhost:11434")
        return ChatOllama(model=model, base_url=base_url, temperature=0)

    # Default: OpenAI
    from langchain_openai import ChatOpenAI
    model = os.environ.get("DTGS_MODEL", "gpt-4o-mini")
    return ChatOpenAI(model=model, temperature=0)


_SYSTEM_PROMPT = """You are DTGS Agent, an AI assistant that discovers and calls tools
extracted from Java codebases.

You will be given a list of available tools. Your job is to:
1. Identify which tool best satisfies the user's request.
2. Call that tool with the correct arguments.
3. Return a clear, concise answer based on the tool result.

If no tool matches, say so clearly. Do not hallucinate tool names."""


# ── Node 1: receive_query ─────────────────────────────────────────────────

def receive_query(state: AgentState) -> dict:
    """Initialise the conversation with a system prompt and the user's query."""
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=state["query"]),
    ]
    return {
        "messages": messages,
        "iterations": 0,
        "tool_call": None,
        "tool_result": None,
    }


# ── Node 2: search_tools ──────────────────────────────────────────────────

def search_tools(state: AgentState) -> dict:
    """
    Search the registry for tools relevant to the user's query.
    Uses semantic search if an OpenAI API key is available, else keyword.
    """
    registry = ToolRegistry(state.get("registry_path", "dtgs.db"))
    query = state["query"]

    # Try semantic search first (only works with OpenAI embeddings)
    api_key = os.environ.get("OPENAI_API_KEY", "")
    query_embedding: list[float] | None = None

    if api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            resp = client.embeddings.create(
                model="text-embedding-3-small",
                input=[query],
            )
            query_embedding = resp.data[0].embedding
        except Exception:
            pass

    tools = registry.search(query=query, query_embedding=query_embedding, top_k=8)
    return {"retrieved_tools": tools}


# ── Node 3: llm_select_tool ───────────────────────────────────────────────

def llm_select_tool(state: AgentState) -> dict:
    """
    Call the LLM with retrieved tools as the ``tools=`` parameter.
    The LLM either issues a tool_call or responds directly.
    """
    model = _get_chat_model()

    tools = state.get("retrieved_tools", [])
    # Bind tools to the model in OpenAI function-calling format
    model_with_tools = model.bind_tools(tools) if tools else model

    response: AIMessage = model_with_tools.invoke(state["messages"])

    updates: dict = {
        "messages": [response],
        "iterations": state.get("iterations", 0) + 1,
    }

    # Capture the first tool_call if the LLM issued one
    if response.tool_calls:
        tc = response.tool_calls[0]
        updates["tool_call"] = {
            "name": tc["name"],
            "args": tc["args"],
            "id": tc["id"],
        }
    else:
        updates["tool_call"] = None

    return updates


# ── Node 4: execute_tool ──────────────────────────────────────────────────

def execute_tool(state: AgentState) -> dict:
    """
    Execute the tool selected by the LLM.

    Currently returns a structured explanation of the call.
    In Phase 2 this will proxy to a subprocess/HTTP endpoint.
    """
    tc = state.get("tool_call")
    if not tc:
        return {"tool_result": "No tool was selected."}

    # Build a human-readable result explaining the call
    result = {
        "status": "simulated",
        "tool": tc["name"],
        "args": tc["args"],
        "note": (
            "Tool execution is simulated in Phase 1. "
            "Actual sandboxed execution will be added in Phase 2."
        ),
    }
    result_str = json.dumps(result, indent=2)

    tool_msg = ToolMessage(
        content=result_str,
        tool_call_id=tc.get("id", "unknown"),
    )
    return {"tool_result": result_str, "messages": [tool_msg]}


# ── Node 5: synthesize_result ─────────────────────────────────────────────

def synthesize_result(state: AgentState) -> dict:
    """
    Ask the LLM to synthesize a final answer from the tool result.
    """
    model = _get_chat_model()
    response: AIMessage = model.invoke(state["messages"])
    return {"messages": [response]}
