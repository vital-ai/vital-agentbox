"""
Live integration tests for AgentCoreEngine + AgentCoreBox.

Requires AWS credentials with access to Bedrock AgentCore Code Interpreter.
Set AWS_PROFILE or AWS credentials env vars before running.

Usage:
    AWS_PROFILE=cardiffprod python test/test_agentcore_live.py
"""

import asyncio
import os
import sys


async def main():
    passed = 0
    failed = 0
    skipped = 0

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

    def skip(name, reason=""):
        nonlocal skipped
        skipped += 1
        print(f"  ⊘ {name} (skipped: {reason})")

    # Import after env setup
    from agentbox.engine.agentcore_engine import AgentCoreEngine
    from agentbox.box.agentcore_box import AgentCoreBox

    # =====================================================================
    print("=" * 60)
    print("LIVE TEST: AgentCoreEngine basic lifecycle")
    print("=" * 60)

    engine = AgentCoreEngine(region="us-east-1", timeout=60)

    print("\n--- start session ---")
    try:
        await engine.start()
        check("engine started", engine.started)
        check("session_id assigned", engine.session_id is not None,
              f"session_id={engine.session_id}")
        check("engine_type is agentcore", engine.engine_type == "agentcore")
    except Exception as e:
        check("engine started", False, f"Exception: {e}")
        print("\nFATAL: Cannot start AgentCore session. Aborting.")
        print(f"  Error: {e}")
        return False

    # =====================================================================
    print("\n" + "=" * 60)
    print("LIVE TEST: Code execution")
    print("=" * 60)

    print("\n--- Python hello world ---")
    result = await engine.execute("print('hello from agentcore')")
    check("execute returns dict", isinstance(result, dict))
    check("exit_code is 0", result.get("exit_code") == 0,
          f"result={result}")
    check("stdout has hello", "hello from agentcore" in result.get("stdout", ""),
          f"stdout={result.get('stdout')!r}")
    print(f"    stdout: {result.get('stdout', '').strip()}")
    print(f"    stderr: {result.get('stderr', '').strip()}")

    print("\n--- Python math ---")
    result = await engine.execute("import math; print(math.pi)")
    check("math.pi", "3.14159" in result.get("stdout", ""),
          f"stdout={result.get('stdout')!r}")

    print("\n--- Python error ---")
    result = await engine.execute("raise ValueError('test error')")
    check("error exit_code != 0", result.get("exit_code") != 0,
          f"exit_code={result.get('exit_code')}")
    # Traceback may appear in stderr or stdout depending on SDK version
    combined = result.get("stderr", "") + result.get("stdout", "")
    check("output has ValueError", "ValueError" in combined,
          f"stderr={result.get('stderr')!r}, stdout={result.get('stdout')!r}")

    print("\n--- Multi-line code ---")
    result = await engine.execute("""
def fibonacci(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a

print(fibonacci(10))
""")
    check("fibonacci(10) = 55", "55" in result.get("stdout", ""),
          f"stdout={result.get('stdout')!r}")

    # =====================================================================
    print("\n" + "=" * 60)
    print("LIVE TEST: Shell execution")
    print("=" * 60)

    print("\n--- echo ---")
    result = await engine.execute_shell("echo 'hello bash'")
    check("shell echo", "hello bash" in result.get("stdout", ""),
          f"stdout={result.get('stdout')!r}")

    print("\n--- ls ---")
    result = await engine.execute_shell("ls /")
    check("ls / has output", len(result.get("stdout", "")) > 0,
          f"stdout={result.get('stdout')!r}")
    check("ls / has common dirs", any(d in result.get("stdout", "") for d in ["usr", "tmp", "home", "etc"]),
          f"stdout={result.get('stdout')!r}")

    print("\n--- python path ---")
    result = await engine.execute_shell("command -v python3 || command -v python")
    check("python found", result.get("exit_code") == 0,
          f"result={result}")

    print("\n--- pip ---")
    result = await engine.execute_shell("pip --version")
    check("pip available", result.get("exit_code") == 0,
          f"result={result}")

    print("\n--- uname ---")
    result = await engine.execute_shell("uname -a")
    check("uname works", result.get("exit_code") == 0)
    print(f"    {result.get('stdout', '').strip()}")

    # =====================================================================
    print("\n" + "=" * 60)
    print("LIVE TEST: File operations")
    print("=" * 60)

    print("\n--- write file ---")
    wrote = await engine.write_file("test_agentcore.txt", "hello from agentbox\nline 2\n")
    check("write_file returns True", wrote is True, f"got {wrote!r}")

    print("\n--- read file ---")
    content = await engine.read_file("test_agentcore.txt")
    check("read_file returns content", content is not None,
          f"got {content!r}")
    check("content matches", content is not None and "hello from agentbox" in content,
          f"content={content!r}")

    print("\n--- list files (cwd) ---")
    result_ls = await engine.execute_shell("ls -1")
    files_cwd = [f.strip() for f in result_ls["stdout"].strip().split("\n") if f.strip()]
    check("test file in cwd", any("test_agentcore" in f for f in files_cwd),
          f"files={files_cwd[:10]}")

    print("\n--- list files (ls /tmp) ---")
    files = await engine.list_files("/tmp")
    check("list_files returns list", isinstance(files, list))
    check("list_files has entries", len(files) > 0,
          f"files={files[:10]}")

    print("\n--- read missing file ---")
    content = await engine.read_file("nonexistent_file_xyz.txt")
    check("missing file returns None", content is None,
          f"got {content!r}")

    # =====================================================================
    print("\n" + "=" * 60)
    print("LIVE TEST: Stop session")
    print("=" * 60)

    await engine.stop()
    check("engine stopped", not engine.started)
    check("session_id cleared", engine.session_id is None)

    # =====================================================================
    print("\n" + "=" * 60)
    print("LIVE TEST: AgentCoreBox (high-level)")
    print("=" * 60)

    print("\n--- box lifecycle ---")
    async with AgentCoreBox(timeout=60, region="us-east-1") as box:
        check("box started", box._started)

        print("\n--- box run_code ---")
        result = await box.run_code("print('box works!')")
        check("run_code ok", result["exit_code"] == 0,
              f"result={result}")
        check("stdout", "box works!" in result["stdout"],
              f"stdout={result['stdout']!r}")

        print("\n--- box run_shell ---")
        result = await box.run_shell("echo 'shell works'")
        check("run_shell ok", result["exit_code"] == 0)
        check("stdout", "shell works" in result["stdout"])

        print("\n--- box read/write file ---")
        await box.write_file("/workspace/test.py", "print('from file')\n")
        content = await box.read_file("/workspace/test.py")
        check("file roundtrip", content is not None and "from file" in content,
              f"content={content!r}")

        print("\n--- box edit intercept ---")
        result = await box.run_shell("edit /workspace/test.py --view")
        check("edit intercepted", result["exit_code"] == 0,
              f"stderr={result['stderr']!r}")
        check("edit shows content", "from file" in result["stdout"],
              f"stdout={result['stdout']!r}")

        print("\n--- box edit str_replace ---")
        result = await box.run_shell(
            "edit /workspace/test.py --old \"print('from file')\" --new \"print('edited!')\""
        )
        check("str_replace ok", result["exit_code"] == 0,
              f"stderr={result['stderr']!r}")

        # Verify the edit was applied
        content = await box.read_file("/workspace/test.py")
        check("edit applied", content is not None and "edited!" in content,
              f"content={content!r}")

        # Run the edited file
        result = await box.run_code(content)
        check("edited code runs", "edited!" in result["stdout"],
              f"stdout={result['stdout']!r}")

        print("\n--- pip install in session ---")
        result = await box.run_shell("pip install requests -q 2>&1 | tail -1")
        check("pip install ok", result["exit_code"] == 0,
              f"stderr={result['stderr']!r}")

        result = await box.run_code("import requests; print(requests.__version__)")
        check("requests importable", result["exit_code"] == 0,
              f"result={result}")
        print(f"    requests version: {result.get('stdout', '').strip()}")

    check("box stopped after context manager", not box._started)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"LIVE RESULTS: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    print(f"{'=' * 60}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
