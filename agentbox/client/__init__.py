"""AgentBox Python client — lightweight SDK for the AgentBox service.

Install with::

    pip install vital-agentbox[client]

Usage::

    from agentbox.client import AgentBoxClient

    async with AgentBoxClient("http://localhost:8090") as client:
        sandbox = await client.create_sandbox()
        result = await sandbox.execute("print(2+2)")
        print(result.stdout)  # "4\n"
        await sandbox.destroy()
"""

from agentbox.client.client import AgentBoxClient, Sandbox, ExecuteResult

__all__ = ["AgentBoxClient", "Sandbox", "ExecuteResult"]
