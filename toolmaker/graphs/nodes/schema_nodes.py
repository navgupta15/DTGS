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
