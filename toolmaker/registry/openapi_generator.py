"""
openapi_generator: Converts stored ToolSchemas (OpenAI format) into OpenAPI 3.1.0 specifications.
"""
from __future__ import annotations

import re


def _parse_rest_annotation(description: str) -> tuple[str, str]:
    """
    Extract the HTTP method and path from the tool description.
    Expected format: "REST endpoint (@GetMapping(\"/api/pets\")): ..."
    Fallback: POST /rpc/{name}
    """
    match = re.search(r"@([A-Z][a-zA-Z]+Mapping)(?:\(\s*[\"']([^\"']+)[\"']\s*\))?", description)
    if not match:
        return "post", "/rpc/unknown"
    
    annotation_name = match.group(1)
    path = match.group(2) or "/"
    
    # Map Spring annotations to HTTP verbs
    verb_map = {
        "GetMapping": "get",
        "PostMapping": "post",
        "PutMapping": "put",
        "DeleteMapping": "delete",
        "PatchMapping": "patch",
        "RequestMapping": "post",  # fallback if method not specified
    }
    verb = verb_map.get(annotation_name, "post")
    
    # Ensure path starts with /
    if not path.startswith("/"):
        path = "/" + path
        
    return verb, path


def generate_openapi_spec(
    namespace: str,
    schemas: list[dict],
    base_url: str = "",
) -> dict:
    """
    Generate an OpenAPI 3.1.0 JSON specification from a list of OpenAI tool schemas.
    
    Args:
        namespace: The tenant namespace (used as the API title).
        schemas: List of dicts where each dict is an OpenAI function schema.
        base_url: The target server URL.
        
    Returns:
        A fully compliant OpenAPI 3.1.0 dictionary.
    """
    openapi = {
        "openapi": "3.1.0",
        "info": {
            "title": f"DTGS Generated API: {namespace}",
            "version": "1.0.0",
            "description": "Auto-generated OpenAPI specification from DTGS AST Analysis."
        },
        "servers": [{"url": base_url}] if base_url else [],
        "paths": {}
    }

    for schema in schemas:
        func = schema.get("function", {})
        if not func:
            continue
            
        name = func.get("name", "unknown")
        description = func.get("description", "")
        params = func.get("parameters", {})
        
        # Parse the REST path and verb out of the description
        verb, path = _parse_rest_annotation(description)
        
        # Identify path parameters from the `{param}` syntax in the path
        path_param_names = re.findall(r"\{([^}]+)\}", path)
        
        properties = params.get("properties", {})
        required = params.get("required", [])
        
        open_parameters = []
        request_body = None
        
        # Map parameters to either query, path, or body
        if verb in ("get", "delete"):
            # GET/DELETE: parameters go in query or path
            for p_name, p_schema in properties.items():
                in_loc = "path" if p_name in path_param_names else "query"
                open_parameters.append({
                    "name": p_name,
                    "in": in_loc,
                    "required": p_name in required,
                    "schema": p_schema,
                    "description": p_schema.get("description", "")
                })
        else:
            # POST/PUT/PATCH: extract path parameters, the rest go to JSON body
            body_props = {}
            for p_name, p_schema in properties.items():
                if p_name in path_param_names:
                    open_parameters.append({
                        "name": p_name,
                        "in": "path",
                        "required": True,
                        "schema": p_schema,
                        "description": p_schema.get("description", "")
                    })
                else:
                    body_props[p_name] = p_schema
            
            if body_props:
                body_required = [r for r in required if r in body_props]
                request_body = {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": body_props,
                                "required": body_required
                            }
                        }
                    },
                    "required": len(body_required) > 0
                }
        
        # Build the operation object
        operation = {
            "operationId": name,
            "summary": name,
            "description": description,
            "responses": {
                "200": {
                    "description": "Successful operation"
                }
            }
        }
        
        if open_parameters:
            operation["parameters"] = open_parameters
        if request_body:
            operation["requestBody"] = request_body
            
        # Add to paths
        if path not in openapi["paths"]:
            openapi["paths"][path] = {}
            
        openapi["paths"][path][verb] = operation

    return openapi
