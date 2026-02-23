# Client SDK

The AgentBox Python client (`agentbox.client`) is a lightweight async/sync
SDK for the AgentBox REST API. It depends only on `httpx`.

```bash
pip install vital-agentbox[client]
```

## AgentBoxClient

```python
from agentbox.client import AgentBoxClient
```

### Constructor

```python
AgentBoxClient(
    base_url: str = "http://localhost:8090",
    *,
    token: str | None = None,       # JWT/API token for auth
    timeout: float = 60.0,          # Default request timeout (seconds)
    headers: dict[str, str] | None = None,  # Extra HTTP headers
)
```

### Context manager (async)

```python
async with AgentBoxClient("http://localhost:8090", token="...") as client:
    sandbox = await client.create_sandbox()
    # ... use sandbox ...
```

The client creates an `httpx.AsyncClient` on enter and closes it on exit.
You can also call `await client.close()` explicitly.

### Sandbox lifecycle

| Method | Returns | Description |
|--------|---------|-------------|
| `create_sandbox(box_type="mem", repo_id=None)` | `Sandbox` | Create a new sandbox |
| `get_sandbox(sandbox_id)` | `Sandbox` | Get handle to existing sandbox |
| `list_sandboxes(**filters)` | `list[SandboxInfo]` | List visible sandboxes |
| `destroy_sandbox(sandbox_id)` | `None` | Destroy a sandbox by ID |

### One-shot execution

```python
result = await client.run("print(2+2)")
# Creates a sandbox, runs the code, destroys the sandbox, returns result
```

### Health

| Method | Returns | Description |
|--------|---------|-------------|
| `health()` | `dict` | Server health status |
| `metrics()` | `dict` | Aggregate metrics |
| `list_workers()` | `list[dict]` | Registered workers (orchestrator only) |

### Sync wrappers

Every async method has a `_sync` variant:

```python
client = AgentBoxClient("http://localhost:8090")
sandbox = client.create_sandbox_sync(box_type="git", repo_id="my-repo")
result = client.run_sync("print('hello')")
info = client.health_sync()
```

Sync wrappers use `asyncio.run()` or `nest_asyncio` if already inside an
event loop (e.g. Jupyter notebooks).

---

## Sandbox

A high-level handle to a single sandbox. Obtained from `client.create_sandbox()`
or `client.get_sandbox()`.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `sandbox_id` | `str` | Unique sandbox identifier |
| `state` | `str` | Current state (`"running"`, `"destroyed"`, etc.) |
| `box_type` | `str` | `"mem"` or `"git"` |

### Code execution

| Method | Returns | Description |
|--------|---------|-------------|
| `execute(code, language="python", timeout=None)` | `ExecuteResult` | Run Python or shell code |
| `run_python(code)` | `ExecuteResult` | Shorthand for `execute(code, language="python")` |
| `run_shell(command)` | `ExecuteResult` | Shorthand for `execute(command, language="shell")` |

```python
# Python
result = await sandbox.execute("import math; print(math.pi)")

# Shell
result = await sandbox.execute("ls -la /", language="shell")

# With timeout
result = await sandbox.execute("sleep 5 && echo done", language="shell", timeout=10)
```

### File operations

| Method | Returns | Description |
|--------|---------|-------------|
| `write_file(path, content)` | `bool` | Write a text file |
| `read_file(path)` | `str \| None` | Read a text file (None if not found) |
| `list_files(path="/", recursive=False)` | `list` | List directory entries |
| `mkdir(path)` | `bool` | Create directory (mkdir -p) |
| `remove_file(path)` | `bool` | Remove a file |
| `copy_file(src, dst)` | `bool` | Copy a file |

```python
await sandbox.write_file("/app/main.py", "print('hello')")
content = await sandbox.read_file("/app/main.py")
entries = await sandbox.list_files("/app")
```

### Lifecycle

| Method | Description |
|--------|-------------|
| `refresh()` | Refresh sandbox info from server |
| `destroy()` | Destroy this sandbox |

### Sync wrappers

Every async method has a `_sync` variant:

```python
sandbox.execute_sync("print(42)")
sandbox.write_file_sync("/data.txt", "hello")
content = sandbox.read_file_sync("/data.txt")
sandbox.destroy_sync()
```

---

## ExecuteResult

```python
from agentbox.client import ExecuteResult
```

| Field | Type | Description |
|-------|------|-------------|
| `stdout` | `str` | Standard output |
| `stderr` | `str` | Standard error |
| `exit_code` | `int` | Process exit code (0 = success) |
| `raw` | `dict` | Full response dict from the API |

---

## SandboxInfo

Returned by `client.list_sandboxes()`.

| Field | Type | Description |
|-------|------|-------------|
| `sandbox_id` | `str` | Unique identifier |
| `state` | `str` | Current state |
| `box_type` | `str` | `"mem"` or `"git"` |
| `worker_id` | `str \| None` | Worker hosting this sandbox |
| `created_at` | `float \| None` | Creation timestamp |

---

## Examples

### Data analysis

```python
sandbox = client.create_sandbox_sync()

sandbox.execute_sync("""
import numpy as np
data = np.random.randn(1000)
print(f"mean: {data.mean():.4f}")
print(f"std:  {data.std():.4f}")
""")

sandbox.destroy_sync()
```

### Multi-file project

```python
sandbox = client.create_sandbox_sync()

# Create project structure via shell
sandbox.execute_sync("""
mkdir -p /project/src
echo 'def add(a, b): return a + b' > /project/src/math_utils.py
echo 'from src.math_utils import add
print(add(3, 4))' > /project/main.py
""", language="shell")

# Run it
result = sandbox.execute_sync("cd /project && python main.py", language="shell")
print(result.stdout)  # "7\n"

sandbox.destroy_sync()
```

### GitBox workflow

```python
sandbox = client.create_sandbox_sync(box_type="git", repo_id="demo")

sandbox.execute_sync("""
git init
echo '# Demo' > README.md
git add README.md
git commit -m 'init'
git log --oneline
""", language="shell")

# Push to S3 storage
sandbox.execute_sync("git push", language="shell")

sandbox.destroy_sync()
```
