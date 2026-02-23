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
    await test("pwd default", "pwd", expect_stdout=sh.env.cwd + "\n")
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

    # --- glob expansion ---
    print("\n--- glob expansion ---")
    await sh.run("mkdir -p /globtest/sub")
    await sh.run("echo a > /globtest/alpha.txt")
    await sh.run("echo b > /globtest/beta.md")
    await sh.run("echo c > /globtest/gamma.txt")
    await sh.run("echo d > /globtest/sub/deep.txt")

    await test("echo glob *",
               "echo /globtest/*.txt",
               expect_stdout="/globtest/alpha.txt /globtest/gamma.txt\n")
    await test("echo glob all",
               "echo /globtest/*",
               expect_stdout="/globtest/alpha.txt /globtest/beta.md /globtest/gamma.txt /globtest/sub\n")
    await test("ls glob *.md",
               "ls /globtest/*.md",
               expect_stdout="/globtest/beta.md\n")
    await test("ls glob multi files",
               "ls /globtest/*.txt",
               expect_stdout="/globtest/alpha.txt\n/globtest/gamma.txt\n")
    await test("cat glob",
               "cat /globtest/alpha.txt /globtest/gamma.txt",
               expect_stdout="a\nc\n")

    # Relative glob
    await sh.run("cd /globtest")
    await test("relative glob",
               "echo *.txt",
               expect_stdout="alpha.txt gamma.txt\n")
    await test("relative glob no match (literal kept)",
               "echo *.xyz",
               expect_stdout="*.xyz\n")
    await sh.run("cd /")

    # Quoted glob should NOT expand
    await test("quoted glob no expand (double)",
               'echo "/globtest/*.txt"',
               expect_stdout="/globtest/*.txt\n")
    await test("quoted glob no expand (single)",
               "echo '/globtest/*.txt'",
               expect_stdout="/globtest/*.txt\n")

    # ? wildcard
    await test("? wildcard",
               "echo /globtest/?????.txt",
               expect_stdout="/globtest/alpha.txt /globtest/gamma.txt\n")

    # --- heredoc + redirect ---
    print("\n--- heredoc + redirect ---")
    await test("heredoc to file",
               "cat << 'EOF' > /heredoc_test.txt\nline one\nline two\nEOF",
               expect_exit=0)
    await test("cat heredoc file",
               "cat /heredoc_test.txt",
               expect_stdout="line one\nline two\n")

    # --- date ---
    print("\n--- date ---")
    r = await sh.run("date")
    assert r.exit_code == 0 and len(r.stdout.strip()) > 10
    passed += 1
    print(f"  ✓ date default: {r.stdout.strip()}")

    await test("date +%Y",
               "date +%Y",
               expect_exit=0)

    await test("date -u format",
               "date -u +%Z",
               expect_stdout="UTC\n")

    await test("date --help",
               "date --help",
               expect_exit=0)

    # --- sort ---
    print("\n--- sort ---")
    await sh.run('echo "banana\napple\ncherry" > /sort_test.txt')
    await test("sort basic",
               "sort /sort_test.txt",
               expect_stdout="apple\nbanana\ncherry\n")
    await test("sort -r",
               "sort -r /sort_test.txt",
               expect_stdout="cherry\nbanana\napple\n")
    await test("sort stdin",
               'echo "3\n1\n2" | sort -n',
               expect_stdout="1\n2\n3\n")
    await test("sort -u",
               'echo "a\nb\na\nc\nb" | sort -u',
               expect_stdout="a\nb\nc\n")

    # --- uniq ---
    print("\n--- uniq ---")
    await test("uniq basic",
               'echo "a\na\nb\nb\nb\nc" | uniq',
               expect_stdout="a\nb\nc\n")
    await test("uniq -c",
               'echo "a\na\nb\nb\nb\nc" | uniq -c',
               expect_stdout="   2 a\n   3 b\n   1 c\n")
    await test("uniq -d",
               'echo "a\na\nb\nc" | uniq -d',
               expect_stdout="a\n")

    # --- cut ---
    print("\n--- cut ---")
    await sh.run('echo "one:two:three\nfour:five:six" > /cut_test.txt')
    await test("cut -d: -f2",
               "cut -d : -f 2 /cut_test.txt",
               expect_stdout="two\nfive\n")
    await test("cut -f1,3",
               "cut -d : -f 1,3 /cut_test.txt",
               expect_stdout="one:three\nfour:six\n")
    await test("cut stdin",
               'echo "hello world" | cut -c 1-5',
               expect_stdout="hello\n")

    # --- tr ---
    print("\n--- tr ---")
    await test("tr translate",
               'echo "hello" | tr a-z A-Z',
               expect_stdout="HELLO\n")
    await test("tr delete",
               'echo "hello world" | tr -d " "',
               expect_stdout="helloworld\n")
    await test("tr squeeze",
               'echo "aabbcc" | tr -s a-c',
               expect_stdout="abc\n")

    # --- diff ---
    print("\n--- diff ---")
    await sh.run('echo "line1\nline2\nline3" > /diff_a.txt')
    await sh.run('echo "line1\nchanged\nline3" > /diff_b.txt')
    await test("diff identical",
               "diff /diff_a.txt /diff_a.txt",
               expect_stdout="",
               expect_exit=0)
    await test("diff different",
               "diff /diff_a.txt /diff_b.txt",
               expect_exit=1)
    await test("diff --brief",
               "diff --brief /diff_a.txt /diff_b.txt",
               expect_stdout="Files /diff_a.txt and /diff_b.txt differ\n",
               expect_exit=1)

    # --- basename / dirname / realpath ---
    print("\n--- basename / dirname / realpath ---")
    await test("basename",
               "basename /foo/bar/baz.txt",
               expect_stdout="baz.txt\n")
    await test("basename with suffix",
               "basename /foo/bar/baz.txt .txt",
               expect_stdout="baz\n")
    await test("dirname",
               "dirname /foo/bar/baz.txt",
               expect_stdout="/foo/bar\n")
    await test("dirname multiple",
               "dirname /a/b.txt /c/d.txt",
               expect_stdout="/a\n/c\n")
    await test("realpath relative",
               "realpath /a/../b/./c",
               expect_stdout="/b/c\n")

    # --- xargs ---
    print("\n--- xargs ---")
    await test("xargs echo",
               'echo "a b c" | xargs echo',
               expect_stdout="a b c\n")

    # --- chmod / sleep (no-op) ---
    print("\n--- chmod / sleep (no-op) ---")
    await test("chmod no-op",
               "chmod 755 /sort_test.txt",
               expect_exit=0)
    await test("sleep no-op",
               "sleep 5",
               expect_exit=0)

    # --- curl / wget (blocked) ---
    print("\n--- curl / wget (blocked) ---")
    await test("curl blocked",
               "curl https://example.com",
               expect_exit=1,
               expect_stderr_contains="network access")
    await test("wget blocked",
               "wget https://example.com",
               expect_exit=1,
               expect_stderr_contains="network access")

    # --- seq ---
    print("\n--- seq ---")
    await test("seq 5",
               "seq 5",
               expect_stdout="1\n2\n3\n4\n5\n")
    await test("seq 2 5",
               "seq 2 5",
               expect_stdout="2\n3\n4\n5\n")
    await test("seq 1 2 7",
               "seq 1 2 7",
               expect_stdout="1\n3\n5\n7\n")

    # --- base64 ---
    print("\n--- base64 ---")
    await test("base64 encode",
               'echo "hello" | base64',
               expect_stdout="aGVsbG8K\n")
    await test("base64 decode",
               'echo "aGVsbG8=" | base64 -d',
               expect_stdout="hello")

    # --- md5sum / sha256sum ---
    print("\n--- md5sum / sha256sum ---")
    r = await sh.run("echo test | md5sum")
    assert r.exit_code == 0 and "  -" in r.stdout
    passed += 1
    print(f"  ✓ md5sum stdin: {r.stdout.strip()}")
    await test("md5sum file",
               "md5sum /sort_test.txt",
               expect_exit=0)
    await test("sha256sum file",
               "sha256sum /sort_test.txt",
               expect_exit=0)

    # --- nl ---
    print("\n--- nl ---")
    await test("nl basic",
               'echo "alpha\nbeta\ngamma" | nl',
               expect_stdout="     1\talpha\n     2\tbeta\n     3\tgamma\n")

    # --- rev ---
    print("\n--- rev ---")
    await test("rev basic",
               'echo "hello\nworld" | rev',
               expect_stdout="olleh\ndlrow\n")

    # --- cat -n ---
    print("\n--- cat -n ---")
    await test("cat -n",
               "cat -n /sort_test.txt",
               expect_stdout="     1\tbanana\n     2\tapple\n     3\tcherry\n")

    # --- du / df ---
    print("\n--- du / df ---")
    await test("df",
               "df",
               expect_exit=0)
    await test("df -h",
               "df -h",
               expect_exit=0)
    await test("du -s /sort_test.txt",
               "du -s /sort_test.txt",
               expect_exit=0)

    # --- uuidgen / mktemp ---
    print("\n--- uuidgen / mktemp ---")
    r = await sh.run("uuidgen")
    assert r.exit_code == 0 and len(r.stdout.strip()) == 36 and "-" in r.stdout
    passed += 1
    print(f"  ✓ uuidgen: {r.stdout.strip()}")

    r = await sh.run("mktemp")
    assert r.exit_code == 0 and r.stdout.strip().startswith("/tmp/")
    passed += 1
    print(f"  ✓ mktemp: {r.stdout.strip()}")

    r = await sh.run("mktemp -d")
    assert r.exit_code == 0 and r.stdout.strip().startswith("/tmp/")
    passed += 1
    print(f"  ✓ mktemp -d: {r.stdout.strip()}")

    # --- awk (host) ---
    print("\n--- awk (host) ---")
    await test("awk print field",
               'echo "one two three" | awk \'{print $2}\'',
               expect_stdout="two\n")
    await test("awk -F delimiter",
               'echo "a:b:c" | awk -F: \'{print $3}\'',
               expect_stdout="c\n")

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
