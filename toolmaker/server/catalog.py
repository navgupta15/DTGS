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
