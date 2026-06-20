# AgentCore Engine

AWS Bedrock AgentCore Code Interpreter — a real Linux MicroVM execution engine.

Unlike the default Pyodide engine (WASM sandbox in Chromium), AgentCore runs
code in a full Linux environment with real Python, real bash, real pip, and a
real filesystem.

## When to use AgentCore

| Need | Use AgentCore | Use Pyodide |
|------|:---:|:---:|
| Real pip install (compiled packages) | ✓ | ✗ |
| Real bash (systemd, apt, curl) | ✓ | ✗ |
| Real filesystem (large files, symlinks) | ✓ | ✗ |
| Sub-second cold start | ✗ | ✓ |
| No AWS dependency | ✗ | ✓ |
| Network isolation (zero egress) | ✗ | ✓ |

## Quick start

```python
from agentbox.client import AgentBoxClient

client = AgentBoxClient("http://localhost:8090")
sandbox = client.create_sandbox_sync(engine="agentcore")

# Real Python with compiled packages
result = sandbox.execute_sync("import numpy; print(numpy.__version__)")

# Real bash
result = sandbox.execute_sync("pip install pandas && python -c 'import pandas; print(pandas.__version__)'", language="shell")

# Real filesystem
result = sandbox.execute_sync("ls -la /", language="shell")

sandbox.destroy_sync()
```

## Comparison: PyodideEngine vs AgentCoreEngine

| Feature | PyodideEngine | AgentCoreEngine |
|---------|---------------|-----------------|
| Runtime | CPython 3.11 → WASM | CPython 3.11+ (native) |
| Shell | tree-sitter-bash emulator (30+ builtins) | Real bash |
| Filesystem | Emscripten MemFS (in-memory) | Real ext4 (MicroVM) |
| pip install | micropip (pure-Python wheels only) | Real pip (any wheel) |
| Network | Blocked (no egress) | Allowed (internet access) |
| Cold start | ~2s | ~5–8s |
| Isolation | Chromium sandbox + WASM | AWS Firecracker MicroVM |
| Max session | In-memory (until worker restarts) | Configurable (default 30 min idle) |
| Dependencies | `[worker]` extra (Playwright) | `[agentcore]` extra (bedrock-agentcore, boto3) |

## Host-intercepted commands

Even though AgentCore has real bash, certain commands are intercepted and
run host-side for richer functionality:

| Command | Why intercepted |
|---------|----------------|
| `edit` | Full 5-tier fuzzy matching + AST-aware patching |
| `apply_patch` | V4A patch format with multi-file support |
| `git push` / `git pull` | Routes through S3 storage backend |

All other commands pass through to real bash in the MicroVM.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_AGENTCORE_REGION` | `us-east-1` | AWS region |
| `AGENTBOX_AGENTCORE_SESSION_TIMEOUT` | `1800` | Idle timeout (seconds) |
| `AGENTBOX_AGENTCORE_INTERPRETER_ID` | — | Custom interpreter ID |

## Prerequisites

1. AWS credentials with access to Bedrock AgentCore Code Interpreter
2. `[agentcore]` extra installed:
   ```bash
   pip install vital-agentbox[agentcore]
   ```

## Architecture

```
Worker Process
├── BoxManager
│   └── AgentCoreBox (per sandbox)
│       ├── AgentCoreEngine (boto3 → AWS)
│       │   └── CodeInterpreter session (MicroVM)
│       ├── Host interception (edit, apply_patch)
│       └── S3 sync (git push/pull via engine_sync)
```

Each `AgentCoreBox` maps to one AgentCore session (one MicroVM). Sessions
persist state (variables, files, installed packages) across calls until
stopped or timed out.

## S3 persistence

When `repo_id` is provided, AgentCoreBox syncs files to/from S3:

- **On start**: pulls files from S3 into the MicroVM workspace
- **On stop** (if `auto_sync=True`): pushes files back to S3
- **On `git push`**: explicit sync to S3
- **On `git pull`**: explicit sync from S3

File transfer uses base64 encoding via shell (`base64 < file | base64 -d > file`)
to handle binary content through the engine's `execute_shell()` interface.

## See also

- [Sandbox overview](overview.md) — all box types
- [Configuration](../reference/config.md) — full env var reference
- [Storage backends](../operations/storage.md) — S3/MinIO setup
