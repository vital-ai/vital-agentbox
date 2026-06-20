"""
Engine-agnostic git sync: push/pull between an ExecutionEngine and a StorageBackend.

Unlike sync.py (which uses page.evaluate for MemFS), this module uses
the engine's read_file/write_file/execute_shell methods — works with any
execution engine (PyodideEngine, AgentCoreEngine, etc.).

Used by AgentCoreBox for S3 persistence with real git.
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbox.box.git.storage import StorageBackend

logger = logging.getLogger(__name__)


async def push_to_store(engine, workspace: str, repo_id: str, storage: "StorageBackend"):
    """Push all files from the engine's workspace to storage backend.

    Uses ``engine.execute_shell("find ...")`` to list files, then
    ``engine.read_file()`` to read each one and write to storage.

    Args:
        engine: An ExecutionEngine instance (started).
        workspace: Workspace directory in the engine (e.g. "/workspace").
        repo_id: Repository identifier in storage.
        storage: StorageBackend to push to.

    Returns:
        (files_pushed, errors) — tuple of count and list of error strings.
    """
    # List all files recursively
    result = await engine.execute_shell(f"find {workspace} -type f")
    if result["exit_code"] != 0:
        return 0, [f"Failed to list files: {result['stderr']}"]

    file_list = [f for f in result["stdout"].strip().split("\n") if f]
    files_pushed = 0
    errors = []

    for full_path in file_list:
        # Read file content as text (may need binary handling)
        # Use base64 encoding via shell to handle binary files
        b64_result = await engine.execute_shell(f"base64 < '{full_path}'")
        if b64_result["exit_code"] != 0:
            errors.append(f"Failed to read: {full_path}")
            continue

        try:
            file_bytes = base64.b64decode(b64_result["stdout"].strip())
        except Exception as e:
            errors.append(f"Failed to decode: {full_path}: {e}")
            continue

        # Compute relative path
        rel_path = full_path[len(workspace):].lstrip("/")
        if not rel_path:
            continue

        await storage.write_file(repo_id, rel_path, file_bytes)
        files_pushed += 1

    return files_pushed, errors


async def pull_from_store(engine, workspace: str, repo_id: str, storage: "StorageBackend",
                          prefix_filter: str | None = None):
    """Pull files from storage backend into the engine's workspace.

    Downloads files from the store and writes into the engine at
    ``{workspace}/{rel_path}``.

    Args:
        engine: An ExecutionEngine instance (started).
        workspace: Workspace directory in the engine (e.g. "/workspace").
        repo_id: Repository identifier in storage.
        storage: StorageBackend to pull from.
        prefix_filter: Optional prefix to filter files (e.g. ".git/").

    Returns:
        (files_pulled, errors) — tuple of count and list of error strings.
    """
    file_list = await storage.list_files(repo_id)
    if prefix_filter:
        file_list = [f for f in file_list if f.startswith(prefix_filter)]

    files_pulled = 0
    errors = []

    for rel_path in file_list:
        file_bytes = await storage.read_file(repo_id, rel_path)
        if file_bytes is None:
            errors.append(f"Failed to read from store: {rel_path}")
            continue

        full_path = f"{workspace}/{rel_path}"

        # Ensure parent directory exists
        parent = "/".join(full_path.split("/")[:-1])
        if parent:
            await engine.execute_shell(f"mkdir -p '{parent}'")

        # Write binary content via base64 decode in the engine
        b64_data = base64.b64encode(file_bytes).decode("ascii")
        write_result = await engine.execute_shell(
            f"echo '{b64_data}' | base64 -d > '{full_path}'"
        )

        if write_result["exit_code"] == 0:
            files_pulled += 1
        else:
            errors.append(f"Failed to write: {full_path}: {write_result['stderr']}")

    return files_pulled, errors
