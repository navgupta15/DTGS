"""
DTGS SDK — HTTP Executor.

Executes LLM tool calls as HTTP requests directly against the target backend.
DTGS server is NOT involved in execution — this module talks directly to the
backend using the cached OpenAPI spec to resolve routes.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx


class ToolExecutor:
    """
    Executes tool calls directly against the target backend API.

    Uses the OpenAPI spec to resolve an ``operationId`` to its HTTP method,
    path, and parameters, then makes a direct HTTP request.

    Args:
        openapi_spec: The full OpenAPI 3.1 spec dict (cached from DTGS).
        dry_run: If ``True``, return the constructed request without executing.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        openapi_spec: dict,
        dry_run: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self.spec = openapi_spec
        self.dry_run = dry_run
        self.timeout = timeout

        # Extract base URL from spec
        servers = self.spec.get("servers", [])
        self.base_url = servers[0].get("url", "") if servers else ""

    def execute(self, operation_id: str, arguments: dict[str, Any]) -> dict:
        """
        Execute an HTTP request for the given operationId.

        Args:
            operation_id: The operationId from the tool schema.
            arguments: The arguments dict from the LLM's tool call.

        Returns:
            Dict with keys: ``status_code``, ``body``, ``method``, ``url``,
            ``request_body``, ``query_params``, ``dry_run``.
        """
        op = self._resolve_operation(operation_id)
        if not op:
            return {
                "status_code": -1,
                "body": f"Operation '{operation_id}' not found in the OpenAPI spec.",
                "method": "unknown",
                "url": "unknown",
                "request_body": None,
                "query_params": None,
                "dry_run": self.dry_run,
            }

        method = op["method"]
        path = op["path"]
        operation = op["operation"]

        # 1. Identify path parameters
        path_param_names = re.findall(r"\{([^}]+)\}", path)

        # 2. Substitute path parameters into URL
        url = path
        for pp in path_param_names:
            if pp in arguments:
                url = url.replace(f"{{{pp}}}", str(arguments[pp]))

        full_url = self.base_url.rstrip("/") + url

        # 3. Separate query params from body params
        query_params: dict = {}
        body_params: dict = {}

        spec_params = operation.get("parameters", [])
        query_param_names = {p["name"] for p in spec_params if p.get("in") == "query"}
        path_param_set = set(path_param_names)

        for arg_name, arg_value in arguments.items():
            if arg_name in path_param_set:
                continue  # Already substituted
            elif arg_name in query_param_names:
                query_params[arg_name] = arg_value
            elif method in ("get", "delete"):
                query_params[arg_name] = arg_value
            else:
                body_params[arg_name] = arg_value

        # 4. Build result dict
        result: dict[str, Any] = {
            "method": method.upper(),
            "url": full_url,
            "query_params": query_params if query_params else None,
            "request_body": body_params if body_params else None,
            "dry_run": self.dry_run,
        }

        # 5. Dry run — return without executing
        if self.dry_run:
            result["status_code"] = 0
            result["body"] = (
                f"[DRY RUN] Would execute: {method.upper()} {full_url}\n"
                f"Query Params: {json.dumps(query_params) if query_params else 'None'}\n"
                f"Request Body: {json.dumps(body_params, indent=2) if body_params else 'None'}"
            )
            return result

        # 6. Execute the real HTTP request
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(
                    method=method.upper(),
                    url=full_url,
                    params=query_params if query_params else None,
                    json=body_params if body_params else None,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )

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
                f"Use dry_run=True to test without a live server."
            )
            return result
        except Exception as exc:
            result["status_code"] = -1
            result["body"] = f"HTTP request failed: {exc}"
            return result

    def _resolve_operation(self, operation_id: str) -> dict | None:
        """
        Find the operation details for a given operationId.

        Returns:
            ``{"method": str, "path": str, "operation": dict}`` or ``None``.
        """
        for path, methods in self.spec.get("paths", {}).items():
            for method, operation in methods.items():
                if method not in ("get", "post", "put", "delete", "patch"):
                    continue
                if operation.get("operationId") == operation_id:
                    return {
                        "method": method,
                        "path": path,
                        "operation": operation,
                    }
        return None

    def list_operations(self) -> list[dict]:
        """
        List all available operations in the spec.

        Returns:
            List of ``{"operationId": str, "method": str, "path": str, "summary": str}``.
        """
        ops = []
        for path, methods in self.spec.get("paths", {}).items():
            for method, operation in methods.items():
                if method not in ("get", "post", "put", "delete", "patch"):
                    continue
                ops.append({
                    "operationId": operation.get("operationId", ""),
                    "method": method.upper(),
                    "path": path,
                    "summary": operation.get("summary", ""),
                })
        return ops
