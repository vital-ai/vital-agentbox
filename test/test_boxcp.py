"""
Test the boxcp host-delegated command against a live MemFS instance.

Tests MemFS ↔ local:// transfers and error handling.
S3 tests require MinIO (run via docker-compose).
"""

import asyncio
import os
import tempfile


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

    async def test(name, cmd, expect_stdout=None, expect_exit=0,
                   expect_stderr_contains=None, expect_stdout_contains=None):
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
        if expect_stdout_contains and expect_stdout_contains not in r.stdout:
            ok = False
            issues.append(f"stdout={r.stdout!r}, expected to contain {expect_stdout_contains!r}")
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
    print("TEST: boxcp (host-delegated file copy)")
    print("=" * 60)

    # Create a temp dir for local:// tests and allowlist it
    tmpdir = tempfile.mkdtemp(prefix="boxcp_test_")
    os.environ["AGENTBOX_BOXCP_LOCAL_ALLOW"] = tmpdir

    # Force reimport so the module picks up the new env var
    import agentbox.box.shell.host_commands.boxcp as boxcp_mod
    boxcp_mod.LOCAL_ALLOW = [tmpdir]

    # --- Usage / error handling ---
    print("\n--- error handling ---")
    await test("no args",
               "boxcp",
               expect_exit=1,
               expect_stderr_contains="Usage")

    await test("one arg",
               "boxcp /foo",
               expect_exit=1,
               expect_stderr_contains="Usage")

    await test("missing source file",
               f"boxcp /nonexistent local://{tmpdir}/out.txt",
               expect_exit=1,
               expect_stderr_contains="No such file")

    # --- MemFS to MemFS (basic copy via boxcp) ---
    print("\n--- memfs to memfs ---")
    await sh.run('echo "boxcp test data" > /boxcp_src.txt')

    await test("memfs → memfs",
               "boxcp /boxcp_src.txt /boxcp_dst.txt",
               expect_exit=0,
               expect_stdout_contains="bytes")

    await test("verify memfs copy",
               "cat /boxcp_dst.txt",
               expect_stdout="boxcp test data\n")

    # --- MemFS → local:// ---
    print("\n--- memfs → local ---")
    await sh.run('echo "export to host" > /export_me.txt')

    await test("memfs → local",
               f"boxcp /export_me.txt local://{tmpdir}/exported.txt",
               expect_exit=0,
               expect_stdout_contains="bytes")

    # Verify the file landed on the host
    host_path = os.path.join(tmpdir, "exported.txt")
    if os.path.isfile(host_path):
        content = open(host_path).read()
        if "export to host" in content:
            passed += 1
            print("  ✓ host file content verified")
        else:
            failed += 1
            print(f"  ✗ host file content: {content!r}")
    else:
        failed += 1
        print(f"  ✗ host file not found: {host_path}")

    # --- local:// → MemFS ---
    print("\n--- local → memfs ---")
    import_path = os.path.join(tmpdir, "import_me.txt")
    with open(import_path, "w") as f:
        f.write("imported from host\n")

    await test("local → memfs",
               f"boxcp local://{import_path} /imported.txt",
               expect_exit=0,
               expect_stdout_contains="bytes")

    await test("verify imported file",
               "cat /imported.txt",
               expect_stdout="imported from host\n")

    # --- Binary round-trip ---
    print("\n--- binary round-trip ---")
    bin_path = os.path.join(tmpdir, "binary.bin")
    bin_data = bytes(range(256))
    with open(bin_path, "wb") as f:
        f.write(bin_data)

    await test("local binary → memfs",
               f"boxcp local://{bin_path} /binary.bin",
               expect_exit=0,
               expect_stdout_contains="256 bytes")

    await test("memfs binary → local",
               f"boxcp /binary.bin local://{tmpdir}/binary_rt.bin",
               expect_exit=0,
               expect_stdout_contains="256 bytes")

    rt_path = os.path.join(tmpdir, "binary_rt.bin")
    if os.path.isfile(rt_path):
        rt_data = open(rt_path, "rb").read()
        if rt_data == bin_data:
            passed += 1
            print("  ✓ binary round-trip verified (256 bytes)")
        else:
            failed += 1
            print(f"  ✗ binary mismatch: {len(rt_data)} bytes")
    else:
        failed += 1
        print(f"  ✗ round-trip file not found: {rt_path}")

    # --- S3 via MinIO ---
    print("\n--- S3 (MinIO) ---")

    # Configure S3 env for MinIO
    os.environ["AGENTBOX_S3_ENDPOINT"] = "http://localhost:9100"
    os.environ["AWS_ACCESS_KEY_ID"] = "minioadmin"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "minioadmin"

    s3_ok = True
    try:
        import boto3
        s3 = boto3.client("s3", endpoint_url="http://localhost:9100")
        s3.head_bucket(Bucket="agentbox-repos")
    except Exception as e:
        s3_ok = False
        print(f"  ⊘ S3/MinIO not available, skipping ({e})")

    if s3_ok:
        # Clean up any leftover test keys
        test_prefix = "boxcp-test/"
        try:
            resp = s3.list_objects_v2(Bucket="agentbox-repos", Prefix=test_prefix)
            for obj in resp.get("Contents", []):
                s3.delete_object(Bucket="agentbox-repos", Key=obj["Key"])
        except Exception:
            pass

        # MemFS → S3
        await sh.run('echo "hello from sandbox" > /s3_export.txt')
        await test("memfs → s3",
                   "boxcp /s3_export.txt s3://agentbox-repos/boxcp-test/exported.txt",
                   expect_exit=0,
                   expect_stdout_contains="bytes")

        # Verify in S3
        try:
            obj = s3.get_object(Bucket="agentbox-repos", Key="boxcp-test/exported.txt")
            s3_content = obj["Body"].read().decode()
            if "hello from sandbox" in s3_content:
                passed += 1
                print("  ✓ S3 object content verified")
            else:
                failed += 1
                print(f"  ✗ S3 content: {s3_content!r}")
        except Exception as e:
            failed += 1
            print(f"  ✗ S3 read failed: {e}")

        # S3 → MemFS
        s3.put_object(Bucket="agentbox-repos", Key="boxcp-test/import_me.txt",
                      Body=b"hello from s3\n")
        await test("s3 → memfs",
                   "boxcp s3://agentbox-repos/boxcp-test/import_me.txt /s3_imported.txt",
                   expect_exit=0,
                   expect_stdout_contains="bytes")
        await test("verify s3 import",
                   "cat /s3_imported.txt",
                   expect_stdout="hello from s3\n")

        # S3 binary round-trip
        s3_bin = bytes(range(256)) * 4  # 1KB
        await sh.run('echo "placeholder" > /s3_bin_src.txt')
        # Write binary to MemFS via local, then export to S3
        bin_tmp = os.path.join(tmpdir, "s3_bin.bin")
        with open(bin_tmp, "wb") as f:
            f.write(s3_bin)
        await test("local binary → memfs (for s3 test)",
                   f"boxcp local://{bin_tmp} /s3_binary.bin",
                   expect_exit=0)
        await test("memfs binary → s3",
                   "boxcp /s3_binary.bin s3://agentbox-repos/boxcp-test/binary.bin",
                   expect_exit=0,
                   expect_stdout_contains="bytes")
        await test("s3 binary → memfs",
                   "boxcp s3://agentbox-repos/boxcp-test/binary.bin /s3_binary_rt.bin",
                   expect_exit=0,
                   expect_stdout_contains="bytes")
        # Export back to local to verify
        await test("memfs → local (verify s3 binary rt)",
                   f"boxcp /s3_binary_rt.bin local://{tmpdir}/s3_binary_rt.bin",
                   expect_exit=0)
        rt_s3_path = os.path.join(tmpdir, "s3_binary_rt.bin")
        if os.path.isfile(rt_s3_path):
            rt_data = open(rt_s3_path, "rb").read()
            if rt_data == s3_bin:
                passed += 1
                print(f"  ✓ S3 binary round-trip verified ({len(s3_bin)} bytes)")
            else:
                failed += 1
                print(f"  ✗ S3 binary mismatch: got {len(rt_data)}, expected {len(s3_bin)}")
        else:
            failed += 1
            print(f"  ✗ S3 binary rt file not found")

        # S3 not found
        await test("s3 not found",
                   "boxcp s3://agentbox-repos/boxcp-test/nonexistent.txt /nope.txt",
                   expect_exit=1,
                   expect_stderr_contains="Not found")

        # Clean up test keys
        try:
            resp = s3.list_objects_v2(Bucket="agentbox-repos", Prefix=test_prefix)
            for obj in resp.get("Contents", []):
                s3.delete_object(Bucket="agentbox-repos", Key=obj["Key"])
        except Exception:
            pass

    # --- local:// security: path outside allowlist ---
    print("\n--- local security ---")
    await test("local outside allowlist",
               "boxcp local:///etc/passwd /stolen.txt",
               expect_exit=1,
               expect_stderr_contains="not in allowlisted")

    # --- which boxcp ---
    print("\n--- virtual /bin ---")
    await test("which boxcp",
               "which boxcp",
               expect_stdout="/bin/boxcp\n")

    # --- Cleanup ---
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

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
