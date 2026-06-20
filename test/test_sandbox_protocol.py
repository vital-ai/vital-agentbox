"""Unit tests for AgentBoxSandbox (BaseSandbox protocol compliance).

These tests verify that AgentBoxSandbox correctly implements the
Deep Agents BaseSandbox / SandboxBackendProtocol interface.

Tests are split into:
  - Protocol compliance tests (no network, no docker-compose)
  - Integration tests (require docker-compose stack running)

Usage:
    python test/test_sandbox_protocol.py          # all tests
    python test/test_sandbox_protocol.py --unit    # unit tests only
    python test/test_sandbox_protocol.py --integration  # integration only
"""

import asyncio
import sys
import warnings

from agentbox.langchain.sandbox import AgentBoxSandbox
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import (
    SandboxBackendProtocol,
    ExecuteResponse,
    FileUploadResponse,
    FileDownloadResponse,
    WriteResult,
    EditResult,
    FileInfo,
)


ORCHESTRATOR_URL = "http://localhost:8090"


def run_unit_tests():
    """Protocol compliance tests — no network required."""
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  \u2713 {name}")
        else:
            failed += 1
            print(f"  \u2717 {name}")
            if detail:
                print(f"      {detail}")

    print("=" * 60)
    print("SANDBOX PROTOCOL UNIT TESTS")
    print("=" * 60)

    # --- Class hierarchy ---
    print("\n--- Class Hierarchy ---")
    check("subclass of BaseSandbox", issubclass(AgentBoxSandbox, BaseSandbox))
    check("subclass of SandboxBackendProtocol",
          issubclass(AgentBoxSandbox, SandboxBackendProtocol))

    # --- Abstract methods implemented ---
    print("\n--- Abstract Methods ---")
    remaining = getattr(AgentBoxSandbox, "__abstractmethods__", set())
    check("no unimplemented abstract methods",
          len(remaining) == 0,
          f"unimplemented: {remaining}")

    for method_name in ["execute", "upload_files", "download_files"]:
        check(f"has {method_name}()",
              callable(getattr(AgentBoxSandbox, method_name, None)))

    check("has id property",
          isinstance(getattr(AgentBoxSandbox, "id", None), property))

    # --- Overridden methods ---
    print("\n--- Overridden Methods ---")
    for method_name in ["read", "write", "edit", "ls_info"]:
        # Verify the method is defined on AgentBoxSandbox, not just inherited
        check(f"overrides {method_name}()",
              method_name in AgentBoxSandbox.__dict__,
              f"{method_name} not found in AgentBoxSandbox.__dict__")

    # --- Inherited methods available ---
    print("\n--- Inherited Methods ---")
    for method_name in ["glob_info", "grep_raw"]:
        check(f"inherits {method_name}()",
              callable(getattr(AgentBoxSandbox, method_name, None)))

    # --- Async variants available (from BaseSandbox) ---
    print("\n--- Async Variants ---")
    for method_name in ["aexecute", "aread", "awrite", "aupload_files", "adownload_files"]:
        check(f"has {method_name}()",
              callable(getattr(AgentBoxSandbox, method_name, None)))

    # --- Constructor ---
    print("\n--- Constructor ---")
    sandbox = AgentBoxSandbox.__new__(AgentBoxSandbox)
    AgentBoxSandbox.__init__(
        sandbox,
        base_url="http://localhost:9999",
        token="test-token",
        box_type="git",
        repo_id="test-repo",
        auto_cleanup=False,
    )
    check("base_url stored", sandbox._base_url == "http://localhost:9999")
    check("box_type stored", sandbox._box_type == "git")
    check("repo_id stored", sandbox._repo_id == "test-repo")
    check("auto_cleanup stored", sandbox._auto_cleanup is False)
    check("sandbox_id initially None", sandbox._sandbox_id is None)
    check("http client created", sandbox._http is not None)
    sandbox._http.close()

    # --- Repr ---
    print("\n--- Repr ---")
    sandbox2 = AgentBoxSandbox.__new__(AgentBoxSandbox)
    sandbox2._sandbox_id = None
    sandbox2._box_type = "mem"
    check("repr before sandbox", "not-created" in repr(sandbox2))
    sandbox2._sandbox_id = "test-123"
    check("repr with sandbox", "test-123" in repr(sandbox2))

    # --- Deprecation warning on old class ---
    print("\n--- Deprecation ---")
    from agentbox.langchain.backend import AgentBoxBackend
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        backend = AgentBoxBackend.__new__(AgentBoxBackend)
        AgentBoxBackend.__init__(backend, base_url="http://localhost:9999")
        check("AgentBoxBackend emits DeprecationWarning",
              len(w) == 1 and issubclass(w[0].category, DeprecationWarning),
              f"warnings: {w}")
    await_cleanup = getattr(backend, "client", None)
    if await_cleanup:
        try:
            asyncio.run(await_cleanup.close())
        except Exception:
            pass

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"UNIT TESTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")
    return failed == 0


async def run_integration_tests():
    """Integration tests — require docker-compose stack running."""
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  \u2713 {name}")
        else:
            failed += 1
            print(f"  \u2717 {name}")
            if detail:
                print(f"      {detail}")

    print("=" * 60)
    print("SANDBOX PROTOCOL INTEGRATION TESTS")
    print("=" * 60)

    # --- Basic lifecycle ---
    print("\n--- Lifecycle ---")
    with AgentBoxSandbox(base_url=ORCHESTRATOR_URL) as sandbox:
        # id triggers lazy creation
        sid = sandbox.id
        check("sandbox created", sid is not None and len(sid) > 0, f"id={sid}")

        # --- execute ---
        print("\n--- execute() ---")
        result = sandbox.execute("echo hello-sandbox")
        check("execute returns ExecuteResponse",
              isinstance(result, ExecuteResponse),
              f"type={type(result)}")
        check("execute output", "hello-sandbox" in result.output,
              f"output={result.output!r}")
        check("execute exit_code", result.exit_code == 0,
              f"exit_code={result.exit_code}")

        # Shell pipeline
        result = sandbox.execute("echo abc | wc -c")
        check("execute pipeline", result.exit_code == 0,
              f"output={result.output!r}")

        # Failing command
        result = sandbox.execute("false")
        check("execute failure exit_code", result.exit_code != 0,
              f"exit_code={result.exit_code}")

        # --- write / read ---
        print("\n--- write() / read() ---")
        wr = sandbox.write("/workspace/test.txt", "hello deep agents")
        check("write returns WriteResult", isinstance(wr, WriteResult),
              f"type={type(wr)}")
        check("write no error", wr.error is None, f"error={wr.error}")
        check("write path", wr.path == "/workspace/test.txt",
              f"path={wr.path}")

        content = sandbox.read("/workspace/test.txt")
        check("read returns str", isinstance(content, str),
              f"type={type(content)}")
        check("read content", content.strip() == "hello deep agents",
              f"content={content!r}")

        # Read missing file
        missing = sandbox.read("/no/such/file.txt")
        check("read missing returns error string", "not found" in missing.lower(),
              f"content={missing!r}")

        # --- edit ---
        print("\n--- edit() ---")
        er = sandbox.edit("/workspace/test.txt", "hello", "goodbye")
        check("edit returns EditResult", isinstance(er, EditResult),
              f"type={type(er)}")
        check("edit no error", er.error is None, f"error={er.error}")
        check("edit occurrences", er.occurrences == 1,
              f"occurrences={er.occurrences}")

        content = sandbox.read("/workspace/test.txt")
        check("edit applied", "goodbye deep agents" in content,
              f"content={content!r}")

        # Edit with replace_all
        sandbox.write("/workspace/multi.txt", "aaa bbb aaa ccc aaa")
        er2 = sandbox.edit("/workspace/multi.txt", "aaa", "XXX", replace_all=True)
        check("edit replace_all count", er2.occurrences == 3,
              f"occurrences={er2.occurrences}")
        content2 = sandbox.read("/workspace/multi.txt")
        check("edit replace_all applied", "aaa" not in content2 and "XXX" in content2,
              f"content={content2!r}")

        # Edit string not found
        er3 = sandbox.edit("/workspace/test.txt", "NONEXISTENT", "X")
        check("edit not found returns error", er3.error is not None,
              f"error={er3.error}")

        # --- ls_info ---
        print("\n--- ls_info() ---")
        entries = sandbox.ls_info("/workspace")
        check("ls_info returns list", isinstance(entries, list),
              f"type={type(entries)}")
        check("ls_info has entries", len(entries) > 0,
              f"count={len(entries)}")
        if entries:
            check("ls_info entry is FileInfo",
                  isinstance(entries[0], dict) and "path" in entries[0],
                  f"entry={entries[0]}")

        # --- upload_files / download_files ---
        print("\n--- upload_files() / download_files() ---")
        upload_result = sandbox.upload_files([
            ("/workspace/uploaded.txt", b"uploaded content"),
            ("/workspace/sub/nested.txt", b"nested content"),
        ])
        check("upload returns list", isinstance(upload_result, list),
              f"type={type(upload_result)}")
        check("upload count", len(upload_result) == 2,
              f"count={len(upload_result)}")
        check("upload no errors",
              all(r.error is None for r in upload_result),
              f"errors={[r.error for r in upload_result]}")

        dl_result = sandbox.download_files([
            "/workspace/uploaded.txt",
            "/workspace/sub/nested.txt",
        ])
        check("download returns list", isinstance(dl_result, list))
        check("download count", len(dl_result) == 2)
        check("download content",
              dl_result[0].content == b"uploaded content",
              f"content={dl_result[0].content!r}")
        check("download nested content",
              dl_result[1].content == b"nested content",
              f"content={dl_result[1].content!r}")

        # Download missing file
        dl_missing = sandbox.download_files(["/no/such/file.txt"])
        check("download missing has error",
              dl_missing[0].error == "file_not_found",
              f"error={dl_missing[0].error}")

        # --- async variants ---
        print("\n--- Async Variants ---")
        aresult = await sandbox.aexecute("echo async-test")
        check("aexecute works", "async-test" in aresult.output,
              f"output={aresult.output!r}")

        acontent = await sandbox.aread("/workspace/test.txt")
        check("aread works", "goodbye" in acontent,
              f"content={acontent!r}")

    # sandbox.__exit__ should have destroyed it
    check("sandbox closed (auto_cleanup)", True)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"INTEGRATION TESTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")
    return failed == 0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--all"

    results = []

    if mode in ("--unit", "--all"):
        results.append(run_unit_tests())

    if mode in ("--integration", "--all"):
        results.append(asyncio.run(run_integration_tests()))

    return all(results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
