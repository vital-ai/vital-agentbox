"""
Unit tests for AgentCoreEngine and AgentCoreBox with mocked CodeInterpreter.

Tests verify:
- Engine lifecycle (start/stop)
- Code execution with response parsing
- Shell execution
- File read/write
- Error handling (timeout, exceptions)
- AgentCoreBox delegation
- BoxManager integration with engine='agentcore'
"""

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock


# ---------------------------------------------------------------------------
# Mock CodeInterpreter
# ---------------------------------------------------------------------------

def make_mock_client():
    """Create a mock CodeInterpreter that returns realistic responses."""
    client = MagicMock()
    client.start.return_value = "session-abc123"

    # execute_code returns streaming response
    client.execute_code.return_value = {
        "stream": [
            {
                "result": {
                    "content": [
                        {"type": "text", "text": "hello\n"}
                    ]
                }
            }
        ]
    }

    # execute_command returns streaming response
    client.execute_command.return_value = {
        "stream": [
            {
                "result": {
                    "content": [
                        {"type": "text", "text": "file1.txt\nfile2.py\n"}
                    ]
                }
            }
        ]
    }

    # download_file returns text
    client.download_file.return_value = "file content here"

    # upload_file returns success
    client.upload_file.return_value = {"status": "ok"}

    # stop returns True
    client.stop.return_value = True

    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

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
    print("TEST: AgentCoreEngine (mocked)")
    print("=" * 60)

    # --- Engine lifecycle ---
    print("\n--- engine lifecycle ---")

    from agentbox.engine.agentcore_engine import AgentCoreEngine

    CI_PATCH = "bedrock_agentcore.tools.CodeInterpreter"

    engine = AgentCoreEngine(region="us-east-1")
    check("engine_type", engine.engine_type == "agentcore")
    check("not started", engine.started is False)

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine(region="us-east-1", session_timeout=1800)

        await engine.start()
        check("started", engine.started is True)
        check("session_id", engine.session_id == "session-abc123")
        check("CodeInterpreter called with region", MockCI.call_args[1]["region"] == "us-east-1")
        check("start called", mock_client.start.called)

    # --- Code execution ---
    print("\n--- execute code ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine()
        await engine.start()

        result = await engine.execute("print('hello')")
        check("execute stdout", result["stdout"] == "hello\n",
              f"got {result['stdout']!r}")
        check("execute exit_code", result["exit_code"] == 0)
        check("execute_code called", mock_client.execute_code.called)
        check("execute_code args",
              mock_client.execute_code.call_args[1]["code"] == "print('hello')")
        check("execute_code language",
              mock_client.execute_code.call_args[1]["language"] == "python")

    # --- Code execution with error ---
    print("\n--- execute code error ---")

    mock_client = make_mock_client()
    mock_client.execute_code.return_value = {
        "stream": [
            {
                "error": {
                    "message": "NameError: name 'x' is not defined",
                    "exitCode": 1,
                }
            }
        ]
    }
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine()
        await engine.start()

        result = await engine.execute("print(x)")
        check("error stderr", "NameError" in result["stderr"],
              f"got {result['stderr']!r}")
        check("error exit_code", result["exit_code"] == 1)

    # --- Shell execution ---
    print("\n--- execute shell ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine()
        await engine.start()

        result = await engine.execute_shell("ls -1")
        check("shell stdout", "file1.txt" in result["stdout"],
              f"got {result['stdout']!r}")
        check("shell exit_code", result["exit_code"] == 0)
        check("execute_command called", mock_client.execute_command.called)

    # --- File read ---
    print("\n--- file read ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine()
        await engine.start()

        content = await engine.read_file("/workspace/test.txt")
        check("read_file content", content == "file content here",
              f"got {content!r}")
        check("download_file called", mock_client.download_file.called)

    # --- File read (not found) ---
    print("\n--- file read not found ---")

    mock_client = make_mock_client()
    mock_client.download_file.side_effect = FileNotFoundError("not found")
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine()
        await engine.start()

        content = await engine.read_file("/nonexistent.txt")
        check("read_file missing returns None", content is None)

    # --- File read (binary) ---
    print("\n--- file read binary ---")

    mock_client = make_mock_client()
    mock_client.download_file.return_value = b"binary\x00data"
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine()
        await engine.start()

        content = await engine.read_file("/image.png")
        check("read_file binary decoded", isinstance(content, str))

    # --- File write ---
    print("\n--- file write ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine()
        await engine.start()

        ok = await engine.write_file("/workspace/out.txt", "hello world")
        check("write_file returns True", ok is True)
        check("upload_file called", mock_client.upload_file.called)
        check("upload_file path (relative)",
              mock_client.upload_file.call_args[1]["path"] == "workspace/out.txt")

    # --- File write error ---
    print("\n--- file write error ---")

    mock_client = make_mock_client()
    mock_client.upload_file.side_effect = Exception("upload failed")
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine()
        await engine.start()

        ok = await engine.write_file("/test.txt", "data")
        check("write_file error returns False", ok is False)

    # --- list_files ---
    print("\n--- list_files ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine()
        await engine.start()

        files = await engine.list_files("/workspace")
        check("list_files returns list", isinstance(files, list))
        check("list_files has entries", len(files) == 2,
              f"got {files}")

    # --- Engine stop ---
    print("\n--- engine stop ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine()
        await engine.start()
        await engine.stop()

        check("stopped", engine.started is False)
        check("session_id cleared", engine.session_id is None)
        check("stop called", mock_client.stop.called)

    # --- Not started error ---
    print("\n--- not started error ---")

    engine = AgentCoreEngine()
    try:
        await engine.execute("print('hi')")
        check("should raise", False)
    except RuntimeError:
        check("raises RuntimeError when not started", True)

    # --- SDK exception during execute ---
    print("\n--- SDK exception ---")

    mock_client = make_mock_client()
    mock_client.execute_code.side_effect = Exception("boto3 error")
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine()
        await engine.start()

        result = await engine.execute("print('hi')")
        check("SDK error stderr", "AgentCore error" in result["stderr"],
              f"got {result['stderr']!r}")
        check("SDK error exit_code", result["exit_code"] == 1)

    # --- Response with structuredContent ---
    print("\n--- structuredContent response format ---")

    mock_client = make_mock_client()
    mock_client.execute_code.return_value = {
        "stream": [{
            "result": {
                "content": [{"type": "text", "text": "42"}],
                "structuredContent": {
                    "stdout": "42",
                    "stderr": "",
                    "exitCode": 0,
                    "executionTime": 0.05,
                },
                "isError": False,
            }
        }]
    }
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client
        engine = AgentCoreEngine()
        await engine.start()

        result = await engine.execute("print(42)")
        check("structuredContent stdout", result["stdout"] == "42",
              f"got {result['stdout']!r}")

    # === AgentCoreBox ===
    print("\n" + "=" * 60)
    print("TEST: AgentCoreBox (mocked)")
    print("=" * 60)

    from agentbox.box.agentcore_box import AgentCoreBox

    # --- Box lifecycle ---
    print("\n--- box lifecycle ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client

        box = AgentCoreBox()
        check("box not started", box._started is False)

        await box.start()
        check("box started", box._started is True)
        check("box session_id", box.session_id == "session-abc123")

    # --- Box context manager ---
    print("\n--- box context manager ---")

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client

        async with AgentCoreBox() as box:
            result = await box.run_code("print('hello')")
            check("box run_code", result["stdout"] == "hello\n",
                  f"got {result['stdout']!r}")

            result = await box.run_shell("ls")
            check("box run_shell", "file1.txt" in result["stdout"])

            content = await box.read_file("/test.txt")
            check("box read_file", content == "file content here")

            ok = await box.write_file("/out.txt", "data")
            check("box write_file", ok is True)

        check("box stopped after exit", box._started is False)

    # --- Box raises when not started ---
    print("\n--- box not started ---")

    box = AgentCoreBox()
    try:
        await box.run_code("print('hi')")
        check("should raise", False)
    except RuntimeError:
        check("box raises RuntimeError when not started", True)

    # === BoxManager with engine='agentcore' ===
    print("\n" + "=" * 60)
    print("TEST: BoxManager engine='agentcore' (mocked)")
    print("=" * 60)

    from agentbox.manager.box_manager import BoxManager

    mock_client = make_mock_client()
    with patch(CI_PATCH) as MockCI:
        MockCI.return_value = mock_client

        mgr = BoxManager()
        await mgr.start()

        info = await mgr.create_sandbox(
            sandbox_id="ac-test-1",
            engine="agentcore",
        )
        check("create returns dict", isinstance(info, dict))
        check("sandbox_id matches", info["sandbox_id"] == "ac-test-1")
        check("engine is agentcore", info["engine"] == "agentcore")
        check("state is ready", info["state"] == "ready")

        # Run code through manager
        sandbox = await mgr.get_sandbox("ac-test-1")
        check("get_sandbox", sandbox is not None)

        await mgr.stop()

    # === Protocol check ===
    print("\n--- protocol check ---")

    from agentbox.engine.base import ExecutionEngine
    check("AgentCoreEngine is ExecutionEngine",
          isinstance(AgentCoreEngine(), ExecutionEngine))

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
