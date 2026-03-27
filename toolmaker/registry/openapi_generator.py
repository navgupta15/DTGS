"""
openapi_generator: Converts stored ToolSchemas (OpenAI format) into OpenAPI 3.1.0 specifications.
"""
from __future__ import annotations

import re


def _parse_rest_annotation(name: str, annotation_text: str) -> tuple[str, str]:
    """
    Extract verb and path from a full Spring Boot annotation string.
    Example: @RequestMapping(value="/{id}", method=RequestMethod.GET)
    """
    if not annotation_text:
        return "post", f"/rpc/{name}"
        
    # 1. Base annotation name
    match = re.search(r"@([A-Z][a-zA-Z]+Mapping)", annotation_text)
    if not match:
        return "post", f"/rpc/{name}"
        
    ann_name = match.group(1)
    
    # 2. Extract path (from path="..." or value="..." or default single arg)
    path_match = re.search(r'(?:value|path)\s*=\s*["\']([^"\']+)["\']', annotation_text)
    if not path_match:
        path_match = re.search(r'\(\s*["\']([^"\']+)["\']', annotation_text)
        
    path = path_match.group(1) if path_match else "/"
    if not path.startswith("/"):
        path = "/" + path
        
    # 3. Extract method
    verb_map = {
        "GetMapping": "get",
        "PostMapping": "post",
        "PutMapping": "put",
        "DeleteMapping": "delete",
        "PatchMapping": "patch",
    }
    
    verb = verb_map.get(ann_name)
    if not verb and ann_name == "RequestMapping":
        # Look for method=RequestMethod.GET
        method_match = re.search(r'method\s*=\s*(?:RequestMethod\.)?([A-Z]+)', annotation_text)
        verb = method_match.group(1).lower() if method_match else "post"
        
    if not verb:
        verb = "post"
        
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
        
        # Read the raw REST annotations saved by the AST parser (bypassing the LLM description completely)
        rest_anns = func.get("__rest_annotations", [])
        raw_annotation = rest_anns[0] if rest_anns else ""
        
        # Parse the REST path and verb directly out of the AST annotation string
        verb, path = _parse_rest_annotation(name, raw_annotation)
        
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
