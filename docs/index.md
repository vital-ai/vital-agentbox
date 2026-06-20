# AgentBox

Secure sandboxed code execution for AI agents.

AgentBox runs Python and shell commands in isolated sandboxes. Two execution
engines are available: **Pyodide** (WASM in Chromium — zero egress) and
**AgentCore** (AWS Bedrock MicroVM — real bash, real pip).

## Key features

- **Dual-layer isolation** — Chromium renderer sandbox + WASM linear memory (Pyodide)
- **Real MicroVM execution** — AWS AgentCore with native Python, bash, pip (AgentCore)
- **Virtual shell** — tree-sitter-bash parser with 30+ builtins against in-memory FS
- **Browser sessions** — Playwright-backed remote browser control via WebSocket
- **Git operations** — isomorphic-git on MemFS or real git in AgentCore, with S3 storage
- **LLM file editing** — `edit` builtin with 5-tier fuzzy matching + AST-aware fallback
- **S3 data access modes** — tenant-scoped, caller-path, or caller-credentials
- **Client SDK** — async/sync Python client, LangChain tools, Deep Agents backend

## Quick start

```bash
pip install vital-agentbox[client]
```

```python
from agentbox.client import AgentBoxClient

client = AgentBoxClient("http://localhost:8090")
sandbox = client.create_sandbox_sync(box_type="mem")

# Run Python
result = sandbox.execute_sync("print(2 + 2)")
print(result.stdout)  # "4\n"

# Run shell
result = sandbox.execute_sync("echo hello > /file.txt && cat /file.txt", language="shell")
print(result.stdout)  # "hello\n"

# File operations
sandbox.write_file_sync("/data.txt", "hello world")
content = sandbox.read_file_sync("/data.txt")

sandbox.destroy_sync()
```

## Box types

| Type | Engine | Description | Use case |
|------|--------|-------------|----------|
| **MemBox** | Pyodide | Ephemeral in-memory sandbox | Default. Data analysis, code generation, testing |
| **GitBox** | Pyodide | MemBox + isomorphic-git + storage | Persistent repos, commit/branch/merge, push to S3 |
| **AgentCoreBox** | AgentCore | Real Linux MicroVM + real git | Compiled packages, real bash, large files |
| **FileSystemBox** | Host | Host directory (dev only) | Local development and debugging |

## Architecture overview

```
┌─────────────────────────────────────────────┐
│  Orchestrator (FastAPI)                     │
│  Auth, routing, scaling, Redis state        │
└───────┬────────────────────────────┬────────┘
        │ HTTP proxy                     │
┌───────▼──────────────────────┐  ┌────▼─────────────┐
│  Worker (code mode)            │  │  Worker (browser)   │
│  ┌──────────────────────────┐ │  │  SessionPool      │
│  │ Chromium + Pyodide (WASM)  │ │  │  Playwright       │
│  │ ─ or ─                     │ │  │  WebSocket ctrl   │
│  │ AgentCore (MicroVM)       │ │  └──────────────────┘
│  └──────────────────────────┘ │
└───────────────────────────────┘
```

## Documentation

- **Getting started**
  - [Installation](getting-started/install.md)
  - [Quickstart](getting-started/quickstart.md)
  - [Deployment](getting-started/deployment.md)
- **Sandbox**
  - [Overview — MemBox vs GitBox vs AgentCore](sandbox/overview.md)
  - [AgentCore engine (AWS MicroVM)](sandbox/agentcore.md)
  - [Shell execution](sandbox/shell.md)
  - [Shell builtins reference](sandbox/builtins.md)
  - [Python execution](sandbox/python.md)
  - [Git operations](sandbox/git.md)
  - [Files and MemFS](sandbox/files.md)
- **API**
  - [Client SDK](api/client-sdk.md)
  - [REST API — Worker](api/worker-api.md)
  - [REST API — Orchestrator](api/orchestrator-api.md)
- **Integrations**
  - [Deep Agents sandbox backend](integrations/deepagents.md)
  - [LangChain tools](integrations/langchain.md)
- **Operations**
  - [Docker](operations/docker.md)
  - [Scaling](operations/scaling.md)
  - [Storage backends](operations/storage.md)
  - [S3 data access modes](operations/data-access.md)
- **Reference**
  - [Configuration](reference/config.md)
  - [Changelog](changelog.md)

## License

Apache 2.0
