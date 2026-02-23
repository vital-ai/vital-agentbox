# LangChain Integration

AgentBox provides LangChain tools and a backend for building agents with
sandbox access using LangChain and LangGraph.

## Installation

```bash
pip install vital-agentbox[langchain]
```

This installs `httpx` and `langchain-core`.

## AgentBoxToolkit

Bundles all AgentBox tools for easy integration with LangGraph agents.

```python
from agentbox.langchain import AgentBoxToolkit

toolkit = AgentBoxToolkit(base_url="http://localhost:8090")
tools = toolkit.get_tools()
# Returns: [CodeExecutionTool, ShellExecutionTool, FileWriteTool, FileReadTool]
```

### Filtering tools

```python
# Only include specific tools
tools = toolkit.get_tools(include=["execute_code", "file_read"])
```

### With a LangGraph agent

```python
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

toolkit = AgentBoxToolkit(base_url="http://localhost:8090")
tools = toolkit.get_tools()

model = ChatOpenAI(model="gpt-4o")
agent = create_react_agent(model, tools)

result = agent.invoke({
    "messages": [{"role": "user", "content": "Write a Python script that computes fibonacci(10)"}]
})
```

## Tools

### CodeExecutionTool

Execute Python or shell code in a persistent sandbox.

- **Name**: `execute_code`
- **Input**: `code` (str), `language` (str, default `"python"`)
- **Output**: stdout, stderr, exit_code

The sandbox persists between calls — variables, files, and installed
packages are retained.

```python
from agentbox.langchain import CodeExecutionTool
from agentbox.client import AgentBoxClient

client = AgentBoxClient("http://localhost:8090")
tool = CodeExecutionTool(client=client)

# LLM calls this tool
result = tool.invoke({"code": "x = 42\nprint(x)", "language": "python"})
```

### ShellExecutionTool

Shell-only variant of CodeExecutionTool.

- **Name**: `execute_shell`
- **Input**: `command` (str)
- **Output**: stdout, stderr, exit_code

```python
from agentbox.langchain import ShellExecutionTool

tool = ShellExecutionTool(client=client)
result = tool.invoke({"command": "ls -la /"})
```

### FileWriteTool

Write files into the sandbox with auto-mkdir.

- **Name**: `file_write`
- **Input**: `path` (str), `content` (str)
- **Output**: success/error message

```python
from agentbox.langchain import FileWriteTool

tool = FileWriteTool(client=client)
result = tool.invoke({"path": "/app/main.py", "content": "print('hello')"})
```

### FileReadTool

Read files from the sandbox.

- **Name**: `file_read`
- **Input**: `path` (str)
- **Output**: file contents or error message

```python
from agentbox.langchain import FileReadTool

tool = FileReadTool(client=client)
result = tool.invoke({"path": "/app/main.py"})
```

## AgentBoxBackend

A higher-level backend for Deep Agents that manages sandbox lifecycle
automatically.

```python
from agentbox.langchain import AgentBoxBackend

backend = AgentBoxBackend(
    base_url="http://localhost:8090",
    box_type="mem",           # or "git"
    auto_cleanup=True,        # destroy sandbox on close
)
```

### Methods

| Method | Description |
|--------|-------------|
| `execute_python(code)` | Run Python code |
| `execute_shell(command)` | Run shell command |
| `write_file(path, content)` | Write a file |
| `read_file(path)` | Read a file |
| `list_files(path)` | List directory |
| `close()` | Cleanup (destroys sandbox if `auto_cleanup=True`) |
| `reset()` | Destroy current sandbox, next call creates a new one |

The backend lazily creates a sandbox on first use and reuses it across
calls. Call `reset()` to start fresh.

```python
backend = AgentBoxBackend(base_url="http://localhost:8090")

# First call creates the sandbox
result = await backend.execute_python("print(42)")

# Subsequent calls reuse the same sandbox
result = await backend.execute_shell("ls /")

# Cleanup
await backend.close()
```

## Sandbox persistence

All tools share a single sandbox per toolkit/backend instance. State
(variables, files, installed packages) persists across tool invocations
within the same conversation.

```
Call 1: execute_code("x = 42")          → sandbox created, x = 42
Call 2: execute_code("print(x)")        → same sandbox, prints 42
Call 3: file_write("/data.txt", "hi")   → same sandbox, file created
Call 4: execute_shell("cat /data.txt")  → same sandbox, prints "hi"
```

## See also

- [Deep Agents backend](deepagents.md) — lower-level `BaseSandbox` integration
- [Client SDK](../api/client-sdk.md) — the underlying client
- [Sandbox overview](../sandbox/overview.md) — MemBox vs GitBox
