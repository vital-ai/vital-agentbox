# Quickstart

This guide walks through creating a sandbox, running code, and working with
files using the Python client SDK.

## Prerequisites

- AgentBox server running (see [Installation](install.md))
- Client installed: `pip install vital-agentbox[client]`

## Start the server (local dev)

```bash
# Single worker mode (simplest)
uvicorn agentbox.api.app:app --port 8090
```

Or with Docker Compose:

```bash
docker compose up
```

The API is now available at `http://localhost:8090`.

## Connect and create a sandbox

### Async

```python
from agentbox.client import AgentBoxClient

async with AgentBoxClient("http://localhost:8090") as client:
    sandbox = await client.create_sandbox(box_type="mem")
    print(sandbox.sandbox_id)  # e.g. "a1b2c3d4..."
```

### Sync

```python
from agentbox.client import AgentBoxClient

client = AgentBoxClient("http://localhost:8090")
sandbox = client.create_sandbox_sync(box_type="mem")
```

## Run Python code

```python
result = sandbox.execute_sync("print(2 + 2)")
print(result.stdout)     # "4\n"
print(result.exit_code)  # 0
```

Multi-line code works:

```python
result = sandbox.execute_sync("""
import math
for i in range(5):
    print(f"{i}: {math.factorial(i)}")
""")
print(result.stdout)
# 0: 1
# 1: 1
# 2: 2
# 3: 6
# 4: 24
```

## Run shell commands

```python
result = sandbox.execute_sync("echo hello world", language="shell")
print(result.stdout)  # "hello world\n"
```

Shell commands run against an in-memory filesystem with 30+ builtins:

```python
# Create files, use pipes, redirects
sandbox.execute_sync("""
mkdir -p /workspace/src
echo 'print("hello")' > /workspace/src/main.py
cat /workspace/src/main.py
""", language="shell")

# Run the Python file
sandbox.execute_sync("python /workspace/src/main.py", language="shell")
```

## File operations

```python
# Write a file
sandbox.write_file_sync("/data.txt", "line 1\nline 2\nline 3\n")

# Read it back
content = sandbox.read_file_sync("/data.txt")
print(content)  # "line 1\nline 2\nline 3\n"

# List directory
entries = sandbox.list_files_sync("/")
for e in entries:
    print(e["name"], e.get("type", ""))

# Create directories
sandbox.mkdir_sync("/workspace/output")
```

## Use the edit builtin

The `edit` command provides LLM-friendly file editing with fuzzy matching:

```python
# Create a file
sandbox.execute_sync("edit /app.py --create 'def hello():\n    print(\"hi\")'", language="shell")

# View it
result = sandbox.execute_sync("edit /app.py --view", language="shell")
print(result.stdout)
#      1	def hello():
#      2	    print("hi")

# Replace a string
sandbox.execute_sync(
    "edit /app.py --old 'print(\"hi\")' --new 'print(\"hello world\")'",
    language="shell"
)
```

## One-shot execution

For quick tasks that don't need a persistent sandbox:

```python
result = await client.run("print(sum(range(100)))")
print(result.stdout)  # "4950\n"
# Sandbox is created and destroyed automatically
```

## GitBox — persistent repositories

```python
sandbox = client.create_sandbox_sync(box_type="git", repo_id="my-project")

# Git operations work inside the sandbox
sandbox.execute_sync("git init", language="shell")
sandbox.execute_sync("""
echo '# My Project' > README.md
git add README.md
git commit -m 'Initial commit'
""", language="shell")

result = sandbox.execute_sync("git log --oneline", language="shell")
print(result.stdout)
```

## Cleanup

Always destroy sandboxes when done:

```python
sandbox.destroy_sync()
```

Or use async context managers:

```python
async with AgentBoxClient("http://localhost:8090") as client:
    sandbox = await client.create_sandbox()
    try:
        result = await sandbox.execute("print('hello')")
    finally:
        await sandbox.destroy()
```

## Next steps

- [Sandbox overview](../sandbox/overview.md) — MemBox vs GitBox in detail
- [Client SDK reference](../api/client-sdk.md) — full API
- [Shell builtins](../sandbox/builtins.md) — all available commands
- [Deployment](deployment.md) — Docker, scaling, production setup
