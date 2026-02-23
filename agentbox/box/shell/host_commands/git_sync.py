"""
Tier 3 host-delegated commands: git push, git pull, git clone.

These commands sync between the in-browser MemFS (isomorphic-git) and
a permanent storage backend (local filesystem, S3, MinIO).

They are registered as git-push, git-pull, git-clone in HOST_COMMANDS
and called by the git builtin when the agent runs git push/pull/clone.
"""

import os

from agentbox.box.shell.environment import ShellResult
from agentbox.box.git.sync import push_to_store, pull_from_store


def _get_storage():
    """Get the configured storage backend. Returns None if not configured."""
    # Import here to avoid circular imports
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


def _get_repo_id(env):
    """Get the repo_id from shell environment or return None."""
    return env.variables.get("AGENTBOX_REPO_ID")


async def host_git_push(args, stdin, env, memfs):
    """git push: sync MemFS repo to permanent storage."""
    if args:
        return ShellResult(
            exit_code=1,
            stderr="git push: arguments not supported. Use plain 'git push' to sync to storage.\n"
        )

    repo_id = _get_repo_id(env)
    if not repo_id:
        return ShellResult(
            exit_code=1,
            stderr="git push: no repo_id configured. Set AGENTBOX_REPO_ID or use GitBox with repo_id.\n"
        )

    storage = _get_storage()
    if storage is None:
        return ShellResult(
            exit_code=1,
            stderr="git push: storage backend not configured.\n"
        )

    dir = env.cwd
    # Verify this is a git repo
    has_git = await memfs.page.evaluate("""([dir]) => {
        try {
            window.pyodide._module.FS.stat(dir + '/.git');
            return true;
        } catch(e) { return false; }
    }""", [dir])

    if not has_git:
        return ShellResult(
            exit_code=1,
            stderr=f"git push: {dir} is not a git repository\n"
        )

    # Get current HEAD commit SHA
    head_sha = await memfs.page.evaluate("""async ([dir]) => {
        const git = window.git;
        const fs = window.fsAdapter;
        if (!git || !fs) return null;
        try {
            return await git.resolveRef({ fs, dir, ref: 'HEAD' });
        } catch(e) { return null; }
    }""", [dir])

    if not head_sha:
        return ShellResult(
            exit_code=0,
            stdout="Everything up-to-date\n",
        )

    # Check if this commit was already pushed
    PUSH_REF_KEY = ".agentbox-push-ref"
    last_pushed = await storage.read_file(repo_id, PUSH_REF_KEY)
    if last_pushed and last_pushed.decode("utf-8").strip() == head_sha:
        return ShellResult(
            exit_code=0,
            stdout="Everything up-to-date\n",
        )

    files_pushed, errors = await push_to_store(memfs.page, dir, repo_id, storage)

    if errors:
        stderr = "\n".join(errors) + "\n"
        return ShellResult(
            exit_code=1,
            stdout=f"Pushed {files_pushed} files to {repo_id}\n",
            stderr=stderr,
        )

    # Record the pushed commit SHA
    await storage.write_file(repo_id, PUSH_REF_KEY, head_sha.encode("utf-8"))

    return ShellResult(
        exit_code=0,
        stdout=f"Pushed {files_pushed} files to {repo_id}\n",
    )


async def host_git_pull(args, stdin, env, memfs):
    """git pull: fetch latest pushed state from storage into MemFS."""
    if args:
        return ShellResult(
            exit_code=1,
            stderr="git pull: arguments not supported. Use plain 'git pull' to sync from storage.\n"
        )

    repo_id = _get_repo_id(env)
    if not repo_id:
        return ShellResult(
            exit_code=1,
            stderr="git pull: no repo_id configured.\n"
        )

    storage = _get_storage()
    if storage is None:
        return ShellResult(
            exit_code=1,
            stderr="git pull: storage backend not configured.\n"
        )

    exists = await storage.exists(repo_id)
    if not exists:
        return ShellResult(
            exit_code=0,
            stdout="Already up to date.\n",
        )

    # Check if remote has changed since last pull
    PUSH_REF_KEY = ".agentbox-push-ref"
    remote_ref = await storage.read_file(repo_id, PUSH_REF_KEY)
    remote_sha = remote_ref.decode("utf-8").strip() if remote_ref else None
    last_pull_sha = env.variables.get("AGENTBOX_LAST_PULL_REF")
    if remote_sha and last_pull_sha and remote_sha == last_pull_sha:
        return ShellResult(
            exit_code=0,
            stdout="Already up to date.\n",
        )

    dir = env.cwd
    files_pulled, errors = await pull_from_store(memfs.page, dir, repo_id, storage)

    if files_pulled == 0 and not errors:
        return ShellResult(
            exit_code=0,
            stdout="Already up to date.\n",
        )

    if errors:
        stderr = "\n".join(errors) + "\n"
        return ShellResult(
            exit_code=1,
            stdout=f"Pulled {files_pulled} files from {repo_id}\n",
            stderr=stderr,
        )

    # Checkout working tree from pulled .git objects
    await memfs.page.evaluate("""async ([dir]) => {
        const git = window.git;
        const fs = window.fsAdapter;
        if (!git || !fs) return;
        try { await git.checkout({ fs, dir, ref: 'main', force: true }); }
        catch(e) {
            try { await git.checkout({ fs, dir, ref: 'master', force: true }); }
            catch(e2) {}
        }
    }""", [dir])

    # Track what we last pulled so we can short-circuit next time
    if remote_sha:
        env.variables["AGENTBOX_LAST_PULL_REF"] = remote_sha

    return ShellResult(
        exit_code=0,
        stdout=f"Pulled {files_pulled} files from {repo_id}\n",
    )


async def host_git_fetch(args, stdin, env, memfs):
    """git fetch: download objects from storage without updating working tree."""
    if args:
        return ShellResult(
            exit_code=1,
            stderr="git fetch: arguments not supported. Use plain 'git fetch' to sync from storage.\n"
        )

    repo_id = _get_repo_id(env)
    if not repo_id:
        return ShellResult(
            exit_code=1,
            stderr="git fetch: no repo_id configured.\n"
        )

    storage = _get_storage()
    if storage is None:
        return ShellResult(
            exit_code=1,
            stderr="git fetch: storage backend not configured.\n"
        )

    exists = await storage.exists(repo_id)
    if not exists:
        return ShellResult(
            exit_code=0,
            stdout="",
        )

    dir = env.cwd
    # Only sync .git/ objects, not working tree files
    files_pulled, errors = await pull_from_store(
        memfs.page, dir, repo_id, storage, prefix_filter=".git/"
    )

    if errors:
        stderr = "\n".join(errors) + "\n"
        return ShellResult(
            exit_code=1,
            stderr=stderr,
        )

    return ShellResult(
        exit_code=0,
        stdout="",
    )


async def host_git_clone(args, stdin, env, memfs):
    """git clone: error, already in a repo."""
    return ShellResult(
        exit_code=1,
        stderr="fatal: you are already in a git repository\n"
    )
