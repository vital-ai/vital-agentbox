"""
GitBox: Sandbox with isomorphic-git for versioned file operations.

Extends CodeExecutorBox to load isomorphic-git in the browser page,
set up the FS adapter, and optionally initialize or restore a git repo.

On start, if repo_id is set and the repo already exists in storage,
the workspace is automatically restored from S3. Otherwise a fresh
git repo is initialized.
"""

import logging
import os

from agentbox.box.code_exec_box import CodeExecutorBox, PYODIDE_URL
from agentbox.box.git.fs_adapter import FS_ADAPTER_JS, GIT_HELPERS_JS
from agentbox.box.git.sync import pull_from_store


logger = logging.getLogger(__name__)

ISOMORPHIC_GIT_CDN = os.environ.get(
    "AGENTBOX_ISOMORPHIC_GIT_URL",
    "https://unpkg.com/isomorphic-git@1.27.1/index.umd.min.js",
)

DEFAULT_WORKSPACE = "/workspace"


def _get_storage():
    """Get the configured storage backend. Returns None if not configured."""
    from agentbox.box.git.storage import LocalStorageBackend, S3StorageBackend

    backend_type = os.environ.get("AGENTBOX_GIT_STORE", "local")

    if backend_type == "local":
        base_path = os.environ.get("AGENTBOX_GIT_STORE_PATH", "/tmp/agentbox-repos")
        return LocalStorageBackend(base_path)
    elif backend_type == "s3":
        bucket = os.environ.get("AGENTBOX_GIT_S3_BUCKET")
        if not bucket:
            return None
        prefix = os.environ.get("AGENTBOX_GIT_S3_PREFIX", "repos/")
        endpoint = os.environ.get("AGENTBOX_GIT_S3_ENDPOINT")
        region = os.environ.get("AGENTBOX_GIT_S3_REGION")
        return S3StorageBackend(bucket, prefix, endpoint_url=endpoint, region_name=region)

    return None


class GitBox(CodeExecutorBox):
    """Git-enabled sandbox with isomorphic-git on MemFS.

    Extends CodeExecutorBox:
    - Loads isomorphic-git in the browser page
    - Sets up the Emscripten FS adapter for isomorphic-git
    - If repo_id exists in storage, restores from S3 on start
    - Otherwise initializes a fresh git repo at /workspace

    Usage:
        async with GitBox(repo_id="task-123") as box:
            await box.run_shell('cd /workspace && echo "# Report" > report.md')
            await box.run_shell('git add report.md')
            await box.run_shell('git commit -m "Initial draft"')
            await box.run_shell('git log --oneline')
    """

    def __init__(self, repo_id=None, workspace=DEFAULT_WORKSPACE,
                 auto_sync=True, **kwargs):
        """
        Args:
            repo_id: Repository identifier for persistent storage.
                     None = ephemeral git repo (no sync).
            workspace: Path for the git working directory.
            auto_sync: If True, auto-sync to storage on commit.
            **kwargs: Passed to CodeExecutorBox (timeout, message_handler).
        """
        super().__init__(**kwargs)
        self.repo_id = repo_id
        self.workspace = workspace
        self.auto_sync = auto_sync

    async def start(self):
        """Launch browser, load Pyodide + isomorphic-git, init or restore repo."""
        if self._started:
            return

        # Start the base: Playwright + Pyodide + MemFS + ShellExecutor
        await super().start()

        # Load isomorphic-git into the page
        await self._page.add_script_tag(url=ISOMORPHIC_GIT_CDN)

        # Set up FS adapter and helpers for isomorphic-git
        await self._page.evaluate(FS_ADAPTER_JS)
        await self._page.evaluate(GIT_HELPERS_JS)

        # Set repo_id in shell environment for git push
        if self.repo_id:
            await self.run_shell(f"export AGENTBOX_REPO_ID={self.repo_id}")

        # Create workspace directory
        await self.memfs.mkdir_p(self.workspace)

        # Try to restore from storage if repo exists
        restored = False
        if self.repo_id:
            storage = _get_storage()
            if storage and await storage.exists(self.repo_id):
                logger.info("Restoring repo %s from storage into %s", self.repo_id, self.workspace)
                files_pulled, errors = await pull_from_store(
                    self._page, self.workspace, self.repo_id, storage
                )
                if files_pulled > 0:
                    # Checkout working tree from restored .git objects
                    await self._page.evaluate("""async ([dir]) => {
                        const git = window.git;
                        const fs = window.fsAdapter;
                        if (!git || !fs) return;
                        try { await git.checkout({ fs, dir, ref: 'main' }); }
                        catch(e) {
                            try { await git.checkout({ fs, dir, ref: 'master' }); }
                            catch(e2) {}
                        }
                    }""", [self.workspace])
                    restored = True
                    logger.info("Restored %d files from storage (errors: %d)", files_pulled, len(errors))
                    # Set last-pull ref so git pull knows we're up to date
                    push_ref = await storage.read_file(self.repo_id, ".agentbox-push-ref")
                    if push_ref:
                        await self.run_shell(f"export AGENTBOX_LAST_PULL_REF={push_ref.decode('utf-8').strip()}")

        # If not restored, init a fresh repo
        if not restored:
            await self.run_shell(f"git init {self.workspace}")

        # Set cwd to workspace
        await self.run_shell(f"cd {self.workspace}")

