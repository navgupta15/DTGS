"""
DTGS — Schema & Embedding Nodes.

Implements two nodes for Graph 1:
  generate_schemas → embed_tools
"""
from __future__ import annotations

import os

from toolmaker.graphs.state import IngestionState
from toolmaker.logger import logger


# ── Node: generate_schemas ────────────────────────────────────────────────

def generate_schemas(state: IngestionState) -> dict:
    """
    Convert each AnalyzedMethod dict → OpenAI function-calling ToolSchema.
    """
    from toolmaker.models import AnalyzedMethod, JavaParameter, AnalyzedClass, ClassField
    from toolmaker.analyzer.schema_generator import method_to_tool_schema
    from toolmaker.registry.sqlite_registry import ToolRegistry
    import hashlib
    import json

    registry = ToolRegistry(state.get("registry_path", "dtgs.db"))
    namespace = state.get("namespace", "default")

    # Fetch existing tools and build a lookup
    existing_tools = {}
    with registry._connect() as conn:
        rows = conn.execute("SELECT name, method_hash, description, embedding FROM tools WHERE namespace = ?", (namespace,)).fetchall()
        for r in rows:
            from toolmaker.registry.sqlite_registry import _unpack_embedding
            emb_blob = r["embedding"]
            emb = _unpack_embedding(emb_blob) if emb_blob else None
            existing_tools[r["name"]] = {
                "hash": r["method_hash"],
                "description": r["description"],
                "embedding": emb,
            }

    # Build global Class Registry from this ingestion run
    raw_classes = state.get("analyzed_classes", [])
    classes_registry: dict[str, AnalyzedClass] = {}
    for rc in raw_classes:
        fields = [ClassField(**f) for f in rc.get("fields", [])]
        ac = AnalyzedClass(**{**rc, "fields": fields})
        classes_registry[ac.class_name] = ac

    schemas: list[dict] = []
    for raw in state.get("analyzed_methods", []):
        # Reconstruct the Pydantic model from the serialised dict
        params = [JavaParameter(**p) for p in raw.get("parameters", [])]
        method = AnalyzedMethod(**{**raw, "parameters": params})
        schema = method_to_tool_schema(method, classes_registry)
        schema_dict = schema.model_dump()
        
        # Calculate robust hash of the raw tool JSON before enhancement
        func_dump = json.dumps(schema_dict.get("function", {}), sort_keys=True)
        method_hash = hashlib.md5(func_dump.encode()).hexdigest()
        schema_dict["__method_hash"] = method_hash
        
        name = schema_dict.get("function", {}).get("name")
        
        # Cache check
        if name in existing_tools and existing_tools[name]["hash"] == method_hash:
            logger.debug(f"Cache hit for schema: {name}")
            schema_dict["__skip_enhance"] = True
            schema_dict["function"]["description"] = existing_tools[name]["description"]
            if existing_tools[name]["embedding"]:
                schema_dict["__cached_embedding"] = existing_tools[name]["embedding"]
                
        schemas.append(schema_dict)

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
    
    # Just to count how many we actually need to enhance
    to_enhance = sum(1 for s in schemas if not s.get("__skip_enhance") and s.get("function"))
    if to_enhance > 0:
        logger.info(f"Enhancing {to_enhance} schema descriptions using LLM...")
    else:
        logger.info("All schemas hit the cache. Skipping LLM enhancement.")
        
    from langchain_core.messages import HumanMessage, SystemMessage
    
    sys_prompt = SystemMessage(
        content="You are an expert API documentation writer for AI agents. "
                "Given a raw tool function, rewrite its description in 1-2 clear, "
                "comprehensive sentences. Explain what the tool does, what parameters it takes, "
                "and when an AI should use it. Only output the new description, nothing else."
    )

    current_idx = 0
    for schema in schemas:
        func = schema.get("function", {})
        if not func:
            enhanced_schemas.append(schema)
            continue
            
        if schema.get("__skip_enhance"):
            enhanced_schemas.append(schema)
            continue
            
        current_idx += 1
        name = func.get("name")
        params = func.get("parameters", {})
        prompt = (
            f"Tool Name: {name}\n"
            f"Current Description: {func.get('description')}\n"
            f"Parameters: {params}\n\n"
            "Write the new description strictly."
        )
        
        logger.info(f"[{current_idx}/{to_enhance}] Calling LLM for tool: {name}")
        
        try:
            # invoke the LLM
            response = model.invoke([sys_prompt, HumanMessage(content=prompt)])
            new_desc = response.content.strip()
            
            logger.debug(f"LLM rewrote '{name}' description to: {new_desc}")
            
            # Update the schema inline
            func["description"] = new_desc
            enhanced_schemas.append(schema)
        except Exception as e:
            warnings.warn(f"[DTGS] LLM enhancement failed for {name}: {e}", stacklevel=2)
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
        
        texts_to_embed = []
        indices_to_embed = []
        embeddings: list[list[float] | None] = [None] * len(schemas)
        
        for i, s in enumerate(schemas):
            if "__cached_embedding" in s and s["__cached_embedding"] is not None:
                embeddings[i] = s["__cached_embedding"]
            else:
                text = s.get("function", {}).get("description", s.get("function", {}).get("name", ""))
                texts_to_embed.append(text)
                indices_to_embed.append(i)

        if texts_to_embed:
            logger.info(f"Generating embeddings for {len(texts_to_embed)} tools...")
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=texts_to_embed,
            )
            for text_idx, data_item in enumerate(response.data):
                orig_idx = indices_to_embed[text_idx]
                embeddings[orig_idx] = data_item.embedding
                
        return {"embeddings": embeddings}

    except Exception as exc:
        import warnings
        warnings.warn(
            f"[DTGS] Embedding failed, falling back to keyword search: {exc}",
            stacklevel=2,
        )
        # If partial failure, those hit cache will still have it. The others will be empty.
        # It's safest to return the partially filled array.
        return {"embeddings": embeddings}
