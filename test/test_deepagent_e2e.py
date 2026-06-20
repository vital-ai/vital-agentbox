"""End-to-end test: create_deep_agent(backend=AgentBoxSandbox(...)).

Requires:
    - docker-compose stack running (orchestrator at localhost:8090)
    - ANTHROPIC_API_KEY in .env

Usage:
    python test/test_deepagent_e2e.py
"""

import os
import sys

from dotenv import load_dotenv
load_dotenv()

from agentbox.langchain import AgentBoxSandbox
from deepagents import create_deep_agent
from langchain_anthropic import ChatAnthropic


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set, skipping")
        return True

    print("=" * 60)
    print("DEEP AGENT END-TO-END TEST")
    print("=" * 60)

    sandbox = AgentBoxSandbox(base_url="http://localhost:8090")

    model = ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=api_key,
    )
    agent = create_deep_agent(
        model=model,
        backend=sandbox,
        system_prompt="You are a helpful coding assistant. Use your sandbox to execute code when asked.",
        name="agentbox-e2e-test",
    )

    print(f"\nSandbox: {sandbox}")

    # --- Test 1: Code execution ---
    print("\n--- Test 1: Calculate 20th Fibonacci number ---")
    result = agent.invoke({
        "messages": [
            {"role": "user", "content": "Calculate the 20th Fibonacci number using Python."}
        ],
    })

    messages = result.get("messages", [])
    print(f"Messages: {len(messages)} total")
    for msg in messages:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", "")
        tool_calls = getattr(msg, "tool_calls", [])
        if role == "ai" and tool_calls:
            for tc in tool_calls:
                print(f"  [{role}] tool_call: {tc['name']}({list(tc['args'].keys())})")
        elif role == "tool":
            print(f"  [{role}] {content[:150]}")
        elif role == "ai":
            print(f"  [{role}] {content[:200]}")
        elif role == "human":
            print(f"  [{role}] {content[:100]}")

    final = messages[-1] if messages else None
    final_content = getattr(final, "content", "")
    test1_pass = "6765" in final_content
    print(f"\n{'PASS' if test1_pass else 'FAIL'}: Final answer contains 6765: {test1_pass}")
    print(f"  Final: {final_content[:200]}")

    # --- Test 2: File operations ---
    print("\n--- Test 2: Write and read a file ---")
    result2 = agent.invoke({
        "messages": [
            {"role": "user", "content": "Write a Python file at /workspace/hello.py that prints 'Hello from AgentBox!', then execute it and show the output."}
        ],
    })

    messages2 = result2.get("messages", [])
    print(f"Messages: {len(messages2)} total")
    for msg in messages2:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", "")
        tool_calls = getattr(msg, "tool_calls", [])
        if role == "ai" and tool_calls:
            for tc in tool_calls:
                print(f"  [{role}] tool_call: {tc['name']}({list(tc['args'].keys())})")
        elif role == "tool":
            print(f"  [{role}] {content[:150]}")
        elif role == "ai":
            print(f"  [{role}] {content[:200]}")
        elif role == "human":
            print(f"  [{role}] {content[:100]}")

    final2 = messages2[-1] if messages2 else None
    final_content2 = getattr(final2, "content", "")
    test2_pass = "Hello from AgentBox" in final_content2 or "hello" in final_content2.lower()
    print(f"\n{'PASS' if test2_pass else 'FAIL'}: File write + execute worked: {test2_pass}")
    print(f"  Final: {final_content2[:200]}")

    # Cleanup
    sandbox.close()
    print(f"\nSandbox cleaned up.")

    all_pass = test1_pass and test2_pass
    print(f"\n{'=' * 60}")
    print(f"RESULT: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    print(f"{'=' * 60}")
    return all_pass


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
