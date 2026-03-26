"""
DTGS FastAPI Server.
Exposes the multi-tenant SQLite tool registry as standardized OpenAPI 3.1 specifications.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
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
    github_url: str
    namespace: str = "default"
    base_url: str = ""


@app.post("/api/v1/ingest", tags=["Management"])
async def ingest_repo(request: Request, payload: IngestRequest):
    """
    Trigger the DTGS Ingestion pipeline (Graph 1) dynamically via HTTP.
    This allows CI/CD or other agents to push new repos into the catalog on demand.
    """
    from toolmaker.graphs.ingestion_graph import run_ingestion
    
    logger.info(f"Dynamic ingestion requested for repo: {payload.github_url} (namespace: {payload.namespace})")
    db_path = getattr(request.app.state, "registry_path", "dtgs.db")
    
    # Run the ingestion synchronously (could be punted to background task later)
    result = run_ingestion(
        github_url=payload.github_url,
        registry_path=db_path,
        namespace=payload.namespace,
        base_url=payload.base_url
    )
    
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
        
    return {
        "status": "success",
        "namespace": payload.namespace,
        "tools_added": len(result.get("registry_ids", [])),
        "summary": result.get("summary")
    }
