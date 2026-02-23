"""
Test the tree-sitter-bash ShellExecutor against a live MemFS instance.
"""

import asyncio


PYODIDE_CDN = "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/pyodide.js"


async def setup():
    from playwright.async_api import async_playwright
    from agentbox.box.memfs.memfs import MemFS
    from agentbox.box.shell import ShellExecutor

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()

    await page.goto(f'data:text/html,<script src="{PYODIDE_CDN}"></script>')
    await page.evaluate("async () => { window.pyodide = await loadPyodide(); }")

    memfs = MemFS(page)
    executor = ShellExecutor(memfs)
    return pw, browser, executor


async def main():
    pw, browser, sh = await setup()
    passed = 0
    failed = 0

    async def test(name, cmd, expect_stdout=None, expect_exit=0, expect_stderr_contains=None):
        nonlocal passed, failed
        r = await sh.run(cmd)
        ok = True
        issues = []

        if expect_exit is not None and r.exit_code != expect_exit:
            ok = False
            issues.append(f"exit_code={r.exit_code}, expected {expect_exit}")
        if expect_stdout is not None and r.stdout != expect_stdout:
            ok = False
            issues.append(f"stdout={r.stdout!r}, expected {expect_stdout!r}")
        if expect_stderr_contains and expect_stderr_contains not in r.stderr:
            ok = False
            issues.append(f"stderr={r.stderr!r}, expected to contain {expect_stderr_contains!r}")

        if ok:
            passed += 1
            print(f"  ✓ {name}")
        else:
            failed += 1
            print(f"  ✗ {name}")
            for issue in issues:
                print(f"      {issue}")
            if r.stderr:
                print(f"      stderr: {r.stderr!r}")

    print("=" * 60)
    print("TEST: ShellExecutor (tree-sitter-bash + MemFS)")
    print("=" * 60)

    # --- echo ---
    print("\n--- echo ---")
    await test("echo basic", "echo hello", expect_stdout="hello\n")
    await test("echo multi-word", "echo hello world", expect_stdout="hello world\n")
    await test("echo -n", "echo -n hello", expect_stdout="hello")
    await test("echo empty", "echo", expect_stdout="\n")

    # --- mkdir + ls ---
    print("\n--- mkdir + ls ---")
    await test("mkdir", "mkdir /testdir", expect_exit=0)
    await test("mkdir -p nested", "mkdir -p /a/b/c", expect_exit=0)

    # --- write via redirect ---
    print("\n--- write via redirect ---")
    await test("echo > file",
               'echo "hello world" > /testdir/hello.txt',
               expect_exit=0)
    await test("echo >> file (append)",
               'echo " appended" >> /testdir/hello.txt',
               expect_exit=0)

    # --- cat ---
    print("\n--- cat ---")
    await test("cat file",
               "cat /testdir/hello.txt",
               expect_stdout="hello world\n appended\n")

    # --- cp ---
    print("\n--- cp ---")
    await test("cp file",
               "cp /testdir/hello.txt /testdir/copy.txt",
               expect_exit=0)
    await test("cat copied file",
               "cat /testdir/copy.txt",
               expect_stdout="hello world\n appended\n")

    # --- mv ---
    print("\n--- mv ---")
    await test("mv file",
               "mv /testdir/copy.txt /testdir/moved.txt",
               expect_exit=0)
    await test("cat moved file",
               "cat /testdir/moved.txt",
               expect_stdout="hello world\n appended\n")
    await test("cat old path gone",
               "cat /testdir/copy.txt",
               expect_exit=1,
               expect_stderr_contains="No such file")

    # --- rm ---
    print("\n--- rm ---")
    await test("rm file",
               "rm /testdir/moved.txt",
               expect_exit=0)
    await test("cat removed file",
               "cat /testdir/moved.txt",
               expect_exit=1,
               expect_stderr_contains="No such file")

    # --- pwd + cd ---
    print("\n--- pwd + cd ---")
    await test("pwd default", "pwd", expect_stdout="/\n")
    await test("cd /testdir", "cd /testdir", expect_exit=0)
    await test("pwd after cd", "pwd", expect_stdout="/testdir\n")
    await test("cd /", "cd /", expect_exit=0)

    # --- pipes ---
    print("\n--- pipes ---")
    await test("echo | cat",
               "echo hello | cat",
               expect_stdout="hello\n")
    await test("echo | grep",
               'echo "hello world" | grep hello',
               expect_stdout="hello world\n")
    await test("echo | grep no match",
               'echo "hello" | grep xyz',
               expect_exit=1)
    await test("echo | wc -l",
               'echo "hello" | wc -l',
               expect_stdout="1\n")

    # --- && and || ---
    print("\n--- && and || ---")
    await test("true && echo",
               "true && echo yes",
               expect_stdout="yes\n")
    await test("false && echo",
               "false && echo yes",
               expect_stdout="",
               expect_exit=1)
    await test("false || echo",
               "false || echo fallback",
               expect_stdout="fallback\n")
    await test("true || echo",
               "true || echo fallback",
               expect_stdout="")

    # --- chaining: mkdir && echo > file && cat ---
    print("\n--- chaining ---")
    await test("chained commands",
               'mkdir -p /chain && echo "chained" > /chain/test.txt && cat /chain/test.txt',
               expect_stdout="chained\n")

    # --- variables ---
    print("\n--- variables ---")
    await test("export + echo",
               'export FOO=bar && echo $FOO',
               expect_stdout="bar\n")

    # --- wc ---
    print("\n--- wc ---")
    r = await sh.run('echo "one two three" > /wc_test.txt')
    await test("wc -w",
               "wc -w /wc_test.txt",
               expect_stdout="3 /wc_test.txt\n")

    # --- head / tail ---
    print("\n--- head / tail ---")
    # Write multi-line file
    await sh.run('echo "line1" > /lines.txt')
    await sh.run('echo "line2" >> /lines.txt')
    await sh.run('echo "line3" >> /lines.txt')
    await sh.run('echo "line4" >> /lines.txt')
    await sh.run('echo "line5" >> /lines.txt')
    await test("head -n 2",
               "head -n 2 /lines.txt",
               expect_stdout="line1\nline2\n")
    await test("tail -n 2",
               "tail -n 2 /lines.txt",
               expect_stdout="line4\nline5\n")

    # --- touch ---
    print("\n--- touch ---")
    await test("touch new file",
               "touch /touched.txt",
               expect_exit=0)
    await test("cat touched file",
               "cat /touched.txt",
               expect_stdout="")

    # --- command not found ---
    print("\n--- command not found ---")
    await test("unknown command",
               "nonexistent_cmd",
               expect_exit=127,
               expect_stderr_contains="command not found")

    # --- error handling ---
    print("\n--- error handling ---")
    await test("cat nonexistent || echo fallback",
               "cat /nonexistent || echo fallback",
               expect_stdout="fallback\n")

    # --- Tier 2: python/python3 via Pyodide ---
    print("\n--- python (Tier 2: Pyodide) ---")
    await test("python -c inline",
               'python -c "print(2 + 2)"',
               expect_stdout="4\n")
    await test("python3 -c inline",
               'python3 -c "print(\'hello from python3\')"',
               expect_stdout="hello from python3\n")

    # python script.py from MemFS
    await sh.run('echo "import sys" > /test_script.py')
    await sh.run('echo "print(sys.argv)" >> /test_script.py')
    await test("python script.py",
               "python /test_script.py",
               expect_stdout="['python']\n")
    await test("python script.py with args",
               "python /test_script.py foo bar",
               expect_stdout="['python', 'foo', 'bar']\n")

    # python reading from stdin (pipe)
    await test("echo | python (pipe)",
               'echo "print(42)" | python',
               expect_stdout="42\n")

    # python error handling
    await test("python syntax error",
               'python -c "def"',
               expect_exit=1,
               expect_stderr_contains="SyntaxError")

    # python nonexistent script
    await test("python missing script",
               "python /nonexistent_script.py",
               expect_exit=2,
               expect_stderr_contains="No such file")

    # python with MemFS interaction (read/write files from Python)
    await sh.run('echo "test content" > /pydata.txt')
    await test("python reads MemFS file",
               'python -c "f = open(\'/pydata.txt\'); print(f.read().strip()); f.close()"',
               expect_stdout="test content\n")

    await test("python writes MemFS file",
               'python -c "f = open(\'/pyout.txt\', \'w\'); f.write(\'from python\\n\'); f.close(); print(\'wrote\')"',
               expect_stdout="wrote\n")
    await test("cat python-written file",
               "cat /pyout.txt",
               expect_stdout="from python\n")

    # python with shell pipe chain
    await test("python in pipe chain",
               'echo "3 + 4" | python -c "import sys; expr = sys.stdin.read().strip(); print(eval(expr))"',
               expect_stdout="7\n")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    await browser.close()
    await pw.stop()

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
