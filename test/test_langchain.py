"""Test LangChain tools and AgentBoxBackend against the running docker-compose stack.

Prerequisites:
    docker compose up --build -d
    Orchestrator at http://localhost:8090
    pip install langchain-core
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from agentbox.client import AgentBoxClient
from agentbox.langchain import (
    AgentBoxToolkit,
    AgentBoxBackend,
    CodeExecutionTool,
    ShellExecutionTool,
    FileWriteTool,
    FileReadTool,
)


ORCHESTRATOR_URL = "http://localhost:8090"


async def main():
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  ✓ {name}")
        else:
            failed += 1
            print(f"  ✗ {name}")
            if detail:
                print(f"      {detail}")

    print("=" * 60)
    print("LANGCHAIN INTEGRATION TEST")
    print("=" * 60)

    # --- Toolkit ---
    print("\n--- AgentBoxToolkit ---")
    toolkit = AgentBoxToolkit(base_url=ORCHESTRATOR_URL)
    tools = toolkit.get_tools()
    check("toolkit returns 4 tools", len(tools) == 4, f"got {len(tools)}")
    tool_names = [t.name for t in tools]
    check("has execute_code", "execute_code" in tool_names, tool_names)
    check("has execute_shell", "execute_shell" in tool_names, tool_names)
    check("has write_file", "write_file" in tool_names, tool_names)
    check("has read_file", "read_file" in tool_names, tool_names)

    # --- Filtered toolkit ---
    toolkit2 = AgentBoxToolkit(base_url=ORCHESTRATOR_URL, include=["execute_code"])
    tools2 = toolkit2.get_tools()
    check("filtered toolkit", len(tools2) == 1 and tools2[0].name == "execute_code",
          f"got {[t.name for t in tools2]}")

    # --- CodeExecutionTool ---
    print("\n--- CodeExecutionTool ---")
    client = AgentBoxClient(ORCHESTRATOR_URL)
    code_tool = CodeExecutionTool(client=client)

    output = await code_tool._arun("print(3 * 7)")
    check("code tool output", "21" in output, output)

    output = await code_tool._arun("echo hi-from-tool", language="shell")
    check("code tool shell", "hi-from-tool" in output, output)

    # State persists in same tool
    await code_tool._arun("magic = 42")
    output = await code_tool._arun("print(magic)")
    check("code tool state persists", "42" in output, output)

    # --- ShellExecutionTool ---
    print("\n--- ShellExecutionTool ---")
    shell_tool = ShellExecutionTool(client=client)
    output = await shell_tool._arun("echo shell-tool-test")
    check("shell tool output", "shell-tool-test" in output, output)

    # --- FileWriteTool + FileReadTool ---
    print("\n--- File Tools ---")
    write_tool = FileWriteTool(client=client, sandbox=code_tool.sandbox)
    read_tool = FileReadTool(client=client, sandbox=code_tool.sandbox)

    output = await write_tool._arun("/data/report.txt", "Test report content")
    check("write tool", "Written" in output, output)

    output = await read_tool._arun("/data/report.txt")
    check("read tool", output == "Test report content", output)

    output = await read_tool._arun("/nonexistent.txt")
    check("read tool missing", "not found" in output.lower(), output)

    # Cleanup tools
    if code_tool.sandbox:
        await code_tool.sandbox.destroy()
    if shell_tool.sandbox:
        await shell_tool.sandbox.destroy()
    await client.close()

    # --- AgentBoxBackend ---
    print("\n--- AgentBoxBackend ---")
    async with AgentBoxBackend(base_url=ORCHESTRATOR_URL) as backend:
        check("backend created", backend.sandbox_id is None)

        # Execute python (lazy creates sandbox)
        result = await backend.execute_python("print('backend-test')")
        check("backend execute_python", result.success and "backend-test" in result.output,
              f"success={result.success} output={result.output}")
        check("backend has sandbox", backend.sandbox_id is not None)

        # Execute shell
        result = await backend.execute_shell("echo backend-shell")
        check("backend execute_shell", result.success and "backend-shell" in result.output,
              f"success={result.success} output={result.output}")

        # Generic execute
        result = await backend.execute("print(100)", language="python")
        check("backend execute generic", "100" in result.output, result.output)

        # File ops
        result = await backend.write_file("/workspace/test.md", "# Hello")
        check("backend write_file", result.success, result.error)

        result = await backend.read_file("/workspace/test.md")
        check("backend read_file", result.output == "# Hello", result.output)

        result = await backend.list_files("/workspace")
        check("backend list_files", result.success, result.data)

        result = await backend.mkdir("/workspace/sub")
        check("backend mkdir", result.success, result.error)

        # Read missing file
        result = await backend.read_file("/no/such/file")
        check("backend read missing", not result.success, result.error)

        # Reset
        old_id = backend.sandbox_id
        result = await backend.reset()
        check("backend reset", result.success and backend.sandbox_id != old_id,
              f"old={old_id} new={backend.sandbox_id}")

    # --- LLM Agent with Tools ---
    print("\n--- LLM Agent (GPT-5-mini) ---")
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage, AIMessage

            llm = ChatOpenAI(model="gpt-5-mini", temperature=0, api_key=api_key)

            agent_toolkit = AgentBoxToolkit(base_url=ORCHESTRATOR_URL)
            agent_tools = agent_toolkit.get_tools()
            llm_with_tools = llm.bind_tools(agent_tools)

            # Ask the LLM to write and execute code
            messages = [
                HumanMessage(content="Calculate the first 10 Fibonacci numbers using Python code. Use the execute_code tool.")
            ]
            response = await llm_with_tools.ainvoke(messages)
            check("llm returned tool call", len(response.tool_calls) > 0,
                  f"tool_calls={response.tool_calls}")

            if response.tool_calls:
                tc = response.tool_calls[0]
                check("llm chose execute_code", tc["name"] == "execute_code",
                      f"name={tc['name']}")

                # Execute the tool call
                code_tool_for_agent = agent_tools[0]  # execute_code
                tool_output = await code_tool_for_agent._arun(**tc["args"])
                check("tool produced fibonacci output",
                      "1" in tool_output and ("13" in tool_output or "21" in tool_output),
                      tool_output[:200])
                print(f"      LLM code output: {tool_output[:150]}")

            await agent_toolkit.cleanup()

        except Exception as e:
            check("llm agent", False, str(e))
    else:
        print("  (skipping LLM test — no OPENAI_API_KEY in .env)")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"LANGCHAIN: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
