"""
DTGS SDK — Low-level HTTP client for the DTGS catalog server.

Provides typed methods for all DTGS REST API endpoints. Does not handle
tool filtering or execution — use DTGSToolkit for that.
"""
from __future__ import annotations

from typing import Any

import httpx


class DTGSClient:
    """
    Low-level HTTP client for the DTGS catalog server.

    All methods make synchronous HTTP requests and return parsed JSON.
    Raises ``DTGSClientError`` on connection or HTTP errors.

    Args:
        server_url: Base URL of the DTGS server (e.g. ``http://localhost:8000``).
        timeout: HTTP request timeout in seconds.
    """

    def __init__(self, server_url: str, timeout: float = 10.0) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GET request and return parsed JSON."""
        url = f"{self.server_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.ConnectError:
            raise DTGSClientError(
                f"Could not connect to DTGS server at {self.server_url}. "
                f"Is the server running?"
            )
        except httpx.HTTPStatusError as exc:
            raise DTGSClientError(
                f"DTGS server returned {exc.response.status_code}: "
                f"{exc.response.text}"
            )

    # ── Namespace endpoints ────────────────────────────────────────────────

    def list_namespaces(self) -> list[dict]:
        """
        List all ingested namespaces with tool counts.

        Returns:
            List of dicts: ``[{"namespace": "...", "count": N, ...}]``
        """
        return self._get("/api/v1/namespaces")

    # ── Spec endpoints ─────────────────────────────────────────────────────

    def get_openapi_spec(self, namespace: str) -> dict:
        """
        Fetch the full OpenAPI 3.1 specification for a namespace.

        Args:
            namespace: The tenant namespace.

        Returns:
            Complete OpenAPI 3.1.0 JSON dict.
        """
        return self._get(f"/api/v1/{namespace}/openapi.json")

    def get_tools(self, namespace: str) -> list[dict]:
        """
        Fetch all tools for a namespace in OpenAI function-calling format.

        Args:
            namespace: The tenant namespace.

        Returns:
            List of OpenAI tool schema dicts.
        """
        return self._get(f"/api/v1/{namespace}/tools")

    # ── Search endpoint ────────────────────────────────────────────────────

    def search_tools(
        self,
        namespace: str,
        query: str,
        top_k: int = 15,
        rest_only: bool = True,
    ) -> list[dict]:
        """
        Search for tools matching a natural language query.

        The DTGS server performs semantic + keyword search and returns the
        most relevant tools.

        Args:
            namespace: The tenant namespace.
            query: Natural language query string.
            top_k: Maximum number of tools to return.
            rest_only: Only return REST endpoints (exclude getters/setters).

        Returns:
            List of OpenAI tool schema dicts (filtered).
        """
        return self._get(
            f"/api/v1/{namespace}/tools/search",
            params={"q": query, "top_k": top_k, "rest_only": rest_only},
        )

    # ── Controller endpoints ───────────────────────────────────────────────

    def get_controllers(self, namespace: str) -> list[dict]:
        """
        List controllers (grouped by class_name) for a namespace.

        Returns:
            List of dicts:
            ``[{"class_name": "...", "api_count": N, "tool_names": "..."}]``
        """
        return self._get(f"/api/v1/{namespace}/controllers")

    def get_controller_tools(self, namespace: str, class_name: str) -> list[dict]:
        """
        Fetch tools for a specific controller in OpenAI format.

        Args:
            namespace: The tenant namespace.
            class_name: The controller class name.

        Returns:
            List of OpenAI tool schema dicts for that controller.
        """
        return self._get(f"/api/v1/{namespace}/controllers/{class_name}/tools")


class DTGSClientError(Exception):
    """Raised when the DTGS client encounters a connection or API error."""
    pass
