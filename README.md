# Dynamic Tool Generation System (DTGS)

**Automatically discovers LLM-callable tools from Java GitHub repositories** using tree-sitter AST parsing and LangGraph pipelines — no JVM required.

---

## How It Works

DTGS operates as a **Multi-Tenant Tool Catalog**. It completely avoids taking on execution bottlenecks.
Instead, it provides the phonebook (OpenAPI specification) so that external LLM chatbots can make API calls directly — **no MCP server needed**.

```
Graph 1 — Ingestion Pipeline:
  GitHub URL / Local Path → clone/scan → discover .java files
             → [parallel AST parse per file]
             → extract REST paths, HTTP methods, and parameters
             → deep DTO property resolution across packages
             → store in SQLite registry under a specific `namespace`

Web Dashboard — http://localhost:8000:
  Visual UI for ingesting repos, managing namespaces, and browsing OpenAPI specs

FastAPI Server — OpenAPI Catalog:
  GET /api/v1/{namespace}/openapi.json
             → Dynamically builds strict OpenAPI 3.1.0 specifications
             → ANY chatbot (ChatGPT, Claude, LangChain) reads this URL
             → Chatbot makes direct HTTP execution calls to your Java backend

Chat Agent — Interactive LLM Tool Calling:
  CLI chat REPL → fetches tools from DTGS server
             → LLM selects & calls APIs via function calling
             → supports dry-run mode for testing without live backend
```

### 🧠 Smart Delta Caching (Ingestion Optimization)
DTGS calculates a deterministic cryptographic hash for every method it analyzes. If you re-run an ingestion on the same repository, DTGS perfectly bypasses expensive LLM API calls and Embedding API calls for methods that haven't structurally changed since the last run.

### 🧹 Path Filtering & Automatic Test Exclusion 
By default, DTGS ignores common non-source directories as well as `test` and `tests` directories to ensure your agent's tools aren't cluttered with mock functions.
Additionally, you can supply an `--include-file` to aggressively limit the scan to exact package paths. The text file should simply contain **one package or folder substring per line**.

### 🧩 Deep DTO Property Resolution
When DTGS discovers an object as a request parameter (e.g., `@RequestBody PetDto`), it does **not** stop at simply defining it as an opaque `object`. It maintains a global Class Registry across all analyzed files — including DTO classes in packages outside the filtered scope. When serializing the OpenAPI schema, DTGS recursively unpacks these Java objects (including handling generic type parameters like `List<Pet>`) so that the AI Agent sees every single field property (`name`, `age`, `tags`) directly in the tool schema.

### 🔎 Rich Trace Logging & LLM Progress Tracking
DTGS features a centralized, beautiful logging system powered by `rich`.
When ingesting repositories, it displays exactly which tools the LLM is currently enhancing in real-time (e.g., `[INFO] [1/12] Calling LLM for tool: PetController_findPet`). 
If you want to observe deeper operations—like exact AST extraction steps, LLM responses, or SQL database upserts—you can simply append the `--verbose` (or `-v`) flag to any CLI command.

---

## Installation

```bash
# 1. Clone this repo
git clone <this-repo>
cd toolmaker

# 2. Install dependencies (uses uv)
uv sync
```

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Git (for repo ingestion)

---

## Quick Start

### Step 1 — Create a Package Filter File (Optional but Recommended)

Create a `packages.txt` file (one path substring per line) to only scan relevant packages.

```text
com.example.demo.controller
```

### Step 2 — Ingest a repository into a namespace

```bash
# From GitHub
uv run python cli.py ingest https://github.com/spring-projects/spring-petclinic \
   --namespace petclinic \
   --base-url "http://localhost:8080" \
   --include-file packages.txt

# From a local folder
uv run python cli.py ingest-local ./my-spring-app \
   --namespace my_service \
   --base-url "https://api.myapp.com" \
   --include-file packages.txt
```

### Step 3 — Start the DTGS Server (Catalog + Web Dashboard)

```bash
uv run python cli.py serve --port 8000
```

This starts the FastAPI server which exposes:
- **Web Dashboard** at `http://localhost:8000` — visual UI for managing everything
- **OpenAPI Catalog** at `http://localhost:8000/api/v1/{namespace}/openapi.json` — machine-readable spec

### Step 4 — Use the Web Dashboard

Open `http://localhost:8000` in your browser. The dashboard provides:

- **Sidebar** — Lists all ingested namespaces with tool counts. Click to view the OpenAPI spec.
- **Ingest Form** — Submit new ingestion jobs (GitHub URL or Local Path) with package filtering directly from the browser.
- **OpenAPI Viewer** — Interactive Swagger UI rendering + raw JSON view with fullscreen toggle.
- **Namespace Management** — Delete namespaces with one click.

### Step 5 — Hook up your Chatbot

Point ChatGPT Custom Actions, LangChain, or Claude to:
**`http://localhost:8000/api/v1/petclinic/openapi.json`**

The chatbot will instantly learn your Java backend and can make direct HTTP calls to it.

### Step 6 — Or use the built-in Chat Agent

```bash
# Dry-run mode (default — simulates API calls, no backend needed)
uv run python cli.py chat --namespace petclinic

# Live mode (makes real HTTP calls to the target backend)
uv run python cli.py chat --namespace petclinic --live

# With a specific LLM provider
uv run python cli.py chat -n petclinic --provider gemini --model gemini-2.5-flash
uv run python cli.py chat -n petclinic --provider ollama --model llama3.2
```

The chat agent fetches the OpenAPI spec from the running DTGS server, converts operations into LLM tools, and lets you interact naturally:

```
You: Add a pet named Buddy with age 3
🔧 Calling: PetCtrl_addPet
   Args: {"vo": {"name": "Buddy", "age": 3, "tags": []}}
   POST https://api.myapp.com/api/pets/add
   ↳ DRY RUN result: Would execute POST...

Agent: I've submitted a request to add pet "Buddy" (age 3) to the system.
```

---

## 🖥️ Web Dashboard

The DTGS Web Dashboard is a lightweight single-page app served directly by the FastAPI server. No build step, no framework dependencies.

**Features:**
- Dark glassmorphism theme with Inter & JetBrains Mono fonts
- Namespace sidebar with live tool counts and delete controls
- Ingestion form supporting both GitHub URLs and local folder paths
- Interactive Swagger UI + raw JSON viewer with fullscreen mode
- Toast notifications for operation feedback

**API Endpoints powering the dashboard:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve the dashboard UI |
| `/api/v1/namespaces` | GET | List all namespaces with counts |
| `/api/v1/{namespace}/openapi.json` | GET | Get OpenAPI spec for a namespace |
| `/api/v1/ingest` | POST | Trigger ingestion (GitHub or local) |
| `/api/v1/{namespace}` | DELETE | Delete a namespace |

---

## 🛠️ Dynamic Triggers (On-The-Fly Ingestion)

You can command DTGS to ingest new repositories dynamically via HTTP (useful for CI/CD or other orchestrating agents):

```bash
# GitHub ingestion
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"source_type": "github", "github_url": "https://github.com/org/new-service", "namespace": "new_service", "base_url": "https://api.new.com"}'

# Local path ingestion with package filtering
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"source_type": "local", "local_path": "/path/to/project", "namespace": "my_svc", "base_url": "https://api.example.com", "include_packages": ["com.example.controller"]}'
```

---

## Model Backends

DTGS supports cloud and local LLMs for description enhancement and the chat agent. Configure via environment variables or CLI flags:

### Option A — Ollama (local, no API key needed)

1. [Install Ollama](https://ollama.com/download)
2. Pull a model:
   ```bash
   ollama pull llama3.2      # recommended: good tool-calling support
   # or
   ollama pull mistral
   ollama pull qwen2.5
   ```
3. Run the agent:
   ```bash
   $env:DTGS_PROVIDER = "ollama"
   $env:DTGS_MODEL    = "llama3.2"        # default if omitted
   $env:DTGS_BASE_URL = "http://localhost:11434"  # default if omitted

   uv run python cli.py chat -n petclinic --provider ollama
   ```

### Option B — OpenAI

```bash
$env:OPENAI_API_KEY = "sk-..."
$env:DTGS_PROVIDER  = "openai"   # default, can omit
$env:DTGS_MODEL     = "gpt-4o-mini"

uv run python cli.py chat -n petclinic
```

### Option C — Google Gemini

```bash
$env:GOOGLE_API_KEY = "AIzaSy..."
$env:DTGS_PROVIDER  = "gemini"
$env:DTGS_MODEL     = "gemini-2.5-flash"

uv run python cli.py chat -n petclinic --provider gemini
```

### Environment Variable Reference

DTGS automatically loads `.env` files from your working directory.

| Variable             | Description                                          | Default                 |
|----------------------|------------------------------------------------------|-------------------------|
| `DTGS_PROVIDER`      | `openai`, `ollama`, or `gemini`                      | `openai`                |
| `DTGS_MODEL`         | Model name (`gpt-4o-mini`, `gemini-2.5-flash`, etc.) | varies by provider      |
| `DTGS_BASE_URL`      | Target URL if running `ollama`                       | `http://localhost:11434`|
| `OPENAI_API_KEY`     | Your OpenAI API key (if using `openai`)              | -                       |
| `GOOGLE_API_KEY`     | Your Google API key (if using `gemini`)              | -                       |

---

## All CLI Commands

```bash
# ─── Server ───────────────────────────────────────────
# Start the DTGS server (Dashboard + OpenAPI Catalog)
uv run python cli.py serve --port 8000

# ─── Ingestion ────────────────────────────────────────
# Ingest from GitHub
uv run python cli.py ingest https://github.com/owner/repo \
   --namespace service_a --base-url "https://api.a.com"

# Ingest from local folder
uv run python cli.py ingest-local ./my-project \
   --namespace service_local --base-url "https://api.local.com"

# Targeted ingestion (only specific packages)
uv run python cli.py ingest-local ./my-project \
   --namespace service_local --include-file packages.txt

# ─── Chat Agent ───────────────────────────────────────
# Interactive chat with dry-run (no backend needed)
uv run python cli.py chat --namespace service_local

# Interactive chat with live HTTP calls
uv run python cli.py chat --namespace service_local --live

# Chat with a specific LLM
uv run python cli.py chat -n service_local --provider gemini

# ─── Registry Management ─────────────────────────────
# Delete a namespace
uv run python cli.py delete service_a

# Export OpenAPI spec to file
uv run python cli.py export --namespace service_a --output my_api_spec.json

# ─── Debug / Analysis ────────────────────────────────
# Analyze a GitHub repo (no registry, raw output)
uv run python cli.py analyze https://github.com/owner/repo --output schemas.json

# Analyze a local directory (no registry, raw output)
uv run python cli.py analyze-local ./my-project --output schemas.json

# Ask the LangGraph agent a question (legacy Graph 2)
uv run python cli.py run-agent "list all REST endpoints" --registry dtgs.db
```

---

## What Gets Extracted from Java

For each Java method the analyzer captures:

- Class name and method name
- All parameters with types
- Return type
- Access modifiers (`public`, `private`, `static` …)
- Javadoc description and `@param` / `@return` tags
- Spring Boot REST annotations (`@GetMapping`, `@PostMapping`, `@PutMapping`, `@DeleteMapping`, `@PatchMapping`, `@RequestMapping`)

### Example — Input Java

```java
/**
 * Returns a greeting message.
 * @param name The user's name.
 */
@GetMapping("/greet")
public String greet(@RequestParam String name) {
    return "Hello, " + name;
}
```

### Example — Output Schema (OpenAI function-calling)

```json
{
  "type": "function",
  "function": {
    "name": "GreetController_greet",
    "description": "Returns a greeting message. @param name The user's name.",
    "parameters": {
      "type": "object",
      "properties": {
        "name": { "type": "string", "description": "String name" }
      },
      "required": ["name"]
    }
  }
}
```

---

## Project Structure

```
toolmaker/
├── cli.py                       # CLI (ingest, serve, chat, analyze, export)
├── models.py                    # Pydantic models (AnalyzedMethod, ToolSchema)
├── agent/
│   ├── openapi_to_tools.py      # OpenAPI spec → LLM tool format converter
│   └── http_executor.py         # HTTP executor with dry-run mode
├── server/
│   ├── catalog.py               # FastAPI server (dashboard, catalog, ingest API)
│   └── static/
│       └── index.html           # Web dashboard SPA (vanilla HTML/CSS/JS)
├── ingestion/
│   └── github.py                # Git clone + .java file discovery
├── analyzer/
│   ├── java_analyzer.py         # tree-sitter-java AST parser
│   └── schema_generator.py      # Method → OpenAI schema with DTO resolution
├── registry/
│   ├── sqlite_registry.py       # Multi-tenant SQLite store
│   └── openapi_generator.py     # OpenAI schemas → OpenAPI 3.1.0 generator
└── graphs/
    ├── ingestion_graph.py       # Graph 1 wiring (Send API, conditional edges)
    ├── agent_graph.py           # Graph 2 agent pipeline
    └── nodes/
        ├── ingest_nodes.py      # Ingestion pipeline nodes
        ├── schema_nodes.py      # Schema generation & enhancement nodes
        └── agent_nodes.py       # Agent query pipeline nodes
```

---

## Running Tests

```bash
uv run pytest tests/ -v
```

---

## Recommended Local Models (Ollama)

| Model | Size | Tool Calling | Notes |
|---|---|---|---|
| `llama3.2` | 2B / 3B | Good | Default; fast on CPU |
| `mistral` | 7B | Good | Strong reasoning |
| `qwen2.5` | 7B | Excellent | Best tool-calling support |
| `llama3.1` | 8B | Good | Balanced |
| `phi4-mini` | 3.8B | Fair | Very fast on low RAM |

> **Tip:** For best tool-calling results with Ollama, prefer `qwen2.5` or `mistral`.

---

## Roadmap

- [x] Sandboxed tool execution (Substituted via OpenAPI Decoupled Chatbots)
- [x] FastAPI Server with OpenAPI/MCP compatible schemas (Multi-tenant)
- [x] Web Dashboard for visual ingestion & spec browsing
- [x] Interactive Chat Agent with LLM function calling (dry-run + live)
- [x] Cross-package DTO resolution for accurate schemas
- [ ] LangGraph Studio integration
- [ ] Multi-language support (TypeScript, Python)
- [ ] Vector store upgrade (ChromaDB / pgvector)
