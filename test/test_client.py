"""Test AgentBoxClient against the running docker-compose stack.

Prerequisites:
    docker compose up --build -d
    Orchestrator at http://localhost:8090
"""

import asyncio
import sys

from agentbox.client import AgentBoxClient


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
    print("CLIENT SDK TEST")
    print("=" * 60)

    async with AgentBoxClient(ORCHESTRATOR_URL) as client:

        # --- Health ---
        print("\n--- Health ---")
        health = await client.health()
        check("health", health.get("status") == "healthy", health)

        # --- Metrics ---
        print("\n--- Metrics ---")
        metrics = await client.metrics()
        check("metrics", "workers_total" in metrics, metrics)

        # --- Workers ---
        print("\n--- Workers ---")
        workers = await client.list_workers()
        check("list workers", len(workers) >= 1, f"got {len(workers)}")

        # --- Create Sandbox ---
        print("\n--- Create Sandbox ---")
        sandbox = await client.create_sandbox()
        check("create sandbox", sandbox.sandbox_id is not None, sandbox)
        print(f"      sandbox_id = {sandbox.sandbox_id}")

        # --- Execute Python ---
        print("\n--- Execute Python ---")
        result = await sandbox.execute("print(7 * 6)")
        check("python stdout", "42" in result.stdout, result)
        check("python exit_code", result.exit_code == 0, result)

        # --- Multi-line Python ---
        result = await sandbox.execute("""
x = [i**2 for i in range(5)]
print(x)
""")
        check("python multi-line", "[0, 1, 4, 9, 16]" in result.stdout, result)

        # --- Execute Shell ---
        print("\n--- Execute Shell ---")
        result = await sandbox.execute("echo hello-client-sdk", language="shell")
        check("shell stdout", "hello-client-sdk" in result.stdout, result)

        # --- Shorthand methods ---
        result = await sandbox.run_python("print('py')")
        check("run_python", "py" in result.stdout, result)

        result = await sandbox.run_shell("echo sh")
        check("run_shell", "sh" in result.stdout, result)

        # --- File Operations ---
        print("\n--- File Operations ---")
        ok = await sandbox.mkdir("/workspace")
        check("mkdir", ok)

        ok = await sandbox.write_file("/workspace/hello.txt", "hello from SDK")
        check("write_file", ok)

        content = await sandbox.read_file("/workspace/hello.txt")
        check("read_file", content == "hello from SDK", f"got {content!r}")

        entries = await sandbox.list_files("/workspace")
        check("list_files", "hello.txt" in str(entries), f"got {entries}")

        # --- State Persistence ---
        print("\n--- State Persistence ---")
        await sandbox.execute("x = 999")
        result = await sandbox.execute("print(x)")
        check("python state persists", "999" in result.stdout, result)

        # --- Get Sandbox ---
        print("\n--- Get Sandbox ---")
        same = await client.get_sandbox(sandbox.sandbox_id)
        check("get_sandbox", same.sandbox_id == sandbox.sandbox_id)

        # --- List Sandboxes ---
        sandboxes = await client.list_sandboxes()
        check("list_sandboxes", any(s.sandbox_id == sandbox.sandbox_id for s in sandboxes),
              f"got {[s.sandbox_id for s in sandboxes]}")

        # --- Destroy ---
        print("\n--- Destroy ---")
        await sandbox.destroy()
        check("destroy", sandbox.state == "destroyed")

        # --- One-shot run ---
        print("\n--- One-shot run ---")
        result = await client.run("print('oneshot')")
        check("one-shot run", "oneshot" in result.stdout, result)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"CLIENT SDK: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
