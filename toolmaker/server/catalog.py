"""
DTGS FastAPI Server.
Exposes the multi-tenant SQLite tool registry as standardized OpenAPI 3.1 specifications.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from toolmaker.registry.sqlite_registry import ToolRegistry
from toolmaker.registry.openapi_generator import generate_openapi_spec
from toolmaker.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Retrieve the registry path from app state (injected by CLI)
    db_path = getattr(app.state, "registry_path", "dtgs.db")
    app.state.registry = ToolRegistry(db_path)
    logger.info(f"Connected to registry: {db_path}")
    yield
    # Cleanup if needed


app = FastAPI(
    title="DTGS Tool Catalog",
    description="Dynamic Tool Generation System — OpenAPI Provider",
    version="1.0.0",
    lifespan=lifespan,
)

os.makedirs("toolmaker/server/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="toolmaker/server/static"), name="static")

@app.get("/", include_in_schema=False)
async def dashboard():
    """Serve the single-page dashboard."""
    return FileResponse("toolmaker/server/static/index.html")

@app.get("/api/v1/namespaces", tags=["Catalog"])
async def list_namespaces(request: Request):
    """List all ingested namespaces and their tool counts."""
    registry: ToolRegistry = request.app.state.registry
    return registry.list_namespaces()

@app.delete("/api/v1/{namespace}", tags=["Management"])
async def delete_namespace(request: Request, namespace: str):
    """Delete all tools for a given namespace."""
    registry: ToolRegistry = request.app.state.registry
    count = registry.count(namespace)
    registry.delete_namespace(namespace)
    return {"status": "success", "namespace": namespace, "deleted_count": count}

@app.get("/api/v1/{namespace}/openapi.json", tags=["Catalog"])
async def get_openapi_spec(request: Request, namespace: str):
    """
    Returns the complete OpenAPI 3.1.0 JSON specification for the requested namespace.
    """
    logger.info(f"Serving OpenAPI spec for namespace: '{namespace}'")
    registry: ToolRegistry = request.app.state.registry
    
    # We load limit=500 for now. For a massive microservice we'd want pagination
    # or just a higher limit, but 500 endpoints is plenty for a standard API.
    schemas = registry.get_all(namespace=namespace, limit=1000)
    
    if not schemas:
        raise HTTPException(
            status_code=404, 
            detail=f"No tools found for namespace '{namespace}'. Has it been ingested?"
        )
        
    # We don't store base_url inside individual ToolSchema dicts currently, 
    # but we can grab it from a side-channel or just omit it and let the client provide it. 
    # Let's peek into the DB to find the base_url. The base_url is stored on the tools table row.
    # To get the base_url efficiently, we'll run a quick query.
    base_url = ""
    with registry._connect() as conn:
        row = conn.execute(
            "SELECT base_url FROM tools WHERE namespace = ? LIMIT 1", 
            (namespace,)
        ).fetchone()
        if row and row["base_url"]:
            base_url = row["base_url"]
            
    spec = generate_openapi_spec(
        namespace=namespace,
        schemas=schemas,
        base_url=base_url
    )
    
    return spec

@app.get("/api/v1/{namespace}/tools", tags=["Catalog"])
async def get_tools_spec(request: Request, namespace: str):
    """
    Returns the LLM-compatible tools format (OpenAI function spec) for the requested namespace.
    """
    from toolmaker.agent.openapi_to_tools import openapi_to_tools

    logger.info(f"Serving Tools for namespace: '{namespace}'")
    registry: ToolRegistry = request.app.state.registry
    
    schemas = registry.get_all(namespace=namespace, limit=1000)
    
    if not schemas:
        raise HTTPException(
            status_code=404, 
            detail=f"No tools found for namespace '{namespace}'. Has it been ingested?"
        )
        
    base_url = ""
    with registry._connect() as conn:
        row = conn.execute(
            "SELECT base_url FROM tools WHERE namespace = ? LIMIT 1", 
            (namespace,)
        ).fetchone()
        if row and row["base_url"]:
            base_url = row["base_url"]
            
    spec = generate_openapi_spec(
        namespace=namespace,
        schemas=schemas,
        base_url=base_url
    )
    
    return openapi_to_tools(spec)


@app.get("/api/v1/{namespace}/tools/search", tags=["Catalog"])
async def search_tools(
    request: Request,
    namespace: str,
    q: str = "",
    top_k: int = 15,
    rest_only: bool = True,
):
    """
    Search for tools relevant to a natural language query.
    Returns filtered tools in OpenAI function-calling format.

    Used by dtgs-sdk for per-query tool filtering when namespaces have many tools.
    """
    from toolmaker.agent.openapi_to_tools import openapi_to_tools

    logger.info(f"Tool search for namespace '{namespace}': q='{q}', top_k={top_k}")
    registry: ToolRegistry = request.app.state.registry

    if not q:
        # No query — return all tools (respecting rest_only)
        if rest_only:
            schemas = registry.get_rest_tools(namespace=namespace, limit=top_k)
        else:
            schemas = registry.get_all(namespace=namespace, limit=top_k)
    else:
        # Try semantic search if embeddings exist
        import os
        query_embedding: list[float] | None = None
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                resp = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=[q],
                )
                query_embedding = resp.data[0].embedding
            except Exception:
                pass

        schemas = registry.search(
            query=q,
            namespace=namespace,
            query_embedding=query_embedding,
            top_k=top_k,
        )

    if not schemas:
        raise HTTPException(
            status_code=404,
            detail=f"No tools found for namespace '{namespace}' matching query '{q}'."
        )

    # Convert to OpenAPI spec then to OpenAI tools format
    base_url = ""
    with registry._connect() as conn:
        row = conn.execute(
            "SELECT base_url FROM tools WHERE namespace = ? LIMIT 1",
            (namespace,)
        ).fetchone()
        if row and row["base_url"]:
            base_url = row["base_url"]

    spec = generate_openapi_spec(namespace=namespace, schemas=schemas, base_url=base_url)
    return openapi_to_tools(spec)


@app.get("/api/v1/{namespace}/controllers", tags=["Catalog"])
async def list_controllers(request: Request, namespace: str):
    """
    List all controllers (grouped by class_name) for the given namespace.
    Returns controller-level summaries with API counts.
    """
    registry: ToolRegistry = request.app.state.registry
    controllers = registry.get_controller_groups(namespace)

    if not controllers:
        raise HTTPException(
            status_code=404,
            detail=f"No controllers found for namespace '{namespace}'."
        )

    return controllers


@app.get("/api/v1/{namespace}/controllers/{class_name}/tools", tags=["Catalog"])
async def get_controller_tools(request: Request, namespace: str, class_name: str):
    """
    Returns tools for a specific controller in OpenAI function-calling format.
    """
    from toolmaker.agent.openapi_to_tools import openapi_to_tools

    registry: ToolRegistry = request.app.state.registry
    schemas = registry.get_tools_by_class(namespace, class_name)

    if not schemas:
        raise HTTPException(
            status_code=404,
            detail=f"No tools found for controller '{class_name}' in namespace '{namespace}'."
        )

    base_url = ""
    with registry._connect() as conn:
        row = conn.execute(
            "SELECT base_url FROM tools WHERE namespace = ? LIMIT 1",
            (namespace,)
        ).fetchone()
        if row and row["base_url"]:
            base_url = row["base_url"]

    spec = generate_openapi_spec(namespace=namespace, schemas=schemas, base_url=base_url)
    return openapi_to_tools(spec)


class IngestRequest(BaseModel):
    source_type: str = "github"
    github_url: str = ""
    local_path: str = ""
    namespace: str = "default"
    base_url: str = ""
    include_packages: list[str] | None = None
    enhance: bool = True


@app.post("/api/v1/ingest", tags=["Management"])
async def ingest_repo(request: Request, payload: IngestRequest):
    """
    Trigger the DTGS Ingestion pipeline (Graph 1) dynamically via HTTP.
    This allows CI/CD or other agents to push new repos into the catalog on demand.
    """
    from toolmaker.graphs.ingestion_graph import run_ingestion
    
    logger.info(f"Dynamic ingestion requested for namespace: {payload.namespace} ({payload.source_type})")
    db_path = getattr(request.app.state, "registry_path", "dtgs.db")
    
    # Run the ingestion synchronously (could be punted to background task later)
    result = run_ingestion(
        github_url=payload.github_url if payload.source_type == "github" else None,
        local_path=payload.local_path if payload.source_type == "local" else None,
        registry_path=db_path,
        namespace=payload.namespace,
        base_url=payload.base_url,
        enhance_descriptions=payload.enhance,
        include_patterns=payload.include_packages
    )
    
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
        
    return {
        "status": "success",
        "namespace": payload.namespace,
        "tools_added": len(result.get("registry_ids", [])),
        "summary": result.get("summary")
    }


# ── Chat Endpoint ──────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str  # "user", "assistant", "tool"
    content: str
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None

class ChatRequest(BaseModel):
    namespace: str
    message: str
    history: list[ChatMessage] = []
    provider: str = "ollama"
    model: str = "qwen3:8b"
    dry_run: bool = True


@app.post("/api/v1/chat", tags=["Chat"])
def chat_with_agent(request: Request, payload: ChatRequest):
    """
    Send a message to the DTGS chat agent. Uses the dtgs_sdk locally
    to filter tools via query and execute API calls.
    """
    import json
    import os
    from dtgs_sdk import DTGSToolkit
    
    # 1. Initialize DTGSToolkit using the running server's base URL
    server_url = str(request.base_url).rstrip("/")
    toolkit = DTGSToolkit(
        server_url=server_url,
        namespace=payload.namespace,
        dry_run=payload.dry_run
    )
    
    # Get tools dynamically filtered by user query
    tools = toolkit.get_tools(query=payload.message)

    # 2. Set up the LLM
    os.environ["DTGS_PROVIDER"] = payload.provider
    os.environ["DTGS_MODEL"] = payload.model

    try:
        from toolmaker.graphs.nodes.agent_nodes import _get_chat_model
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        llm = _get_chat_model()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load LLM ({payload.provider}/{payload.model}): {e}")

    # 3. Build conversation
    system_prompt = (
        f"You are DTGS Agent, an AI assistant that discovers and calls REST APIs.\n"
        f"You currently have access to {len(tools)} API tools for the '{payload.namespace}' service.\n"
        f"When the user asks something, identify the right API tool, call it, and interpret the result.\n"
        f"If no tool matches, say so clearly. Do not invent tool names."
    )

    messages = [SystemMessage(content=system_prompt)]

    # Rebuild history
    for msg in payload.history:
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            messages.append(AIMessage(content=msg.content))
        elif msg.role == "tool":
            messages.append(ToolMessage(content=msg.content, tool_call_id=msg.tool_call_id or ""))

    messages.append(HumanMessage(content=payload.message))

    # 4. Call LLM with tools
    llm_with_tools = llm.bind_tools(tools) if tools else llm

    try:
        response: AIMessage = llm_with_tools.invoke(messages)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {e}")

    # 5. Process tool calls
    tool_calls_output = []
    final_text = response.content or ""

    if response.tool_calls:
        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_id = tc["id"]

            try:
                result = toolkit.execute(tool_name, tool_args)
            except Exception as e:
                result = {
                    "method": "ERROR",
                    "url": "ERROR",
                    "status_code": -1,
                    "body": f"Failed to execute {tool_name}: {e}",
                    "dry_run": payload.dry_run
                }

            tool_calls_output.append({
                "name": tool_name,
                "args": tool_args,
                "method": result.get("method", ""),
                "url": result.get("url", ""),
                "status_code": result.get("status_code", -1),
                "response": result.get("body", ""),
                "dry_run": payload.dry_run,
            })

            # Feed result back to LLM for synthesis
            result_str = json.dumps(result.get("body", ""), indent=2) if isinstance(result.get("body"), (dict, list)) else str(result.get("body", ""))
            messages.append(response)
            messages.append(ToolMessage(content=result_str, tool_call_id=tool_id))

        # Get final synthesis
        try:
            synthesis: AIMessage = llm_with_tools.invoke(messages)
            final_text = synthesis.content or ""
        except Exception:
            final_text = "I called the API but couldn't generate a summary."

    return {
        "response": final_text,
        "tool_calls": tool_calls_output,
    }

