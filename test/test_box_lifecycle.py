"""
Test CodeExecutorBox lifecycle: start/stop, run_code, run_shell,
read_file, write_file, context manager, messaging bridge.
"""

import asyncio
from agentbox.box.code_exec_box import CodeExecutorBox


async def main():
    passed = 0
    failed = 0

    async def test(name, coro, expect_exit=0, expect_stdout=None, expect_stderr_contains=None):
        nonlocal passed, failed
        r = await coro
        ok = True
        issues = []

        if expect_exit is not None and r.get("exit_code") != expect_exit:
            ok = False
            issues.append(f"exit_code={r.get('exit_code')}, expected {expect_exit}")
        if expect_stdout is not None and r.get("stdout") != expect_stdout:
            ok = False
            issues.append(f"stdout={r.get('stdout')!r}, expected {expect_stdout!r}")
        if expect_stderr_contains and expect_stderr_contains not in r.get("stderr", ""):
            ok = False
            issues.append(f"stderr missing {expect_stderr_contains!r}")

        if ok:
            passed += 1
            print(f"  ✓ {name}")
        else:
            failed += 1
            print(f"  ✗ {name}")
            for issue in issues:
                print(f"      {issue}")

    print("=" * 60)
    print("TEST: CodeExecutorBox Lifecycle")
    print("=" * 60)

    # --- Context manager ---
    print("\n--- context manager + run_code ---")
    async with CodeExecutorBox() as box:
        await test("run_code: print",
                    box.run_code("print('hello')"),
                    expect_stdout="hello\n")

        await test("run_code: math",
                    box.run_code("print(2 ** 10)"),
                    expect_stdout="1024\n")

        await test("run_code: error",
                    box.run_code("1/0"),
                    expect_exit=1,
                    expect_stderr_contains="ZeroDivisionError")

        await test("run_code: unsupported language",
                    box.run_code("console.log('hi')", language="javascript"),
                    expect_exit=1,
                    expect_stderr_contains="Unsupported language")

        # --- run_shell ---
        print("\n--- run_shell ---")
        await test("run_shell: echo",
                    box.run_shell('echo hello'),
                    expect_stdout="hello\n")

        await test("run_shell: mkdir + ls",
                    box.run_shell('mkdir /workspace && echo done'),
                    expect_stdout="done\n")

        await test("run_shell: pipe",
                    box.run_shell('echo "hello world" | grep world'),
                    expect_stdout="hello world\n")

        # --- read_file / write_file ---
        print("\n--- read_file / write_file ---")
        wrote = await box.write_file("/test.txt", "file content\n")
        if wrote:
            passed += 1
            print("  ✓ write_file")
        else:
            failed += 1
            print("  ✗ write_file")

        content = await box.read_file("/test.txt")
        if content == "file content\n":
            passed += 1
            print("  ✓ read_file")
        else:
            failed += 1
            print(f"  ✗ read_file: got {content!r}")

        missing = await box.read_file("/nonexistent.txt")
        if missing is None:
            passed += 1
            print("  ✓ read_file returns None for missing")
        else:
            failed += 1
            print(f"  ✗ read_file missing: got {missing!r}")

        # --- cross-boundary: shell writes, python reads ---
        print("\n--- cross-boundary ---")
        await box.run_shell('echo "from shell" > /cross.txt')
        await test("python reads shell-written file",
                    box.run_code("print(open('/cross.txt').read().strip())"),
                    expect_stdout="from shell\n")

        await box.run_code("open('/from_py.txt', 'w').write('from python\\n')")
        await test("shell reads python-written file",
                    box.run_shell("cat /from_py.txt"),
                    expect_stdout="from python\n")

        # --- persistent state across calls ---
        print("\n--- persistent state ---")
        await box.run_code("x = 42")
        await test("variable persists across run_code calls",
                    box.run_code("print(x)"),
                    expect_stdout="42\n")

        await box.run_shell("export MYVAR=hello")
        await test("shell env persists across run_shell calls",
                    box.run_shell("echo $MYVAR"),
                    expect_stdout="hello\n")

    # --- Verify stopped ---
    print("\n--- lifecycle ---")
    try:
        await box.run_code("print('should fail')")
        failed += 1
        print("  ✗ should raise after stop")
    except RuntimeError:
        passed += 1
        print("  ✓ raises RuntimeError after stop")

    # --- Custom message handler ---
    print("\n--- message handler ---")
    received = []

    async def custom_handler(msg):
        received.append(msg)
        return {"status": "ok", "echo": msg}

    async with CodeExecutorBox(message_handler=custom_handler) as box:
        r = await box.run_code("""
import json
reply = await messaging.send({"test": "ping"})
print(json.dumps(reply))
""")
        if r["exit_code"] == 0 and '"status": "ok"' in r["stdout"]:
            passed += 1
            print("  ✓ custom message handler called")
        else:
            failed += 1
            print(f"  ✗ message handler: {r}")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
