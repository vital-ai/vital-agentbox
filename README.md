# vital-agentbox

Secure sandboxed code execution for AI agents. Runs Python and shell
commands inside a Chromium + Pyodide (WASM) sandbox with two independent
security boundaries — no host filesystem or network access from agent code.

## Features

- **Dual-layer isolation** — Chromium renderer sandbox + WASM linear memory
- **Virtual shell** — tree-sitter-bash parser with 30+ builtins on in-memory FS
- **Python execution** — Pyodide (CPython 3.11 compiled to WASM)
- **Git operations** — isomorphic-git on Emscripten MemFS with S3/MinIO storage
- **AI-friendly editing** — `edit` builtin with fuzzy + AST-aware matching
- **LangChain & Deep Agents** — toolkit, tools, and sandbox backend integrations
- **Scalable** — orchestrator + worker architecture with Redis routing

## Box types

| Type | Description |
|------|-------------|
| **MemBox** | Ephemeral in-memory sandbox (default) |
| **GitBox** | MemBox + isomorphic-git + pluggable storage (S3/MinIO/local) |
| **FileSystemBox** | Local dev only, backed by host directory |

## Install

```bash
# Lightweight client (for LangGraph / Deep Agent apps)
pip install vital-agentbox[client]

# Sandbox worker (runs Chromium + Pyodide)
pip install vital-agentbox[worker]
playwright install chromium

# Orchestrator (routes requests to workers, no Chromium)
pip install vital-agentbox[orchestrator]

# LangChain integration
pip install vital-agentbox[langchain]
```

## Quick start

```python
from agentbox.client import AgentBoxClient

client = AgentBoxClient("http://localhost:8090")

# Create a sandbox
sandbox = client.create_sandbox_sync(box_type="mem")

# Run Python
result = sandbox.execute_sync("print(2 + 2)")
print(result.stdout)  # "4\n"

# Run shell commands
result = sandbox.execute_sync('echo "hello" > /file.txt && cat /file.txt', language="shell")
print(result.stdout)  # "hello\n"

# AI-friendly file editing
result = sandbox.execute_sync(
    "edit /file.txt --old 'hello' --new 'world'",
    language="shell",
)

# Cleanup
sandbox.destroy_sync()
```

## LangChain integration

```python
from agentbox.langchain import AgentBoxToolkit

toolkit = AgentBoxToolkit(base_url="http://localhost:8090")
tools = toolkit.get_tools()
# → [CodeExecutionTool, ShellExecutionTool, FileWriteTool, FileReadTool]
```

## Docker

```bash
# Full stack (orchestrator + 2 workers + MinIO)
docker compose up

# Single worker
docker run -p 8090:8000 --shm-size=2g agentbox-worker
```

## Documentation

Full documentation is in the [`docs/`](docs/index.md) directory:

- [Getting started](docs/getting-started/install.md)
- [Sandbox overview](docs/sandbox/overview.md)
- [Shell builtins reference](docs/sandbox/builtins.md)
- [Client SDK reference](docs/api/client-sdk.md)
- [REST API reference](docs/api/worker-api.md)
- [Deployment guide](docs/getting-started/deployment.md)

## System requirements

- Python ≥ 3.11
- Chromium (via `playwright install chromium`) — worker only
- Redis — orchestrator only
- For PDF generation: pandoc + LaTeX

## License

Apache 2.0
