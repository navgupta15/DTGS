# DTGS SDK

**Client SDK for the [Dynamic Tool Generation System (DTGS)](https://github.com/your-org/toolmaker)**

> Discover, filter, and execute API tools from any LLM agent — with just 3 lines of code.

DTGS SDK connects your LLM agent to a DTGS catalog server, transparently solving the **"too many tools"** problem. It fetches tool specs once, caches them locally, auto-filters to the most relevant tools per query, and executes API calls **directly against your backend** — DTGS is never a proxy.

---

## Table of Contents

- [Why DTGS SDK?](#why-dtgs-sdk)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Usage Patterns](#usage-patterns)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Local Search](#local-search)
- [Framework Integrations](#framework-integrations)
- [Development](#development)

---

## Why DTGS SDK?

When DTGS ingests a large enterprise service, it can produce **300+ API tool definitions**. No LLM can handle that many tools at once — accuracy degrades beyond ~20 tools, regardless of context window size.

| Scenario | Without SDK | With SDK |
|----------|-------------|----------|
| Small service (20 tools) | Works fine | Works fine (no filtering) |
| Large service (300 tools) | ❌ LLM chokes | ✅ Auto-filters to 15-20 per query |
| Per-query DTGS calls | N/A | **Zero** (local search) |
| API execution | Client builds HTTP calls | `toolkit.execute()` handles everything |
| Framework support | Manual conversion | LangChain + OpenAI built-in |

---

## Installation

### Using uv (recommended)

```bash
# Base SDK (only httpx dependency)
uv add "dtgs-sdk"

# With local semantic search (sentence-transformers)
uv add "dtgs-sdk[search]"

# With LangChain integration
uv add "dtgs-sdk[langchain]"

# Everything
uv add "dtgs-sdk[all]"
```

### Using pip

```bash
pip install dtgs-sdk               # Base
pip install "dtgs-sdk[search]"     # + semantic search
pip install "dtgs-sdk[langchain]"  # + LangChain adapter
pip install "dtgs-sdk[all]"        # Everything
```

### From source (development)

```bash
git clone <repo-url>
cd dtgs_sdk
uv sync                   # Install base + dev dependencies
uv sync --extra search    # + sentence-transformers
uv sync --extra langchain # + langchain-core
uv sync --all-extras      # Install all optional dependencies
```

> **Note:** Requires Python 3.10+. The repo ships a `.python-version` file that pins to 3.12 for development consistency.

---

## Quick Start

### Prerequisites

A running DTGS catalog server with at least one ingested namespace:

```bash
# In the toolmaker project
cd toolmaker
uv run python cli.py ingest https://github.com/spring-projects/spring-petclinic \
    --namespace petclinic \
    --base-url http://localhost:8080
uv run python cli.py serve
```

### Basic Usage

```python
from dtgs_sdk import DTGSToolkit

# 1. Connect to DTGS server
toolkit = DTGSToolkit("http://localhost:8000", namespace="petclinic")

print(f"Connected: {toolkit}")
# DTGSToolkit(server='http://localhost:8000', namespace='petclinic', tools=20, mode=full, search=server)

# 2. Get tools (auto-filters if namespace has >20 tools)
tools = toolkit.get_tools(query="find all owners")
print(f"Got {len(tools)} tools")

# 3. Execute a tool call directly against the backend
result = toolkit.execute("listOwners", {"page": 1})
print(f"Status: {result['status_code']}")
print(f"Body: {result['body']}")
```

### Dry Run Mode

Test tool resolution without making real HTTP calls:

```python
toolkit = DTGSToolkit(
    "http://localhost:8000",
    namespace="petclinic",
    dry_run=True,  # No actual HTTP calls to backend
)

result = toolkit.execute("listOwners", {"page": 1})
print(result["body"])
# [DRY RUN] Would execute: GET http://localhost:8080/owners
# Query Params: {"page": 1}
# Request Body: None
```

---

## Architecture

```
┌───────────────────────────────────────────────────────────┐
│  Your LLM Agent                                           │
│                                                           │
│  toolkit = DTGSToolkit("http://dtgs:8000", ns="svc")     │
│  tools = toolkit.get_tools(query="...")                    │
│  result = toolkit.execute("tool_name", {args})            │
└──────────┬──────────────────────────┬─────────────────────┘
           │                          │
    Discovery (once, cached)    Execution (per call)
           │                          │
           ▼                          ▼
    ┌──────────────┐          ┌──────────────┐
    │ DTGS Server  │          │   Backend    │
    │ (catalog)    │          │   Service    │
    │              │          │              │
    │ Serves specs │          │ Your APIs    │
    │ Lightweight  │          │ Direct HTTP  │
    └──────────────┘          └──────────────┘
```

**Key design decisions:**

1. **DTGS is NOT a proxy** — The SDK fetches specs from DTGS once, then calls your backend directly. DTGS has zero runtime overhead after initial spec fetch.

2. **Local search first** — Per-query filtering happens locally (via keyword or semantic search). No DTGS calls at runtime.

3. **Automatic threshold** — If a namespace has ≤20 tools, `get_tools()` returns all of them without filtering. Filtering only activates for large namespaces.

---

## Usage Patterns

### Pattern 1: Generic (Any Framework)

```python
from dtgs_sdk import DTGSToolkit

toolkit = DTGSToolkit("http://dtgs:8000", namespace="order-service")

# Get filtered tools for this query
tools = toolkit.get_tools(query="refund payment for order")
# Returns: [{"type": "function", "function": {"name": "refundPayment", ...}}, ...]

# Bind to your LLM (any framework)
llm_with_tools = your_llm.bind_tools(tools)
response = llm_with_tools.invoke(messages)

# Execute the tool call
if response.tool_calls:
    tc = response.tool_calls[0]
    result = toolkit.execute(tc["name"], tc["args"])
    print(result["status_code"], result["body"])
```

### Pattern 2: LangChain Agent

```python
from dtgs_sdk import DTGSToolkit
from dtgs_sdk.integrations.langchain import create_dtgs_tools

toolkit = DTGSToolkit("http://dtgs:8000", namespace="order-service")

# Create LangChain tools — each auto-executes via direct HTTP
tools = create_dtgs_tools(toolkit, query="refund payment")

# Use with any LangChain agent
from langchain.agents import create_react_agent
agent = create_react_agent(llm, tools)
result = agent.invoke({"input": "refund payment for order 5042"})
```

### Pattern 3: OpenAI SDK

```python
from dtgs_sdk import DTGSToolkit
from dtgs_sdk.integrations.openai_adapter import get_tools, handle_tool_calls
import openai

toolkit = DTGSToolkit("http://dtgs:8000", namespace="order-service")

messages = [{"role": "user", "content": "refund payment for order 5042"}]

# Get filtered tools
tools = get_tools(toolkit, query=messages[-1]["content"])

# Call OpenAI with tools
response = openai.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    tools=tools,
)

# Execute tool calls and get results
if response.choices[0].message.tool_calls:
    tool_messages = handle_tool_calls(toolkit, response)
    messages.append(response.choices[0].message)
    messages.extend(tool_messages)

    # Get final answer with tool results
    final = openai.chat.completions.create(
        model="gpt-4o",
        messages=messages,
    )
    print(final.choices[0].message.content)
```

### Pattern 4: Browse by Controller

```python
from dtgs_sdk import DTGSToolkit

toolkit = DTGSToolkit("http://dtgs:8000", namespace="order-service")

# List all controllers
controllers = toolkit.get_controllers()
for c in controllers:
    print(f"  {c['class_name']}: {c['api_count']} APIs")
# OrderController: 25 APIs
# PaymentController: 18 APIs
# ShippingController: 15 APIs

# Load tools for just one controller
payment_tools = toolkit.get_controller_tools("PaymentController")
llm.bind_tools(payment_tools)  # Only 18 tools
```

---

## Configuration

```python
toolkit = DTGSToolkit(
    server_url="http://dtgs:8000",   # DTGS catalog server URL
    namespace="order-service",        # Tenant namespace

    # Filtering
    max_tools=20,                     # Max tools per query (default: 20)
    auto_filter=True,                 # Auto-filter when tools exceed max_tools

    # Search
    local_search=True,                # Use local search instead of per-query DTGS calls
    search_model="all-MiniLM-L6-v2",  # Sentence-transformer model for local search

    # Caching
    cache_ttl=300,                    # Refresh cached spec every N seconds (0 = no auto-refresh)

    # Execution
    dry_run=False,                    # True = simulate API calls without executing
)
```

### Environment Variables

The SDK itself doesn't use environment variables, but your LLM provider might need them:

```bash
# For OpenAI
export OPENAI_API_KEY=sk-...

# For Ollama (local models)
export DTGS_PROVIDER=ollama
export DTGS_MODEL=qwen3:8b

# For Gemini
export GOOGLE_API_KEY=...
```

---

## API Reference

### DTGSToolkit

The main class for DTGS integration.

| Method | Returns | Description |
|--------|---------|-------------|
| `get_tools(query=None)` | `list[dict]` | Get filtered tools in OpenAI format. Auto-filters for large namespaces. |
| `get_all_tools()` | `list[dict]` | Get ALL tools (bypasses filtering). |
| `execute(tool_name, args)` | `dict` | Execute a tool call directly against the backend. |
| `get_controllers()` | `list[dict]` | List controllers with API counts. |
| `get_controller_tools(class_name)` | `list[dict]` | Get tools for one controller. |
| `get_openapi_spec()` | `dict` | Get the full cached OpenAPI spec. |
| `refresh()` | `None` | Force-refresh cached data from DTGS. |

| Property | Type | Description |
|----------|------|-------------|
| `tool_count` | `int` | Total tools in the namespace. |
| `needs_filtering` | `bool` | Whether the namespace exceeds `max_tools`. |
| `namespace` | `str` | The tenant namespace. |
| `server_url` | `str` | The DTGS server URL. |

### DTGSClient

Low-level HTTP client for DTGS server endpoints.

| Method | Returns | Description |
|--------|---------|-------------|
| `list_namespaces()` | `list[dict]` | List all namespaces. |
| `get_openapi_spec(ns)` | `dict` | Fetch full OpenAPI spec. |
| `get_tools(ns)` | `list[dict]` | Fetch all tools. |
| `search_tools(ns, query, top_k)` | `list[dict]` | Search for relevant tools. |
| `get_controllers(ns)` | `list[dict]` | List controllers. |
| `get_controller_tools(ns, name)` | `list[dict]` | Get a controller's tools. |

### ToolExecutor

Executes HTTP requests directly against the backend.

| Method | Returns | Description |
|--------|---------|-------------|
| `execute(operation_id, args)` | `dict` | Execute an API call. Returns `status_code`, `body`, `method`, `url`. |
| `list_operations()` | `list[dict]` | List all available operations in the spec. |

### Execution Result Format

```python
result = toolkit.execute("refundPayment", {"orderId": "5042"})

# result = {
#     "status_code": 200,          # HTTP status (0 for dry-run, -1 for error)
#     "body": {"status": "ok"},    # Response body (parsed JSON or text)
#     "method": "POST",            # HTTP method
#     "url": "http://backend/...", # Full URL with path params resolved
#     "request_body": {...},       # JSON body sent (POST/PUT/PATCH)
#     "query_params": {...},       # Query parameters (GET/DELETE)
#     "dry_run": False,            # Whether this was a dry run
# }
```

---

## Local Search

The SDK filters tools per query **without calling DTGS at runtime**. Two search backends are available:

### Keyword Search (default, zero dependencies)

Always available. Tokenizes the query and scores tools by word overlap with tool names, descriptions, and parameter names.

```python
# Keyword search is automatic when sentence-transformers is not installed
toolkit = DTGSToolkit("http://dtgs:8000", namespace="svc")
tools = toolkit.get_tools(query="refund payment")  # Uses keyword matching
```

### Semantic Search (optional, higher accuracy)

Uses `sentence-transformers` to embed tool descriptions locally and perform cosine similarity search. Significantly better at matching intent (e.g., "give money back" → `refundPayment`).

```bash
# Install the optional dependency
uv add sentence-transformers
# or
uv sync --extra search
```

```python
# Semantic search activates automatically when sentence-transformers is installed
toolkit = DTGSToolkit("http://dtgs:8000", namespace="svc")
tools = toolkit.get_tools(query="give money back to customer")
# Correctly finds refundPayment even without exact keyword match
```

The search backend is detected automatically. No code changes needed.

---

## Framework Integrations

### LangChain

```bash
# From source
uv sync --extra langchain

# From PyPI
uv add "dtgs-sdk[langchain]"
```

```python
from dtgs_sdk import DTGSToolkit
from dtgs_sdk.integrations.langchain import create_dtgs_tools

toolkit = DTGSToolkit("http://dtgs:8000", namespace="order-service")

# Creates LangChain StructuredTool instances
# Each tool auto-executes via the toolkit's HTTP executor
tools = create_dtgs_tools(toolkit, query="manage orders")

# Compatible with any LangChain agent type
agent = create_react_agent(llm, tools)
```

### OpenAI SDK

No extra dependencies needed — the tools format is already OpenAI-compatible.

```python
from dtgs_sdk.integrations.openai_adapter import get_tools, handle_tool_calls

toolkit = DTGSToolkit("http://dtgs:8000", namespace="order-service")
tools = get_tools(toolkit, query="manage payments")

# handle_tool_calls() processes the response, executes tools, and returns
# formatted messages ready to append to the conversation
```

---

## Development

### Setup

```bash
git clone <repo-url>
cd dtgs_sdk
uv sync              # Install base + dev dependencies (pytest, pytest-httpx)
uv sync --all-extras # Install everything including sentence-transformers + langchain-core
```

### Running Tests

```bash
uv run pytest            # Run all 18 tests
uv run pytest -v         # Verbose output with test names
uv run pytest -k search  # Run only LocalToolSearch tests
uv run pytest -k executor # Run only ToolExecutor tests
```

Expected output:
```
18 passed in ~4s
```

### Project Structure

```
dtgs_sdk/
├── pyproject.toml                      # Package config (uv + pip compatible)
├── uv.lock                             # Reproducible lockfile (committed)
├── .python-version                     # Pins Python 3.12 for development
├── README.md
├── dtgs_sdk/
│   ├── __init__.py                     # Public exports: DTGSToolkit, DTGSClient
│   ├── client.py                       # Low-level HTTP client for DTGS server
│   ├── executor.py                     # Direct HTTP execution to backend
│   ├── local_search.py                 # Local keyword + semantic search
│   ├── toolkit.py                      # Main DTGSToolkit class
│   └── integrations/
│       ├── __init__.py
│       ├── langchain.py                # LangChain StructuredTool adapter
│       └── openai_adapter.py           # OpenAI SDK helpers
└── tests/
    └── test_quick.py                   # 18 pytest tests (3 test classes)
```

### Dependencies

| Dependency | Required | Version | Purpose |
|------------|----------|---------|--------|
| `httpx` | ✅ Base | `>=0.27.0` | HTTP client for DTGS server + backend API calls |
| `pytest` | 🔧 Dev | `>=9.0.0` | Test runner |
| `pytest-httpx` | 🔧 Dev | `>=0.30.0` | HTTP mocking for tests |
| `sentence-transformers` | ❌ Optional (`search`) | `>=3.0.0` | Local semantic search via `all-MiniLM-L6-v2` model |
| `langchain-core` | ❌ Optional (`langchain`) | `>=0.2.0` | LangChain `StructuredTool` adapter |

---

## License

MIT
