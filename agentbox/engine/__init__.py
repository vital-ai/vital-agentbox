"""Pluggable execution engine abstraction.

Engines provide the low-level primitives — code execution, shell commands,
and filesystem access. Higher-level features (git, editing, persistence)
sit in the Box layer above.

Available engines:
    - PyodideEngine: Playwright + Pyodide + MemFS (default)
    - AgentCoreEngine: AWS Bedrock AgentCore Code Interpreter (future)
"""

from agentbox.engine.base import ExecutionEngine

__all__ = [
    "ExecutionEngine",
    "PyodideEngine",
    "AgentCoreEngine",
]


def __getattr__(name):
    if name == "PyodideEngine":
        from agentbox.engine.pyodide_engine import PyodideEngine
        return PyodideEngine
    if name == "AgentCoreEngine":
        from agentbox.engine.agentcore_engine import AgentCoreEngine
        return AgentCoreEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
