"""
Unit tests for AgentCoreBox command interception (edit, apply_patch).

Tests verify that edit and apply_patch commands are intercepted and run
host-side using the patch module, while other commands pass through to
real bash via the engine.
"""

import asyncio
from unittest.mock import MagicMock, patch


CI_PATCH = "bedrock_agentcore.tools.CodeInterpreter"


def make_mock_client():
    """Create a mock CodeInterpreter with realistic responses."""
    client = MagicMock()
    client.start.return_value = "session-abc123"
    client.stop.return_value = True

    # execute_command default
    client.execute_command.return_value = {
        "stream": [{"result": {"content": [{"type": "text", "text": "ok\n"}]}}]
    }
    # execute_code default
    client.execute_code.return_value = {
        "stream": [{"result": {"content": [{"type": "text", "text": "ok\n"}]}}]
    }
    client.upload_file.return_value = {"status": "ok"}
    client.download_file.return_value = "file content"

    return client


# File content for testing
SAMPLE_PY = """\
def hello():
    print("hello world")

def goodbye():
    print("goodbye world")
"""


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

    from agentbox.box.agentcore_box import AgentCoreBox

    # =====================================================================
    print("=" * 60)
    print("TEST: edit command interception")
    print("=" * 60)

    # --- edit --view ---
    print("\n--- edit --view ---")

    mock_client = make_mock_client()
    mock_client.download_file.return_value = SAMPLE_PY
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            # Reset after start() which calls execute_command for mkdir
            mock_client.execute_command.reset_mock()
            result = await box.run_shell("edit hello.py --view")
            check("edit --view intercepted", result["exit_code"] == 0,
                  f"stderr={result['stderr']!r}")
            check("edit --view has line numbers", "1" in result["stdout"])
            check("edit --view shows content", "hello" in result["stdout"])
            # Verify execute_command was NOT called for the edit (intercepted)
            check("not passed to bash", not mock_client.execute_command.called)

    # --- edit --view --range ---
    print("\n--- edit --view --range ---")

    mock_client = make_mock_client()
    mock_client.download_file.return_value = SAMPLE_PY
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell("edit hello.py --view --range 1:2")
            check("edit --view --range ok", result["exit_code"] == 0)
            check("shows lines", "hello" in result["stdout"])

    # --- edit --old --new (str_replace) ---
    print("\n--- edit --old --new ---")

    mock_client = make_mock_client()
    mock_client.download_file.return_value = SAMPLE_PY
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell(
                'edit hello.py --old \'print("hello world")\' --new \'print("hi world")\''
            )
            check("str_replace ok", result["exit_code"] == 0,
                  f"stderr={result['stderr']!r}")
            check("upload called", mock_client.upload_file.called)

    # --- edit --insert ---
    print("\n--- edit --insert ---")

    mock_client = make_mock_client()
    mock_client.download_file.return_value = SAMPLE_PY
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell(
                'edit hello.py --insert 2 --text "    # this is a comment"'
            )
            check("insert ok", result["exit_code"] == 0,
                  f"stderr={result['stderr']!r}")
            check("insert upload called", mock_client.upload_file.called)

    # --- edit --create ---
    print("\n--- edit --create ---")

    mock_client = make_mock_client()
    mock_client.download_file.side_effect = FileNotFoundError("not found")
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell(
                'edit newfile.py --create --content "print(42)"'
            )
            check("create ok", result["exit_code"] == 0,
                  f"stderr={result['stderr']!r}")
            check("create upload called", mock_client.upload_file.called)

    # --- edit --create (already exists) ---
    print("\n--- edit --create (exists) ---")

    mock_client = make_mock_client()
    mock_client.download_file.return_value = "existing"
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell(
                'edit hello.py --create --content "print(42)"'
            )
            check("create rejects existing", result["exit_code"] == 1)
            check("error mentions exists", "already exists" in result["stderr"])

    # --- edit --info ---
    print("\n--- edit --info ---")

    mock_client = make_mock_client()
    mock_client.download_file.return_value = SAMPLE_PY
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell("edit hello.py --info")
            check("info ok", result["exit_code"] == 0,
                  f"stderr={result['stderr']!r}")
            check("info shows lines", "lines" in result["stdout"].lower())

    # --- edit --diff ---
    print("\n--- edit --diff ---")

    mock_client = make_mock_client()
    mock_client.download_file.return_value = SAMPLE_PY
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell(
                'edit hello.py --diff --old \'print("hello world")\' --new \'print("hi")\''
            )
            check("diff ok", result["exit_code"] == 0,
                  f"stderr={result['stderr']!r}")
            # diff should NOT write
            check("diff no upload", not mock_client.upload_file.called)

    # --- edit missing file ---
    print("\n--- edit missing file ---")

    mock_client = make_mock_client()
    mock_client.download_file.side_effect = FileNotFoundError("not found")
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell(
                'edit nofile.py --old "a" --new "b"'
            )
            check("missing file fails", result["exit_code"] == 1)
            check("error mentions no such file", "No such file" in result["stderr"])

    # --- edit no args ---
    print("\n--- edit no args ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell("edit")
            check("no args fails", result["exit_code"] == 1)
            check("shows usage", "usage" in result["stderr"])

    # --- edit relative path ---
    print("\n--- edit relative path ---")

    mock_client = make_mock_client()
    mock_client.download_file.return_value = SAMPLE_PY
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell("edit src/app.py --view")
            check("relative path resolved", result["exit_code"] == 0)
            # Check that download_file was called with resolved relative path
            call_path = mock_client.download_file.call_args[1]["path"]
            check("path resolved to workspace/src/app.py",
                  call_path == "workspace/src/app.py",
                  f"got {call_path!r}")

    # =====================================================================
    print("\n" + "=" * 60)
    print("TEST: apply_patch command interception")
    print("=" * 60)

    # --- apply_patch with heredoc ---
    print("\n--- apply_patch heredoc ---")

    mock_client = make_mock_client()
    mock_client.download_file.return_value = SAMPLE_PY
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            patch_cmd = (
                "apply_patch << 'EOF'\n"
                "*** Update File: /workspace/hello.py\n"
                "@@ def hello():\n"
                '-    print("hello world")\n'
                '+    print("hi world")\n'
                "*** End Patch\n"
                "EOF"
            )
            result = await box.run_shell(patch_cmd)
            check("apply_patch ok", result["exit_code"] == 0,
                  f"stderr={result['stderr']!r}, stdout={result['stdout']!r}")
            check("shows UPDATE", "UPDATE" in result["stdout"])
            check("upload called", mock_client.upload_file.called)

    # --- apply_patch add file ---
    print("\n--- apply_patch add ---")

    mock_client = make_mock_client()
    mock_client.download_file.side_effect = FileNotFoundError("not found")
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            patch_cmd = (
                "apply_patch << 'EOF'\n"
                "*** Add File: /workspace/new.py\n"
                "+print('new file')\n"
                "*** End Patch\n"
                "EOF"
            )
            result = await box.run_shell(patch_cmd)
            check("add ok", result["exit_code"] == 0,
                  f"stderr={result['stderr']!r}, stdout={result['stdout']!r}")
            check("shows ADD", "ADD" in result["stdout"])

    # --- apply_patch delete file ---
    print("\n--- apply_patch delete ---")

    mock_client = make_mock_client()
    mock_client.download_file.return_value = "old content"
    mock_client.execute_command.return_value = {
        "stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]
    }
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            patch_cmd = (
                "apply_patch << 'EOF'\n"
                "*** Delete File: /workspace/old.py\n"
                "*** End Patch\n"
                "EOF"
            )
            result = await box.run_shell(patch_cmd)
            check("delete ok", result["exit_code"] == 0,
                  f"stderr={result['stderr']!r}, stdout={result['stdout']!r}")
            check("shows DELETE", "DELETE" in result["stdout"])

    # --- apply_patch no input ---
    print("\n--- apply_patch no input ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell("apply_patch")
            check("no input fails", result["exit_code"] == 1)
            check("shows usage", "Usage" in result["stderr"])

    # =====================================================================
    print("\n" + "=" * 60)
    print("TEST: non-intercepted commands pass through")
    print("=" * 60)

    mock_client = make_mock_client()
    mock_client.execute_command.return_value = {
        "stream": [{"result": {"content": [{"type": "text", "text": "hello\n"}]}}]
    }
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell("echo hello")
            check("echo passes through", mock_client.execute_command.called)
            check("echo stdout", result["stdout"] == "hello\n",
                  f"got {result['stdout']!r}")

            mock_client.execute_command.reset_mock()
            await box.run_shell("ls -la")
            check("ls passes through", mock_client.execute_command.called)

            mock_client.execute_command.reset_mock()
            await box.run_shell("pip install pandas")
            check("pip passes through", mock_client.execute_command.called)

            mock_client.execute_command.reset_mock()
            await box.run_shell("git status")
            check("git status passes through", mock_client.execute_command.called)

    # =====================================================================
    print("\n" + "=" * 60)
    print("TEST: path resolution")
    print("=" * 60)

    box = AgentCoreBox.__new__(AgentCoreBox)
    box._cwd = "/workspace"

    check("absolute path unchanged", box._resolve_path("/tmp/foo") == "/tmp/foo")
    check("relative resolved", box._resolve_path("src/app.py") == "/workspace/src/app.py")
    check("dot-dot resolved", box._resolve_path("../tmp/foo") == "/tmp/foo")
    check("simple name resolved", box._resolve_path("file.txt") == "/workspace/file.txt")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
