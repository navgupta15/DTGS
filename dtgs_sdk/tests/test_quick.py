"""
DTGS SDK — Pytest test suite for core components.

Tests LocalToolSearch, ToolExecutor, and DTGSClient error handling.
All tests run without a live DTGS server or backend.
"""
import pytest
from dtgs_sdk.local_search import LocalToolSearch
from dtgs_sdk.executor import ToolExecutor
from dtgs_sdk.client import DTGSClient, DTGSClientError


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_tools() -> list[dict]:
    """8 mock tools simulating a multi-controller service."""
    return [
        {
            "type": "function",
            "function": {
                "name": "createOrder",
                "description": "POST /orders - Create a new customer order",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customerId": {"type": "string"},
                        "items": {"type": "array"},
                    },
                    "required": ["customerId"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "getOrderById",
                "description": "GET /orders/{id} - Retrieve an order by its ID",
                "parameters": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "refundPayment",
                "description": "POST /payments/refund - Refund a payment for an order",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "orderId": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                    "required": ["orderId"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "processPayment",
                "description": "POST /payments - Process a payment for an order",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "orderId": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                    "required": ["orderId", "amount"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "getPaymentStatus",
                "description": "GET /payments/{id}/status - Get the status of a payment",
                "parameters": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "listCustomers",
                "description": "GET /customers - List all registered customers",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "createShipment",
                "description": "POST /shipments - Create a shipment for an order",
                "parameters": {
                    "type": "object",
                    "properties": {"orderId": {"type": "string"}},
                    "required": ["orderId"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "trackShipment",
                "description": "GET /shipments/{id}/track - Track shipment location and status",
                "parameters": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            },
        },
    ]


@pytest.fixture
def sample_openapi_spec() -> dict:
    """Minimal OpenAPI spec with POST (path + body) and GET (query params)."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "servers": [{"url": "http://localhost:8080"}],
        "paths": {
            "/orders/{orderId}/refund": {
                "post": {
                    "operationId": "refundPayment",
                    "summary": "Refund a payment",
                    "parameters": [
                        {
                            "name": "orderId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "amount": {"type": "number"},
                                        "reason": {"type": "string"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/orders": {
                "get": {
                    "operationId": "listOrders",
                    "summary": "List all orders",
                    "parameters": [
                        {"name": "status", "in": "query", "schema": {"type": "string"}},
                        {"name": "page", "in": "query", "schema": {"type": "integer"}},
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    }


# ── LocalToolSearch tests ─────────────────────────────────────────────────────

class TestLocalToolSearch:
    """Tests for the local keyword and semantic search engine."""

    def test_init_without_sentence_transformers(self, sample_tools):
        """Should initialize correctly even without sentence-transformers."""
        search = LocalToolSearch(sample_tools)
        assert len(search.tools) == 8
        # sentence-transformers not installed in base deps → False
        assert search.has_semantic_search is False

    def test_keyword_search_refund(self, sample_tools):
        """Query 'refund payment for order' should rank refundPayment first."""
        search = LocalToolSearch(sample_tools)
        results = search.search("refund payment for order", top_k=3)
        assert len(results) <= 3
        assert results[0]["function"]["name"] == "refundPayment"

    def test_keyword_search_shipment(self, sample_tools):
        """Query 'track my shipment' should return shipment-related tools first."""
        search = LocalToolSearch(sample_tools)
        results = search.search("track my shipment", top_k=3)
        names = [t["function"]["name"] for t in results]
        assert "trackShipment" in names
        assert names[0] == "trackShipment"

    def test_keyword_search_payment(self, sample_tools):
        """Query 'payment status' should return payment tools."""
        search = LocalToolSearch(sample_tools)
        results = search.search("payment status", top_k=3)
        names = [t["function"]["name"] for t in results]
        assert any("Payment" in n or "payment" in n.lower() for n in names)

    def test_top_k_respected(self, sample_tools):
        """Result count must not exceed top_k."""
        search = LocalToolSearch(sample_tools)
        for k in (1, 3, 5, 8):
            results = search.search("order", top_k=k)
            assert len(results) <= k

    def test_empty_query_returns_first_k(self, sample_tools):
        """Empty query should return first top_k tools without error."""
        search = LocalToolSearch(sample_tools)
        results = search.search("", top_k=4)
        assert len(results) <= 4

    def test_no_match_returns_fallback(self, sample_tools):
        """When no keywords match, should return first top_k as fallback."""
        search = LocalToolSearch(sample_tools)
        results = search.search("zzzzz_no_match_xyz", top_k=3)
        assert len(results) <= 3  # Graceful fallback, no crash


# ── ToolExecutor tests ────────────────────────────────────────────────────────

class TestToolExecutor:
    """Tests for the direct HTTP executor."""

    def test_post_with_path_and_body_params(self, sample_openapi_spec):
        """POST should resolve path param, put rest in body."""
        executor = ToolExecutor(sample_openapi_spec, dry_run=True)
        result = executor.execute(
            "refundPayment",
            {"orderId": "5042", "amount": 29.99, "reason": "defective"},
        )
        assert result["method"] == "POST"
        assert result["url"] == "http://localhost:8080/orders/5042/refund"
        assert result["request_body"]["amount"] == 29.99
        assert result["request_body"]["reason"] == "defective"
        assert "5042" not in str(result.get("request_body", {}))  # Path param not in body
        assert result["dry_run"] is True

    def test_get_with_query_params(self, sample_openapi_spec):
        """GET should put non-path params into query_params."""
        executor = ToolExecutor(sample_openapi_spec, dry_run=True)
        result = executor.execute("listOrders", {"status": "pending", "page": 2})
        assert result["method"] == "GET"
        assert result["url"] == "http://localhost:8080/orders"
        assert result["query_params"]["status"] == "pending"
        assert result["query_params"]["page"] == 2
        assert result["request_body"] is None

    def test_unknown_operation_returns_error(self, sample_openapi_spec):
        """Unknown operationId should return status_code -1."""
        executor = ToolExecutor(sample_openapi_spec, dry_run=True)
        result = executor.execute("nonExistentTool", {})
        assert result["status_code"] == -1
        assert "not found" in result["body"].lower()

    def test_list_operations(self, sample_openapi_spec):
        """list_operations() should return all paths with their operationIds."""
        executor = ToolExecutor(sample_openapi_spec)
        ops = executor.list_operations()
        assert len(ops) == 2
        op_ids = {op["operationId"] for op in ops}
        assert "refundPayment" in op_ids
        assert "listOrders" in op_ids

    def test_base_url_extracted_from_spec(self, sample_openapi_spec):
        """Executor should read base_url from spec servers."""
        executor = ToolExecutor(sample_openapi_spec)
        assert executor.base_url == "http://localhost:8080"

    def test_missing_path_param_leaves_placeholder(self, sample_openapi_spec):
        """If path param is missing from args, placeholder stays in URL."""
        executor = ToolExecutor(sample_openapi_spec, dry_run=True)
        result = executor.execute("refundPayment", {"amount": 10.0})  # no orderId
        assert "{orderId}" in result["url"]

    def test_dry_run_false_on_base_executor(self, sample_openapi_spec):
        """Executor created without dry_run defaults to False."""
        executor = ToolExecutor(sample_openapi_spec)
        assert executor.dry_run is False


# ── DTGSClient error handling tests ──────────────────────────────────────────

class TestDTGSClientErrors:
    """Tests for DTGSClient connection and HTTP error handling."""

    def test_connection_error_raises_dtgs_client_error(self):
        """Connection to unreachable server should raise DTGSClientError."""
        client = DTGSClient("http://localhost:19999")  # Nothing running here
        with pytest.raises(DTGSClientError) as exc_info:
            client.list_namespaces()
        assert "connect" in str(exc_info.value).lower() or "server" in str(exc_info.value).lower()

    def test_dtgs_client_error_is_exception(self):
        """DTGSClientError should be an Exception subclass."""
        assert issubclass(DTGSClientError, Exception)

    def test_client_strips_trailing_slash(self):
        """Server URL trailing slash should be stripped."""
        client = DTGSClient("http://localhost:8000/")
        assert client.server_url == "http://localhost:8000"

    def test_client_stores_timeout(self):
        """Custom timeout should be stored on the client."""
        client = DTGSClient("http://localhost:8000", timeout=60.0)
        assert client.timeout == 60.0
