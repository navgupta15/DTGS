# Dynamic Tool Generation System (DTGS)

**Automatically discovers LLM-callable tools from Java GitHub repositories** using tree-sitter AST parsing and LangGraph pipelines — no JVM required.

---

## How It Works

DTGS runs two LangGraph StateGraphs:

```
Graph 1 — Ingestion Pipeline:
  GitHub URL → clone → discover .java files
             → [parallel AST parse per file]  ← Send API fan-out
             → generate OpenAI schemas
             → embed (optional)
             → store in SQLite registry

Graph 2 — Agent Query Pipeline:
  User query → search registry → LLM selects tool
             → execute tool → synthesize answer
             → [loop until done or max iterations]
```

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

### Step 1 — Ingest a Java repo

```bash
# From GitHub
uv run python cli.py ingest https://github.com/spring-projects/spring-petclinic --registry petclinic.db

# From a local Java project
uv run python cli.py analyze-local ./my-java-project --output tools.json
```

### Step 2 — Query with the Agent

Choose a model backend — **no OpenAI key required if you use Ollama**.

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

| Variable | Default | Description |
|---|---|---|
| `DTGS_PROVIDER` | `openai` | `openai` or `ollama` |
| `DTGS_MODEL` | `gpt-4o-mini` / `llama3.2` | Model name |
| `DTGS_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OPENAI_API_KEY` | — | Required when `DTGS_PROVIDER=openai` |

---

## All CLI Commands

```bash
# Analyze a GitHub repo — prints schemas only, no registry
uv run python cli.py analyze https://github.com/owner/repo --output schemas.json

# Analyze a local Java directory — prints schemas only
uv run python cli.py analyze-local ./my-project --output schemas.json --public-only

# Ingest GitHub repo into SQLite registry (Graph 1)
uv run python cli.py ingest https://github.com/owner/repo --registry dtgs.db

# Ask the LLM agent a question (Graph 2)
uv run python cli.py run-agent "list all REST endpoints" --registry dtgs.db --max-iter 3
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
├── ingestion/github.py          # Git clone + .java file discovery
├── analyzer/
│   ├── java_analyzer.py         # tree-sitter-java AST parser
│   └── schema_generator.py      # Method → OpenAI schema
├── registry/
│   └── sqlite_registry.py       # SQLite store + cosine similarity search
└── graphs/
    ├── state.py                 # IngestionState, AgentState TypedDicts
    ├── ingestion_graph.py       # Graph 1 wiring (Send API, conditional edges)
    ├── agent_graph.py           # Graph 2 wiring (loop + iteration guard)
    └── nodes/
        ├── ingest_nodes.py      # clone, discover, fan_out, analyze, store
        ├── schema_nodes.py      # generate_schemas, embed_tools
        └── agent_nodes.py       # receive_query, search_tools, llm_select_tool …
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

- [ ] Sandboxed tool execution (subprocess / Docker)
- [ ] FastAPI server with MCP protocol endpoint
- [ ] LangGraph Studio integration
- [ ] Multi-language support (TypeScript, Python)
- [ ] Vector store upgrade (ChromaDB / pgvector)
