# Deep Agents Sandbox Backend

AgentBox provides `AgentBoxSandbox` — a sandbox backend that implements
the Deep Agents `BaseSandbox` protocol. This lets you use AgentBox as a
drop-in replacement for Modal, Daytona, or Runloop sandboxes with
[Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview).

## Installation

```bash
pip install vital-agentbox[client]
pip install deepagents
```

## Usage

```python
from agentbox.client import AgentBoxClient
from agentbox.deepagents import AgentBoxSandbox
from deepagents import create_deep_agent

# Create a sandbox via the client SDK
client = AgentBoxClient("http://localhost:8090")
sandbox_info = client.create_sandbox_sync(box_type="git", repo_id="my-project")

# Wrap it as a Deep Agents backend
backend = AgentBoxSandbox(
    base_url="http://localhost:8090",
    sandbox_id=sandbox_info.sandbox_id,
)

# Create a Deep Agent with sandbox access
agent = create_deep_agent(
    backend=backend,
    system_prompt="You are a coding assistant with sandbox access.",
)

result = agent.invoke({
    "messages": [{"role": "user", "content": "Create and run a hello world script"}]
})

print(result["messages"][-1].content)

# Cleanup
sandbox_info.destroy_sync()
```

## What the backend provides

The `AgentBoxSandbox` backend gives the Deep Agent access to:

- **`execute`** tool — run shell commands in the sandbox
- **`read_file`** — read files with line numbers and pagination
- **`write_file`** — create new files
- **`edit_file`** — str_replace editing with fuzzy matching
- **`ls`** — list directories
- **`glob`** — find files by pattern
- **`grep`** — search file contents

## Interface

`AgentBoxSandbox` extends `BaseSandbox` from `deepagents.backends.sandbox`:

### Abstract methods (implemented)

| Method | Description |
|--------|-------------|
| `execute(command, timeout=None)` | Run a shell command, return `ExecuteResponse` |
| `id` | Sandbox identifier (property) |
| `upload_files(files)` | Upload files into the sandbox |
| `download_files(paths)` | Download files from the sandbox |

### Overridden methods (Tier 1 builtins)

These override `BaseSandbox`'s default `python3 -c` implementations with
AgentBox's faster Tier 1 shell builtins:

| Method | Implementation |
|--------|---------------|
| `read(file_path, offset, limit)` | `edit <file> --view --range N:M` |
| `write(file_path, content)` | `cat > <file> << 'EOF'` heredoc |
| `edit(file_path, old, new)` | `edit <file> --old '...' --new '...'` |
| `ls_info(path)` | `find <path> -maxdepth 1` |
| `glob_info(pattern, path)` | `find <path> -name <pattern>` |

### Inherited methods (from BaseSandbox)

| Method | Description |
|--------|-------------|
| `grep_raw(pattern, path, glob)` | Delegates to `grep` via `execute()` |

## Constructor

```python
AgentBoxSandbox(
    base_url: str,                    # AgentBox API URL
    sandbox_id: str,                  # Existing sandbox ID
    *,
    default_timeout: int = 120,       # Default command timeout (seconds)
    log_file: str | None = None,      # Optional log file path
)
```

## Factory method

```python
backend = AgentBoxSandbox.create(
    "http://localhost:8090",
    box_type="git",
    repo_id="my-project",
)
# Creates a new sandbox and returns a connected backend
```

## Lifecycle

The backend does NOT manage sandbox lifecycle — the caller is responsible
for creating and destroying sandboxes:

```python
client = AgentBoxClient("http://localhost:8090")
sandbox = client.create_sandbox_sync(box_type="mem")

backend = AgentBoxSandbox("http://localhost:8090", sandbox.sandbox_id)

# ... use with Deep Agent ...

backend.destroy()  # or sandbox.destroy_sync()
```

## See also

- [Client SDK](../api/client-sdk.md) — creating and managing sandboxes
- [LangChain tools](langchain.md) — toolkit for LangChain agents
- [Sandbox overview](../sandbox/overview.md) — MemBox vs GitBox
