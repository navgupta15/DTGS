"""
DTGS — OpenAPI to LLM Tools Converter.

Converts an OpenAPI 3.1.0 specification into a list of OpenAI function-calling
compatible tool schemas that can be passed directly to model.bind_tools().
"""
from __future__ import annotations

import re


def openapi_to_tools(spec: dict) -> list[dict]:
    """
    Convert an OpenAPI 3.1 spec dict into a list of OpenAI-format tool schemas.

    Each operation in the spec becomes one tool with:
      - name = operationId
      - description = summary + description
      - parameters = merged path/query params + requestBody schema

    Args:
        spec: A parsed OpenAPI 3.1.0 JSON dict.

    Returns:
        List of dicts in OpenAI tool format:
        [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]
    """
    tools: list[dict] = []
    base_url = ""
    servers = spec.get("servers", [])
    if servers:
        base_url = servers[0].get("url", "")

    paths = spec.get("paths", {})

    for path, methods in paths.items():
        for method, operation in methods.items():
            if method not in ("get", "post", "put", "delete", "patch"):
                continue

            op_id = operation.get("operationId", f"{method}_{path}")
            summary = operation.get("summary", "")
            description = operation.get("description", "")

            full_desc = f"{summary}\n{description}".strip() if description != summary else summary
            full_desc += f"\n\n[HTTP {method.upper()} {base_url}{path}]"

            # Build parameters schema
            properties: dict = {}
            required: list[str] = []

            # Path and query parameters
            for param in operation.get("parameters", []):
                p_name = param["name"]
                p_schema = param.get("schema", {"type": "string"})
                p_desc = param.get("description", p_schema.get("description", ""))
                properties[p_name] = {
                    "type": p_schema.get("type", "string"),
                    "description": p_desc,
                }
                # Carry over nested properties for object params
                if "properties" in p_schema:
                    properties[p_name]["properties"] = p_schema["properties"]
                if "items" in p_schema:
                    properties[p_name]["items"] = p_schema["items"]
                if param.get("required", False):
                    required.append(p_name)

            # Request body (POST/PUT/PATCH)
            req_body = operation.get("requestBody")
            if req_body:
                content = req_body.get("content", {})
                json_schema = content.get("application/json", {}).get("schema", {})
                body_props = json_schema.get("properties", {})
                body_required = json_schema.get("required", [])

                for bp_name, bp_schema in body_props.items():
                    properties[bp_name] = bp_schema
                    if bp_name in body_required:
                        required.append(bp_name)

            tool = {
                "type": "function",
                "function": {
                    "name": op_id,
                    "description": full_desc,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
            tools.append(tool)

    return tools


def resolve_operation(spec: dict, operation_id: str) -> dict | None:
    """
    Find the operation details (method, path, parameters, requestBody) for a given operationId.

    Returns a dict: {"method": str, "path": str, "operation": dict, "base_url": str}
    or None if not found.
    """
    base_url = ""
    servers = spec.get("servers", [])
    if servers:
        base_url = servers[0].get("url", "")

    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            if operation.get("operationId") == operation_id:
                return {
                    "method": method,
                    "path": path,
                    "operation": operation,
                    "base_url": base_url,
                }
    return None
