"""Deep Agents integration for AgentBox.

Provides ``AgentBoxSandbox`` — a sandbox backend that implements
the Deep Agents ``BaseSandbox`` protocol, so AgentBox can be used
as a drop-in replacement for Modal, Daytona, or Runloop sandboxes.

Usage::

    from agentbox.deepagents import AgentBoxSandbox
    from agentbox.client import AgentBoxClient
    from deepagents import create_deep_agent

    client = AgentBoxClient("http://localhost:8090")
    sandbox = client.create_sandbox_sync(box_type="git", repo_id="my-project")
    backend = AgentBoxSandbox(sandbox=sandbox)

    agent = create_deep_agent(
        backend=backend,
        system_prompt="You are a coding assistant with sandbox access.",
    )

    result = agent.invoke({
        "messages": [{"role": "user", "content": "Create and run a Python script"}]
    })

    sandbox.destroy_sync()
"""

from agentbox.deepagents.sandbox import AgentBoxSandbox

__all__ = ["AgentBoxSandbox"]
