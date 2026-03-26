# Dynamic Tool Generation System (DTGS)

**Automatically discovers LLM-callable tools from Java GitHub repositories** using tree-sitter AST parsing and LangGraph pipelines — no JVM required.

---

## How It Works

DTGS operates strictly as a **Multi-Tenant Tool Catalog**. It completely avoids taking on execution bottlenecks.
Instead, it provides the phonebook (OpenAPI specification) so that external LLM chatbots can make API calls directly.

```
Graph 1 — Ingestion Pipeline:
  GitHub URL → clone → discover .java files
             → [parallel AST parse per file]
             → extract REST paths, HTTP methods, and parameters
             → store in SQLite registry under a specific `namespace`

FastAPI Server — OpenAPI Catalog:
  GET /api/v1/{namespace}/openapi.json
             → Dynamically builds strict OpenAPI 3.1.0 specifications
             → ANY chatbot (ChatGPT, Claude, LangChain) reads this URL
             → Chatbot makes direct HTTP execution calls to your Java backend
```

```

### 🧠 Smart Delta Caching (Ingestion Optimization)
DTGS calculates a deterministic cryptographic hash for every method it analyzes. If you re-run an ingestion on the same repository, DTGS perfectly bypasses expensive LLM API calls and Embedding API calls for methods that haven't structurally changed since the last run.

### 🧹 Path Filtering & Automatic Test Exclusion 
By default, DTGS ignores common non-source directories as well as `test` and `tests` directories to ensure your agent's tools aren't cluttered with mock functions.
Additionally, you can supply an `--include-file` to aggressively limit the scan to exact package paths. The text file should simply contain **one package or folder substring per line**.

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
com/petclinic/owner
com/petclinic/vet
```

### Step 2 — Ingest a repository into a namespace

```bash
uv run python cli.py ingest https://github.com/spring-projects/spring-petclinic \
   --namespace petclinic \
   --base-url "http://localhost:8080" \
   --include-file packages.txt
```

### Step 3 — Start the OpenAPI Catalog Server

```bash
uv run python cli.py serve --port 8000
```

### Step 4 — Hook up your Chatbot

Point ChatGPT Custom Actions, LangChain, or Claude to:
**`http://localhost:8000/api/v1/petclinic/openapi.json`**

The chatbot will instantly learn your Java backend and can make direct HTTP calls to it.

---

## 🛠️ Dynamic Triggers (On-The-Fly Ingestion)

You can command DTGS to ingest new repositories dynamically via HTTP (useful for CI/CD or other orchestrating agents):
```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/org/new-service", "namespace": "new_service", "base_url": "https://api.new.com"}'
```

---

## Model Backends

DTGS supports both cloud and local LLMs. Configure via environment variables:

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

   uv run python cli.py run-agent "find all pets by owner ID" --registry petclinic.db
   ```

### Option B — OpenAI

```bash
$env:OPENAI_API_KEY = "sk-..."
$env:DTGS_PROVIDER  = "openai"   # default, can omit
$env:DTGS_MODEL     = "gpt-4o-mini"

uv run python cli.py run-agent "find all pets by owner ID" --registry petclinic.db
```

### Environment Variable Reference

DTGS automatically loads `.env` files from your working directory. It needs to know where to send its LLM reasoning tasks.

| Variable             | Description                                          | Default                 |
|----------------------|------------------------------------------------------|-------------------------|
| `DTGS_PROVIDER`      | `openai`, `ollama`, or `gemini`                      | `openai`                |
| `DTGS_MODEL`         | Model name (`gpt-4o-mini`, `gemini-2.5-flash`, etc.) | varies by provider      |
| `DTGS_BASE_URL`      | Target URL if running `ollama`                       | `http://localhost:11434`|
| `OPENAI_API_KEY`     | Your OpenAI API key (if using `openai`)              | -                       |
| `GOOGLE_API_KEY`     | Your Google API key (if using `gemini`)              | -                       |

Example using Gemini locally:
```bash
export DTGS_PROVIDER=gemini
export DTGS_MODEL=gemini-2.5-flash
export GOOGLE_API_KEY="AIzaSy..."
```

## All CLI Commands

```bash
# [Catalog Server] Start the FastAPI OpenAPI server
uv run python cli.py serve --port 8000

# [Ingestion] Populate a namespace in the SQLite registry
# NOTE: Uses the LLM to write fantastic descriptions for the tools by default!
uv run python cli.py ingest https://github.com/owner/repo --namespace service_a --base-url "https://api.a.com"

# [Targeted Ingestion] Only scan specific packages listed in a file
echo "com/petclinic/owner" > packages.txt
uv run python cli.py ingest https://github.com/owner/repo --namespace service_a --include-file packages.txt

# [Registry Management] Delete an entire namespace from the database
uv run python cli.py delete service_a

# [Offline Export] Save the exact openapi.json file for a namespace locally
uv run python cli.py export --namespace service_a --output my_api_spec.json


# [Debug] Analyze a GitHub repo and print schemas only (no registry)
uv run python cli.py analyze https://github.com/owner/repo --output schemas.json

# [Debug] Analyze a local directory and print schemas only
uv run python cli.py analyze-local ./my-project --output schemas.json

# [Debug] Ask the local terminal LangGraph agent a question
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
├── models.py                    # Pydantic models (AnalyzedMethod, ToolSchema)
├── cli.py                       # CLI entrypoints (ingest, serve, analyze)
├── server/
│   └── catalog.py               # FastAPI server (GET openapi.json, POST ingest)
├── ingestion/
│   └── github.py                # Git clone + .java file discovery
├── analyzer/
│   ├── java_analyzer.py         # tree-sitter-java AST parser
│   └── schema_generator.py      # Method → OpenAI schema
├── registry/
│   ├── sqlite_registry.py       # Multi-tenant SQLite store
│   └── openapi_generator.py     # OpenAI schemas → OpenAPI 3.1.0 generator
└── graphs/
    ├── ingestion_graph.py       # Graph 1 wiring (Send API, conditional edges)
    ├── agent_graph.py           # Graph 2 simulated execution pipeline
    └── nodes/
        └── ...
```

---

## Running Tests

```bash
uv run pytest tests/ -v
# 54 tests — all should pass
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
- [ ] LangGraph Studio integration
- [ ] Multi-language support (TypeScript, Python)
- [ ] Vector store upgrade (ChromaDB / pgvector)
