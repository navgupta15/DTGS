"""
DTGS SDK — High-Level Toolkit.

The main class for integrating DTGS with any LLM agent. Handles tool
discovery, filtering, caching, and direct API execution transparently.

Usage::

    from dtgs_sdk import DTGSToolkit

    toolkit = DTGSToolkit("http://dtgs-server:8000", namespace="order-service")

    # Get filtered tools for a query (auto-filters if namespace has many tools)
    tools = toolkit.get_tools(query="refund payment")

    # Execute a tool call directly against the backend (DTGS not involved)
    result = toolkit.execute("refundPayment", {"orderId": "5042"})
"""
from __future__ import annotations

import time
from typing import Any

from dtgs_sdk.client import DTGSClient, DTGSClientError
from dtgs_sdk.executor import ToolExecutor
from dtgs_sdk.local_search import LocalToolSearch


class DTGSToolkit:
    """
    High-level DTGS integration toolkit.

    Handles tool discovery, filtering, caching, and execution. DTGS is used
    for discovery only — API execution goes directly to the backend.

    Args:
        server_url: Base URL of the DTGS catalog server.
        namespace: The tenant namespace to load tools from.
        max_tools: Maximum tools to return per query (tool budget for the LLM).
        auto_filter: Automatically filter tools when count exceeds ``max_tools``.
        local_search: Use local semantic search instead of per-query DTGS calls.
        cache_ttl: Seconds before the cached spec is considered stale.
        dry_run: If ``True``, tool execution returns request details without
                 making actual HTTP calls to the backend.
        search_model: Sentence-transformer model name for local search.

    Example::

        toolkit = DTGSToolkit("http://dtgs:8000", namespace="order-service")

        # Small service (≤20 tools): returns all tools
        tools = toolkit.get_tools()

        # Large service (300 tools): returns top-K filtered tools
        tools = toolkit.get_tools(query="refund payment")

        # Execute directly against the backend
        result = toolkit.execute("refundPayment", {"orderId": "5042"})
    """

    def __init__(
        self,
        server_url: str,
        namespace: str,
        max_tools: int = 20,
        auto_filter: bool = True,
        local_search: bool = True,
        cache_ttl: int = 300,
        dry_run: bool = False,
        search_model: str = "all-MiniLM-L6-v2",
    ) -> None:
        self._client = DTGSClient(server_url)
        self._namespace = namespace
        self._max_tools = max_tools
        self._auto_filter = auto_filter
        self._use_local_search = local_search
        self._cache_ttl = cache_ttl
        self._dry_run = dry_run
        self._search_model = search_model

        # Cache state
        self._spec: dict | None = None
        self._all_tools: list[dict] = []
        self._total_count: int = 0
        self._executor: ToolExecutor | None = None
        self._local_search: LocalToolSearch | None = None
        self._last_fetch: float = 0

        # Initial fetch
        self._refresh_cache()

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def namespace(self) -> str:
        """The tenant namespace."""
        return self._namespace

    @property
    def tool_count(self) -> int:
        """Total number of tools in the namespace."""
        self._check_cache()
        return self._total_count

    @property
    def needs_filtering(self) -> bool:
        """Whether the namespace has too many tools to load at once."""
        return self.tool_count > self._max_tools

    @property
    def server_url(self) -> str:
        """The DTGS server URL."""
        return self._client.server_url

    # ── Tool Discovery ─────────────────────────────────────────────────────

    def get_tools(self, query: str | None = None) -> list[dict]:
        """
        Get tools in OpenAI function-calling format.

        For small namespaces (≤max_tools), returns all tools regardless of query.
        For large namespaces, filters using local search or DTGS server search.

        Args:
            query: User's natural language query. Used for filtering when the
                   namespace has more tools than ``max_tools``. If ``None`` and
                   namespace is large, returns all tools (client's decision).

        Returns:
            List of tool dicts in OpenAI function-calling format::

                [{"type": "function", "function": {"name": ..., "parameters": ...}}]
        """
        self._check_cache()

        # Small namespace — return all tools, no filtering needed
        if not self.needs_filtering:
            return self._all_tools

        # Large namespace without query — return all (client's risk)
        if not query:
            return self._all_tools

        # Large namespace with query — filter
        if self._auto_filter:
            return self._filter_tools(query)

        return self._all_tools

    def get_all_tools(self) -> list[dict]:
        """
        Get ALL tools regardless of count (bypasses filtering).

        Use this for programmatic access, documentation, or when you
        explicitly want the full list.

        Returns:
            Complete list of tool dicts in OpenAI format.
        """
        self._check_cache()
        return self._all_tools

    def get_controllers(self) -> list[dict]:
        """
        Get controller-level summaries for the namespace.

        Returns:
            List of controller dicts::

                [{"class_name": "PaymentCtrl", "api_count": 18, "tool_names": "..."}]
        """
        return self._client.get_controllers(self._namespace)

    def get_controller_tools(self, class_name: str) -> list[dict]:
        """
        Get tools for a specific controller.

        Args:
            class_name: The controller class name.

        Returns:
            List of tool dicts for that controller.
        """
        return self._client.get_controller_tools(self._namespace, class_name)

    # ── Tool Execution ─────────────────────────────────────────────────────

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict:
        """
        Execute a tool call DIRECTLY against the target backend.

        DTGS server is NOT involved — this resolves the operationId from the
        cached OpenAPI spec and makes a direct HTTP call to the backend.

        Args:
            tool_name: The operationId / tool name from the LLM's tool call.
            arguments: The arguments dict from the LLM's tool call.

        Returns:
            Dict with keys: ``status_code``, ``body``, ``method``, ``url``,
            ``request_body``, ``query_params``, ``dry_run``.

        Example::

            result = toolkit.execute("refundPayment", {"orderId": "5042"})
            print(result["status_code"])  # 200
            print(result["body"])         # {"status": "refunded"}
        """
        self._check_cache()
        if self._executor is None:
            raise DTGSClientError("Toolkit not initialized — no OpenAPI spec cached.")
        return self._executor.execute(tool_name, arguments)

    # ── Spec Access ────────────────────────────────────────────────────────

    def get_openapi_spec(self) -> dict:
        """Returns the full cached OpenAPI spec."""
        self._check_cache()
        return self._spec or {}

    # ── Cache Management ───────────────────────────────────────────────────

    def refresh(self) -> None:
        """Force-refresh the cached spec and tools from DTGS."""
        self._refresh_cache()

    def _check_cache(self) -> None:
        """Refresh cache if TTL has expired."""
        if self._cache_ttl > 0 and self._last_fetch > 0:
            elapsed = time.time() - self._last_fetch
            if elapsed > self._cache_ttl:
                self._refresh_cache()

    def _refresh_cache(self) -> None:
        """Fetch spec and tools from DTGS server."""
        self._spec = self._client.get_openapi_spec(self._namespace)
        self._all_tools = self._client.get_tools(self._namespace)
        self._total_count = len(self._all_tools)
        self._executor = ToolExecutor(self._spec, dry_run=self._dry_run)
        self._last_fetch = time.time()

        # Initialize local search if needed
        if self._use_local_search and self._total_count > self._max_tools:
            self._local_search = LocalToolSearch(
                self._all_tools, model_name=self._search_model
            )
        else:
            self._local_search = None

    # ── Internal Filtering ─────────────────────────────────────────────────

    def _filter_tools(self, query: str) -> list[dict]:
        """Filter tools using local search or DTGS server search."""
        # Prefer local search (no DTGS call at runtime)
        if self._local_search:
            return self._local_search.search(query, top_k=self._max_tools)

        # Fall back to DTGS server-side search
        try:
            return self._client.search_tools(
                self._namespace, query=query, top_k=self._max_tools
            )
        except DTGSClientError:
            # If server search fails, return all tools as last resort
            return self._all_tools

    # ── String representation ──────────────────────────────────────────────

    def __repr__(self) -> str:
        status = "filtered" if self.needs_filtering else "full"
        search = "local" if self._local_search else "server"
        return (
            f"DTGSToolkit(server='{self._client.server_url}', "
            f"namespace='{self._namespace}', "
            f"tools={self._total_count}, mode={status}, search={search})"
        )
