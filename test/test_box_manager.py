"""
Test BoxManager: create/get/list/destroy sandboxes,
run code/shell through manager, metrics, reaper.
"""

import asyncio
import os
from agentbox.manager.box_manager import BoxManager, SandboxState


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
    print("TEST: BoxManager")
    print("=" * 60)

    # Use short timeouts for testing
    os.environ["AGENTBOX_MAX_SANDBOXES"] = "3"
    os.environ["AGENTBOX_IDLE_TIMEOUT"] = "9999"
    os.environ["AGENTBOX_MAX_LIFETIME"] = "9999"
    os.environ["AGENTBOX_REAPER_INTERVAL"] = "9999"

    async with BoxManager() as mgr:

        # --- create ---
        print("\n--- create sandbox ---")
        info = await mgr.create_sandbox(sandbox_id="test-1")
        check("create returns dict", isinstance(info, dict))
        check("sandbox_id matches", info["sandbox_id"] == "test-1")
        check("state is ready", info["state"] == "ready")

        # --- get ---
        print("\n--- get sandbox ---")
        info2 = await mgr.get_sandbox("test-1")
        check("get returns dict", info2 is not None)
        check("get sandbox_id", info2["sandbox_id"] == "test-1")

        missing = await mgr.get_sandbox("nonexistent")
        check("get missing returns None", missing is None)

        # --- list ---
        print("\n--- list sandboxes ---")
        lst = await mgr.list_sandboxes()
        check("list has 1 sandbox", len(lst) == 1)

        # --- run_code through manager ---
        print("\n--- run_code ---")
        r = await mgr.run_code("test-1", "print('manager hello')")
        check("run_code success", r["exit_code"] == 0)
        check("run_code stdout", r["stdout"] == "manager hello\n")

        r = await mgr.run_code("test-1", "1/0")
        check("run_code error", r["exit_code"] == 1)
        check("run_code stderr", "ZeroDivisionError" in r["stderr"])

        # --- run_shell through manager ---
        print("\n--- run_shell ---")
        r = await mgr.run_shell("test-1", "echo shell works")
        check("run_shell success", r["exit_code"] == 0)
        check("run_shell stdout", r["stdout"] == "shell works\n")

        # --- file ops through manager ---
        print("\n--- file ops ---")
        wrote = await mgr.write_file("test-1", "/mgr.txt", "managed content\n")
        check("write_file", wrote)

        content = await mgr.read_file("test-1", "/mgr.txt")
        check("read_file", content == "managed content\n")

        # --- state tracking ---
        print("\n--- state tracking ---")
        info3 = await mgr.get_sandbox("test-1")
        check("state back to ready after execution", info3["state"] == "ready")

        # --- duplicate ID ---
        print("\n--- error cases ---")
        try:
            await mgr.create_sandbox(sandbox_id="test-1")
            check("duplicate ID raises", False, "should have raised ValueError")
        except ValueError:
            check("duplicate ID raises ValueError", True)

        # --- capacity limit ---
        await mgr.create_sandbox(sandbox_id="test-2")
        await mgr.create_sandbox(sandbox_id="test-3")
        try:
            await mgr.create_sandbox(sandbox_id="test-4")
            check("capacity limit raises", False, "should have raised RuntimeError")
        except RuntimeError:
            check("capacity limit raises RuntimeError", True)

        # --- unknown sandbox ---
        try:
            await mgr.run_code("nonexistent", "print('hi')")
            check("unknown sandbox raises", False)
        except KeyError:
            check("unknown sandbox raises KeyError", True)

        # --- metrics ---
        print("\n--- metrics ---")
        m = mgr.metrics()
        check("metrics total", m["total"] == 3)
        check("metrics available", m["available"] == 0)
        check("metrics by_state ready", m["by_state"].get("ready") == 3)

        # --- destroy ---
        print("\n--- destroy ---")
        destroyed = await mgr.destroy_sandbox("test-2")
        check("destroy returns True", destroyed)

        destroyed2 = await mgr.destroy_sandbox("nonexistent")
        check("destroy missing returns False", not destroyed2)

        lst2 = await mgr.list_sandboxes()
        check("list after destroy has 2", len(lst2) == 2)

        m2 = mgr.metrics()
        check("metrics after destroy", m2["total"] == 2 and m2["available"] == 1)

        # --- persistent state across manager calls ---
        print("\n--- persistent state ---")
        await mgr.run_code("test-1", "x = 99")
        r = await mgr.run_code("test-1", "print(x)")
        check("state persists across run_code", r["stdout"] == "99\n")

        await mgr.run_shell("test-1", "echo data > /persist.txt")
        r = await mgr.run_shell("test-1", "cat /persist.txt")
        check("state persists across run_shell", r["stdout"] == "data\n")

    # --- After stop, all sandboxes destroyed ---
    print("\n--- after stop ---")
    check("manager cleaned up all sandboxes", len(mgr._sandboxes) == 0)

    # --- Reaper test ---
    print("\n--- reaper ---")
    os.environ["AGENTBOX_IDLE_TIMEOUT"] = "1"
    os.environ["AGENTBOX_REAPER_INTERVAL"] = "1"

    async with BoxManager() as mgr2:
        await mgr2.create_sandbox(sandbox_id="reap-me")
        check("sandbox exists before reap", len(mgr2._sandboxes) == 1)

        # Wait for reaper to run (idle timeout=1s, interval=1s)
        await asyncio.sleep(3)
        check("reaper destroyed idle sandbox", len(mgr2._sandboxes) == 0)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
