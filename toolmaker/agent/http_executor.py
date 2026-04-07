"""
DTGS — HTTP Executor.

Executes real HTTP requests against a target backend using the OpenAPI spec
to map tool call arguments to the correct HTTP method, path, query params, and body.

Supports a dry-run/mock mode for testing without a live backend.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from toolmaker.agent.openapi_to_tools import resolve_operation


def execute_api_call(
    spec: dict,
    operation_id: str,
    arguments: dict[str, Any],
    dry_run: bool = False,
    timeout: float = 30.0,
) -> dict:
    """
    Execute an HTTP request based on an OpenAPI operation.

    Args:
        spec:          The full OpenAPI 3.1 spec dict.
        operation_id:  The operationId to invoke (e.g. "MyCtrl_addPet").
        arguments:     The arguments provided by the LLM tool call.
        dry_run:       If True, return the constructed request without executing.
        timeout:       HTTP request timeout in seconds.

    Returns:
        A dict with keys: status_code, body, method, url, request_body, dry_run
    """
    op = resolve_operation(spec, operation_id)
    if not op:
        return {
            "status_code": -1,
            "body": f"Operation '{operation_id}' not found in the OpenAPI spec.",
            "method": "unknown",
            "url": "unknown",
            "request_body": None,
            "dry_run": dry_run,
        }

    method = op["method"]
    path = op["path"]
    base_url = op["base_url"]
    operation = op["operation"]

    # 1. Identify path parameters from {param} syntax
    path_param_names = re.findall(r"\{([^}]+)\}", path)

    # 2. Build the actual URL by substituting path params
    url = path
    for pp in path_param_names:
        if pp in arguments:
            url = url.replace(f"{{{pp}}}", str(arguments[pp]))

    full_url = base_url.rstrip("/") + url

    # 3. Separate query params vs body params
    query_params: dict = {}
    body_params: dict = {}

    # Determine which params are query vs body based on the operation spec
    spec_params = operation.get("parameters", [])
    query_param_names = {p["name"] for p in spec_params if p.get("in") == "query"}
    path_param_set = set(path_param_names)

    for arg_name, arg_value in arguments.items():
        if arg_name in path_param_set:
            continue  # Already substituted in URL
        elif arg_name in query_param_names:
            query_params[arg_name] = arg_value
        elif method in ("get", "delete"):
            # For GET/DELETE, remaining params go to query
            query_params[arg_name] = arg_value
        else:
            # For POST/PUT/PATCH, remaining params go to body
            body_params[arg_name] = arg_value

    # 4. Construct the result
    result = {
        "method": method.upper(),
        "url": full_url,
        "query_params": query_params if query_params else None,
        "request_body": body_params if body_params else None,
        "dry_run": dry_run,
    }

    if dry_run:
        result["status_code"] = 0
        result["body"] = (
            f"[DRY RUN] Would execute: {method.upper()} {full_url}\n"
            f"Query Params: {json.dumps(query_params) if query_params else 'None'}\n"
            f"Request Body: {json.dumps(body_params, indent=2) if body_params else 'None'}"
        )
        return result

    # 5. Execute the real HTTP request
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(
                method=method.upper(),
                url=full_url,
                params=query_params if query_params else None,
                json=body_params if body_params else None,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            
            # Try to parse response as JSON, fall back to text
            try:
                resp_body = response.json()
            except Exception:
                resp_body = response.text

            result["status_code"] = response.status_code
            result["body"] = resp_body
            return result

    except httpx.ConnectError:
        result["status_code"] = -1
        result["body"] = (
            f"Connection refused: Could not connect to {full_url}. "
            f"Is the target backend running? "
            f"Use --dry-run to test without a live server."
        )
        return result
    except Exception as exc:
        result["status_code"] = -1
        result["body"] = f"HTTP request failed: {exc}"
        return result
