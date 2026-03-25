"""
DTGS — Schema & Embedding Nodes.

Implements two nodes for Graph 1:
  generate_schemas → embed_tools
"""
from __future__ import annotations

import os

from toolmaker.graphs.state import IngestionState


# ── Node: generate_schemas ────────────────────────────────────────────────

def generate_schemas(state: IngestionState) -> dict:
    """
    Convert each AnalyzedMethod dict → OpenAI function-calling ToolSchema.
    """
    from toolmaker.models import AnalyzedMethod, JavaParameter
    from toolmaker.analyzer.schema_generator import method_to_tool_schema

    schemas: list[dict] = []
    for raw in state.get("analyzed_methods", []):
        # Reconstruct the Pydantic model from the serialised dict
        params = [JavaParameter(**p) for p in raw.get("parameters", [])]
        method = AnalyzedMethod(**{**raw, "parameters": params})
        schema = method_to_tool_schema(method)
        schemas.append(schema.model_dump())

    return {"tool_schemas": schemas}


# ── Node: enhance_descriptions ────────────────────────────────────────────

def enhance_descriptions(state: IngestionState) -> dict:
    """
    Given a list of tool schemas, use the configured LLM to rewrite and
    expand their descriptions for better AI use.
    Skipped if state["enhance_descriptions"] is False.
    """
    schemas = state.get("tool_schemas", [])
    if not schemas or not state.get("enhance_descriptions", True):
        return {"tool_schemas": schemas}

    from toolmaker.graphs.nodes.agent_nodes import _get_chat_model
    import warnings
    
    try:
        model = _get_chat_model()
    except Exception as e:
        warnings.warn(f"[DTGS] Failed to load LLM for enhancement: {e}", stacklevel=2)
        return {"tool_schemas": schemas}

    enhanced_schemas = []
    
    from langchain_core.messages import HumanMessage, SystemMessage
    
    sys_prompt = SystemMessage(
        content="You are an expert API documentation writer for AI agents. "
                "Given a raw tool function, rewrite its description in 1-2 clear, "
                "comprehensive sentences. Explain what the tool does, what parameters it takes, "
                "and when an AI should use it. Only output the new description, nothing else."
    )

    for schema in schemas:
        func = schema.get("function", {})
        if not func:
            enhanced_schemas.append(schema)
            continue
            
        params = func.get("parameters", {})
        prompt = (
            f"Tool Name: {func.get('name')}\n"
            f"Current Description: {func.get('description')}\n"
            f"Parameters: {params}\n\n"
            "Write the new description strictly."
        )
        
        try:
            # invoke the LLM
            response = model.invoke([sys_prompt, HumanMessage(content=prompt)])
            new_desc = response.content.strip()
            
            # Update the schema inline
            func["description"] = new_desc
            enhanced_schemas.append(schema)
        except Exception as e:
            warnings.warn(f"[DTGS] LLM enhancement failed for {func.get('name')}: {e}", stacklevel=2)
            enhanced_schemas.append(schema)

    return {"tool_schemas": enhanced_schemas}



# ── Node: embed_tools ─────────────────────────────────────────────────────

def embed_tools(state: IngestionState) -> dict:
    """
    Generate embedding vectors for each tool schema's description.

    Uses OpenAI ``text-embedding-3-small`` when OPENAI_API_KEY is set.
    Falls back to empty embeddings (keyword search will be used instead).
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    schemas = state.get("tool_schemas", [])

    if not api_key or not schemas:
        # No API key or no schemas — skip embedding gracefully
        return {"embeddings": []}

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        texts = [
            s.get("function", {}).get("description", s.get("function", {}).get("name", ""))
            for s in schemas
        ]

        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        embeddings = [item.embedding for item in response.data]
        return {"embeddings": embeddings}

    except Exception as exc:
        import warnings
        warnings.warn(
            f"[DTGS] Embedding failed, falling back to keyword search: {exc}",
            stacklevel=2,
        )
        return {"embeddings": []}
