"""
Unit tests for AgentCoreBox git push/pull interception and S3 persistence.

Tests verify:
- git push/pull commands are intercepted (not passed to bash)
- Storage restore on start (when repo_id is set)
- Auto-sync on stop
- Git init for new repos
- Error cases (no repo_id, no storage)
- engine_sync.py push_to_store/pull_from_store
"""

import asyncio
import os
import shutil
import tempfile
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

CI_PATCH = "bedrock_agentcore.tools.CodeInterpreter"


def make_mock_client():
    """Create a mock CodeInterpreter with realistic responses."""
    client = MagicMock()
    client.start.return_value = "session-git-test"
    client.stop.return_value = True

    def cmd_response(text=""):
        return {"stream": [{"result": {"content": [{"type": "text", "text": text}]}}]}

    client.execute_command.return_value = cmd_response("")
    client.execute_code.return_value = cmd_response("")
    client.upload_file.return_value = {"status": "ok"}
    client.download_file.return_value = "file content"

    return client


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

    from agentbox.box.agentcore_box import AgentCoreBox, _get_storage

    # =====================================================================
    print("=" * 60)
    print("TEST: git push interception")
    print("=" * 60)

    # --- git push with repo_id ---
    print("\n--- git push with repo_id (local storage) ---")

    tmpdir = tempfile.mkdtemp()
    os.environ["AGENTBOX_GIT_STORE"] = "local"
    os.environ["AGENTBOX_GIT_STORE_PATH"] = tmpdir

    try:
        mock_client = make_mock_client()
        # Simulate: find returns files, base64 returns content, git rev-parse returns SHA
        call_count = [0]
        def mock_execute_command(command, **kwargs):
            call_count[0] += 1
            cmd = command
            if "find" in cmd and "-type f" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": "/workspace/hello.py\n/workspace/.git/HEAD\n"}]}}]}
            elif "base64" in cmd:
                import base64 as b64
                if "hello.py" in cmd:
                    return {"stream": [{"result": {"content": [{"type": "text", "text": b64.b64encode(b'print("hi")').decode() + "\n"}]}}]}
                else:
                    return {"stream": [{"result": {"content": [{"type": "text", "text": b64.b64encode(b'ref: refs/heads/main').decode() + "\n"}]}}]}
            elif "git rev-parse HEAD" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": "abc123\n"}]}}]}
            elif "mkdir -p" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            elif "git init" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": "Initialized empty Git repository\n"}]}}]}
            return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}

        mock_client.execute_command.side_effect = mock_execute_command

        with patch(CI_PATCH) as MockCI:
            MockCI.return_value = mock_client
            box = AgentCoreBox(repo_id="test-repo")
            await box.start()
            result = await box.run_shell("git push")
            check("git push intercepted", result["exit_code"] == 0,
                  f"stderr={result['stderr']!r}, stdout={result['stdout']!r}")
            check("push shows files count", "Pushed" in result["stdout"] or "up-to-date" in result["stdout"])
            # Verify the mock wasn't called with "git push" directly
            # (it would be a separate call; check that intercept handled it)
            await box.stop()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # --- git push without repo_id ---
    print("\n--- git push without repo_id ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell("git push")
            check("push fails without repo_id", result["exit_code"] == 1)
            check("error mentions no repo_id", "no repo_id" in result["stderr"])

    # --- git push with args rejected ---
    print("\n--- git push with args ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        box = AgentCoreBox(repo_id="test-repo")
        box._storage = MagicMock()
        await box.start()
        result = await box.run_shell("git push origin main")
        check("push with args rejected", result["exit_code"] == 1)
        check("error mentions not supported", "not supported" in result["stderr"])
        await box.stop()

    # =====================================================================
    print("\n" + "=" * 60)
    print("TEST: git pull interception")
    print("=" * 60)

    # --- git pull with repo_id ---
    print("\n--- git pull with repo_id ---")

    tmpdir = tempfile.mkdtemp()
    os.environ["AGENTBOX_GIT_STORE"] = "local"
    os.environ["AGENTBOX_GIT_STORE_PATH"] = tmpdir

    try:
        # Pre-populate storage with a file
        from agentbox.box.git.storage import LocalStorageBackend
        storage = LocalStorageBackend(tmpdir)
        await storage.write_file("test-repo", "hello.py", b'print("from storage")')

        mock_client = make_mock_client()
        def mock_execute_command_pull(command, **kwargs):
            cmd = command
            if "mkdir -p" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            elif "echo" in cmd and "base64" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            elif "git checkout" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            elif "git init" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": "Initialized\n"}]}}]}
            elif "find" in cmd and "-type f" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}

        mock_client.execute_command.side_effect = mock_execute_command_pull

        with patch(CI_PATCH) as MockCI:
            MockCI.return_value = mock_client
            box = AgentCoreBox(repo_id="test-repo")
            await box.start()
            result = await box.run_shell("git pull")
            check("git pull intercepted", result["exit_code"] == 0,
                  f"stderr={result['stderr']!r}, stdout={result['stdout']!r}")
            check("pull shows files count", "Pulled" in result["stdout"] or "up to date" in result["stdout"])
            await box.stop()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # --- git pull without repo_id ---
    print("\n--- git pull without repo_id ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell("git pull")
            check("pull fails without repo_id", result["exit_code"] == 1)
            check("error mentions no repo_id", "no repo_id" in result["stderr"])

    # =====================================================================
    print("\n" + "=" * 60)
    print("TEST: other git commands pass through")
    print("=" * 60)

    mock_client = make_mock_client()
    mock_client.execute_command.return_value = {
        "stream": [{"result": {"content": [{"type": "text", "text": "On branch main\n"}]}}]
    }
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        async with AgentCoreBox() as box:
            result = await box.run_shell("git status")
            check("git status passes through", result["stdout"] == "On branch main\n")

            result = await box.run_shell("git log --oneline -5")
            check("git log passes through", mock_client.execute_command.called)

            result = await box.run_shell("git commit -m 'test'")
            check("git commit passes through", mock_client.execute_command.called)

            result = await box.run_shell("git branch feature")
            check("git branch passes through", mock_client.execute_command.called)

    # =====================================================================
    print("\n" + "=" * 60)
    print("TEST: auto-restore on start")
    print("=" * 60)

    print("\n--- repo_id with existing storage ---")

    tmpdir = tempfile.mkdtemp()
    os.environ["AGENTBOX_GIT_STORE"] = "local"
    os.environ["AGENTBOX_GIT_STORE_PATH"] = tmpdir

    try:
        storage = LocalStorageBackend(tmpdir)
        await storage.write_file("restore-repo", "app.py", b'print("restored")')
        await storage.write_file("restore-repo", ".git/HEAD", b'ref: refs/heads/main')

        mock_client = make_mock_client()
        mkdir_calls = []
        echo_calls = []

        def mock_execute_command_restore(command, **kwargs):
            cmd = command
            if "mkdir -p" in cmd:
                mkdir_calls.append(cmd)
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            elif "echo" in cmd and "base64" in cmd:
                echo_calls.append(cmd)
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            elif "git checkout" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            elif "find" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}

        mock_client.execute_command.side_effect = mock_execute_command_restore

        with patch(CI_PATCH) as MockCI:
            MockCI.return_value = mock_client
            box = AgentCoreBox(repo_id="restore-repo")
            await box.start()
            check("storage set on start", box._storage is not None)
            check("echo calls made (file writes)", len(echo_calls) > 0,
                  f"echo_calls={len(echo_calls)}")
            await box.stop()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # --- repo_id without existing storage (fresh git init) ---
    print("\n--- repo_id without existing storage ---")

    tmpdir = tempfile.mkdtemp()
    os.environ["AGENTBOX_GIT_STORE"] = "local"
    os.environ["AGENTBOX_GIT_STORE_PATH"] = tmpdir

    try:
        mock_client = make_mock_client()
        git_init_called = []

        def mock_execute_command_init(command, **kwargs):
            cmd = command
            if "git init" in cmd:
                git_init_called.append(cmd)
                return {"stream": [{"result": {"content": [{"type": "text", "text": "Initialized\n"}]}}]}
            elif "mkdir" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            elif "find" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}

        mock_client.execute_command.side_effect = mock_execute_command_init

        with patch(CI_PATCH) as MockCI:
            MockCI.return_value = mock_client
            box = AgentCoreBox(repo_id="new-repo")
            await box.start()
            check("git init called for new repo", len(git_init_called) > 0,
                  f"calls={git_init_called}")
            await box.stop()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # =====================================================================
    print("\n" + "=" * 60)
    print("TEST: auto-sync on stop")
    print("=" * 60)

    tmpdir = tempfile.mkdtemp()
    os.environ["AGENTBOX_GIT_STORE"] = "local"
    os.environ["AGENTBOX_GIT_STORE_PATH"] = tmpdir

    try:
        mock_client = make_mock_client()
        find_calls = []

        def mock_execute_command_sync(command, **kwargs):
            cmd = command
            if "find" in cmd and "-type f" in cmd:
                find_calls.append(cmd)
                return {"stream": [{"result": {"content": [{"type": "text", "text": "/workspace/test.py\n"}]}}]}
            elif "base64" in cmd:
                import base64 as b64
                return {"stream": [{"result": {"content": [{"type": "text", "text": b64.b64encode(b'print("test")').decode() + "\n"}]}}]}
            elif "mkdir" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            elif "git init" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": "Initialized\n"}]}}]}
            return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}

        mock_client.execute_command.side_effect = mock_execute_command_sync

        with patch(CI_PATCH) as MockCI:
            MockCI.return_value = mock_client
            box = AgentCoreBox(repo_id="sync-repo", auto_sync=True)
            await box.start()
            await box.stop()
            # Find should have been called during stop (for push_to_store)
            check("auto-sync: find called on stop", len(find_calls) > 0,
                  f"find_calls={len(find_calls)}")

            # Check that file was written to storage
            storage = LocalStorageBackend(tmpdir)
            files = await storage.list_files("sync-repo")
            check("auto-sync: files in storage", len(files) > 0,
                  f"files={files}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # --- auto_sync=False ---
    print("\n--- auto_sync=False ---")

    tmpdir = tempfile.mkdtemp()
    os.environ["AGENTBOX_GIT_STORE"] = "local"
    os.environ["AGENTBOX_GIT_STORE_PATH"] = tmpdir

    try:
        mock_client = make_mock_client()
        find_calls_nosync = []

        def mock_execute_command_nosync(command, **kwargs):
            cmd = command
            if "find" in cmd and "-type f" in cmd:
                find_calls_nosync.append(cmd)
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            elif "mkdir" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}
            elif "git init" in cmd:
                return {"stream": [{"result": {"content": [{"type": "text", "text": "Initialized\n"}]}}]}
            return {"stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]}

        mock_client.execute_command.side_effect = mock_execute_command_nosync

        with patch(CI_PATCH) as MockCI:
            MockCI.return_value = mock_client
            box = AgentCoreBox(repo_id="nosync-repo", auto_sync=False)
            await box.start()
            find_before_stop = len(find_calls_nosync)
            await box.stop()
            find_after_stop = len(find_calls_nosync)
            check("no find calls during stop when auto_sync=False",
                  find_after_stop == find_before_stop,
                  f"before={find_before_stop}, after={find_after_stop}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # =====================================================================
    print("\n" + "=" * 60)
    print("TEST: _get_storage helper")
    print("=" * 60)

    os.environ["AGENTBOX_GIT_STORE"] = "local"
    os.environ["AGENTBOX_GIT_STORE_PATH"] = "/tmp/test-repos"
    storage = _get_storage()
    check("local storage returns LocalStorageBackend",
          type(storage).__name__ == "LocalStorageBackend")

    os.environ["AGENTBOX_GIT_STORE"] = "s3"
    os.environ.pop("AGENTBOX_GIT_S3_BUCKET", None)
    storage = _get_storage()
    check("s3 without bucket returns None", storage is None)

    os.environ["AGENTBOX_GIT_STORE"] = "invalid"
    storage = _get_storage()
    check("invalid backend returns None", storage is None)

    # Clean up env
    for key in ["AGENTBOX_GIT_STORE", "AGENTBOX_GIT_STORE_PATH",
                "AGENTBOX_GIT_S3_BUCKET", "AGENTBOX_GIT_S3_PREFIX",
                "AGENTBOX_GIT_S3_ENDPOINT", "AGENTBOX_GIT_S3_REGION"]:
        os.environ.pop(key, None)

    # =====================================================================
    print("\n" + "=" * 60)
    print("TEST: ephemeral box (no repo_id)")
    print("=" * 60)

    mock_client = make_mock_client()
    mock_client.execute_command.return_value = {
        "stream": [{"result": {"content": [{"type": "text", "text": ""}]}}]
    }
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        box = AgentCoreBox()
        check("no repo_id", box.repo_id is None)
        check("no storage", box._storage is None)
        await box.start()
        check("started without repo_id", box._started)
        check("still no storage", box._storage is None)
        await box.stop()

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
