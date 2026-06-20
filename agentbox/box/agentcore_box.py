"""AgentCoreBox — Box implementation backed by AWS AgentCore Code Interpreter.

Unlike CodeExecutorBox (which uses PyodideEngine + ShellExecutor),
AgentCoreBox delegates everything to a real MicroVM via AgentCoreEngine.
Shell commands run in real bash — no tree-sitter-bash emulation needed.

Host-intercepted commands:
    - ``edit`` — AI file editing (patch module) runs host-side so the full
      fuzzy/AST matching is available regardless of engine.
    - ``apply_patch`` — V4A patch application runs host-side.
    - ``git push`` / ``git pull`` — intercepted for S3 sync (future).
"""

from __future__ import annotations

import logging
import os
import shlex

from agentbox.box.box import Box
from agentbox.engine.agentcore_engine import AgentCoreEngine

logger = logging.getLogger(__name__)

# Commands that are intercepted and run host-side instead of in the MicroVM
_INTERCEPTED_COMMANDS = {"edit", "apply_patch"}


class AgentCoreBox(Box):
    """Sandbox backed by AWS Bedrock AgentCore Code Interpreter.

    Each box maps to one AgentCore session (one MicroVM). The session
    has real Python, real bash, real pip, and a real filesystem.

    Lifecycle:
        box = AgentCoreBox()
        await box.start()          # start AgentCore session
        result = await box.run_code("print('hello')")
        result = await box.run_shell("ls -la")
        await box.stop()           # stop session, release MicroVM

    Can also be used as an async context manager:
        async with AgentCoreBox() as box:
            await box.run_code("import pandas; print(pandas.__version__)")
    """

    def __init__(self, timeout=300, repo_id=None, workspace="workspace",
                 auto_sync=True, **engine_kwargs):
        """
        Args:
            timeout: Per-execution timeout in seconds.
            repo_id: Repository ID for S3 persistence. None = ephemeral.
            workspace: Working directory in the MicroVM.
            auto_sync: Auto-sync to storage on stop (when repo_id is set).
            **engine_kwargs: Passed to AgentCoreEngine (region, session_timeout,
                interpreter_id).
        """
        self.timeout = timeout
        self.repo_id = repo_id
        self.workspace = workspace
        self.auto_sync = auto_sync
        self._engine = AgentCoreEngine(timeout=timeout, **engine_kwargs)
        self._cwd = workspace
        self._abs_workspace = None  # Resolved during start()
        self._storage = None  # Set by start() if repo_id is configured
        self._token_refresh_task = None  # Background token refresh for browser auth

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def _started(self):
        return self._engine.started

    @property
    def session_id(self):
        """The AgentCore session ID."""
        return self._engine.session_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Start the AgentCore session.

        If repo_id is set, restores files from S3 storage and initializes
        git in the workspace (real git, not isomorphic-git).
        """
        if self._started:
            return
        await self._engine.start()

        # Create workspace directory and resolve absolute path
        await self._engine.execute_shell(f"mkdir -p {self.workspace}")
        abs_ws = (await self._engine.execute_shell(
            f"cd {self.workspace} && pwd"
        ))["stdout"].strip()
        self._abs_workspace = abs_ws or None

        # Inject orchestrator URL and a sandbox-scoped auth token into the
        # MicroVM environment so the browser_client can authenticate.
        # The token is minted from AGENTBOX_SERVICE_SECRET with TTL matching
        # the session timeout — the service secret itself never enters the VM.
        await self._inject_auth_env()

        # Restore from storage if repo exists
        if self.repo_id:
            self._storage = _get_storage()
            if self._storage and await self._storage.exists(self.repo_id):
                from agentbox.box.git.engine_sync import pull_from_store
                files_pulled, errors = await pull_from_store(
                    self._engine, self.workspace, self.repo_id, self._storage
                )
                if files_pulled > 0:
                    logger.info("Restored %d files from storage (errors: %d)",
                                files_pulled, len(errors))
                    # Checkout working tree if .git exists
                    await self._engine.execute_shell(
                        f"cd {self.workspace} && git checkout main 2>/dev/null || "
                        f"git checkout master 2>/dev/null || true"
                    )
            else:
                # Init fresh git repo
                await self._engine.execute_shell(
                    f"cd {self.workspace} && git init && "
                    f"git config user.email 'agent@agentbox' && "
                    f"git config user.name 'AgentBox'"
                )

    async def stop(self):
        """Stop the AgentCore session and release the MicroVM.

        If repo_id is set and auto_sync is True, pushes files to S3
        before stopping.
        """
        if not self._started:
            return

        # Cancel token refresh task
        if self._token_refresh_task:
            self._token_refresh_task.cancel()
            self._token_refresh_task = None

        # Sync to storage before stopping
        if self.repo_id and self.auto_sync and self._storage:
            try:
                from agentbox.box.git.engine_sync import push_to_store
                files_pushed, errors = await push_to_store(
                    self._engine, self.workspace, self.repo_id, self._storage
                )
                if files_pushed > 0:
                    logger.info("Synced %d files to storage on stop (errors: %d)",
                                files_pushed, len(errors))
            except Exception as e:
                logger.warning("Failed to sync on stop: %s", e)

        await self._engine.stop()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
        return False

    # ------------------------------------------------------------------
    # Box ABC implementation
    # ------------------------------------------------------------------

    async def run_code(self, code, language="python"):
        """Execute code in the AgentCore MicroVM.

        Returns:
            dict with keys: stdout, stderr, exit_code
        """
        self._ensure_started()
        return await self._engine.execute(code, language=language)

    async def run_shell(self, command):
        """Execute a shell command in the AgentCore MicroVM (real bash).

        Intercepts ``edit`` and ``apply_patch`` commands to run them
        host-side with the full patch module. All other commands pass
        through to real bash in the MicroVM.

        Returns:
            dict with keys: stdout, stderr, exit_code
        """
        self._ensure_started()

        # Check for intercepted commands
        result = await self._try_intercept(command)
        if result is not None:
            return result

        # Rewrite /workspace/ paths to the actual workspace location
        command = self._rewrite_workspace_paths(command)

        return await self._engine.execute_shell(command)

    async def read_file(self, path):
        """Read a file from the AgentCore MicroVM filesystem."""
        self._ensure_started()
        return await self._engine.read_file(path)

    async def write_file(self, path, content):
        """Write a file to the AgentCore MicroVM filesystem."""
        self._ensure_started()
        return await self._engine.write_file(path, content)

    # ------------------------------------------------------------------
    # Command interception
    # ------------------------------------------------------------------

    async def _try_intercept(self, command: str) -> dict | None:
        """Check if command should be intercepted. Returns result dict or None."""
        # Extract the first word (command name)
        stripped = command.strip()
        if not stripped:
            return None

        # Handle heredoc for apply_patch: split on <<
        cmd_part = stripped.split("<<")[0].strip() if "<<" in stripped else stripped
        first_word = cmd_part.split()[0] if cmd_part.split() else ""

        if first_word == "edit":
            return await self._intercept_edit(stripped)
        elif first_word == "apply_patch":
            return await self._intercept_apply_patch(stripped)
        elif first_word == "git":
            words = cmd_part.split()
            if len(words) >= 2 and words[1] in ("push", "pull"):
                return await self._intercept_git_sync(words[1], words[2:])

        return None

    async def _intercept_edit(self, command: str) -> dict:
        """Run the edit command host-side using the patch module."""
        try:
            args = shlex.split(command)
        except ValueError as e:
            return {"stdout": "", "stderr": f"edit: parse error: {e}\n", "exit_code": 1}

        # Remove 'edit' from args
        args = args[1:]

        if not args:
            return {
                "stdout": "",
                "stderr": (
                    "edit: usage: edit <file> --old '...' --new '...'\n"
                    "       edit <file> --view [--range N:M]\n"
                    "       edit <file> --insert N --text '...'\n"
                    "       edit <file> --create --content '...'\n"
                ),
                "exit_code": 1,
            }

        # Parse arguments (mirrors EditExec.run())
        filepath = None
        old_str = None
        new_str = None
        is_view = False
        view_range = None
        insert_line = None
        insert_text = None
        is_create = False
        create_content = None
        is_info = False
        is_diff = False

        i = 0
        while i < len(args):
            a = args[i]
            if a == "--old" and i + 1 < len(args):
                i += 1; old_str = args[i]
            elif a == "--new" and i + 1 < len(args):
                i += 1; new_str = args[i]
            elif a == "--view":
                is_view = True
            elif a == "--range" and i + 1 < len(args):
                i += 1; view_range = args[i]
            elif a == "--insert" and i + 1 < len(args):
                i += 1
                try:
                    insert_line = int(args[i])
                except ValueError:
                    return {"stdout": "", "stderr": f"edit: --insert requires a line number, got: {args[i]}\n", "exit_code": 1}
            elif a == "--text" and i + 1 < len(args):
                i += 1; insert_text = args[i]
            elif a == "--create":
                is_create = True
            elif a == "--info":
                is_info = True
            elif a == "--diff":
                is_diff = True
            elif a == "--content" and i + 1 < len(args):
                i += 1; create_content = args[i]
            elif not a.startswith("-") and filepath is None:
                filepath = a
            i += 1

        if filepath is None:
            return {"stdout": "", "stderr": "edit: missing file path\n", "exit_code": 1}

        resolved = self._resolve_path(filepath)

        from agentbox.box.patch.patcher import str_replace, insert, view, info, create, diff_preview

        # --- Dispatch to mode ---
        if is_create:
            existing = await self._engine.read_file(resolved)
            if existing is not None:
                return {"stdout": "", "stderr": f"edit: {filepath} already exists. Use --old/--new to edit.\n", "exit_code": 1}
            result = create(create_content or "", path=filepath)
            await self._engine.write_file(resolved, result.new_content)
            return {"stdout": result.message + "\n", "stderr": "", "exit_code": 0}

        if is_info:
            content = await self._engine.read_file(resolved)
            if content is None:
                return {"stdout": "", "stderr": f"edit: {filepath}: No such file\n", "exit_code": 1}
            result = info(content, path=filepath)
            return {"stdout": result.message + "\n", "stderr": "", "exit_code": 0}

        if is_view:
            content = await self._engine.read_file(resolved)
            if content is None:
                return {"stdout": "", "stderr": f"edit: {filepath}: No such file\n", "exit_code": 1}
            start, end = 1, None
            if view_range:
                parts = view_range.split(":")
                try:
                    start = int(parts[0]) if parts[0] else 1
                    end = int(parts[1]) if len(parts) > 1 and parts[1] else None
                except ValueError:
                    return {"stdout": "", "stderr": f"edit: invalid range: {view_range}\n", "exit_code": 1}
            result = view(content, start=start, end=end, path=filepath)
            output = result.message
            if result.snippet:
                output += "\n" + result.snippet
            return {"stdout": output + "\n", "stderr": "", "exit_code": 0}

        if insert_line is not None:
            if insert_text is None:
                return {"stdout": "", "stderr": "edit: --insert requires --text\n", "exit_code": 1}
            content = await self._engine.read_file(resolved)
            if content is None:
                return {"stdout": "", "stderr": f"edit: {filepath}: No such file\n", "exit_code": 1}
            result = insert(content, insert_line, insert_text, path=filepath)
            if not result.success:
                return {"stdout": "", "stderr": result.message + "\n", "exit_code": 1}
            await self._engine.write_file(resolved, result.new_content)
            output = result.message
            if result.snippet:
                output += "\n" + result.snippet
            return {"stdout": output + "\n", "stderr": "", "exit_code": 0}

        if old_str is not None:
            if new_str is None:
                return {"stdout": "", "stderr": "edit: --old requires --new\n", "exit_code": 1}
            content = await self._engine.read_file(resolved)
            if content is None:
                return {"stdout": "", "stderr": f"edit: {filepath}: No such file\n", "exit_code": 1}
            if is_diff:
                result = diff_preview(content, old_str, new_str, path=filepath)
            else:
                result = str_replace(content, old_str, new_str, path=filepath)
            if not result.success:
                return {"stdout": "", "stderr": result.message + "\n", "exit_code": 1}
            if not is_diff:
                await self._engine.write_file(resolved, result.new_content)
            output = result.message
            if result.snippet:
                output += "\n" + result.snippet
            return {"stdout": output + "\n", "stderr": "", "exit_code": 0}

        return {
            "stdout": "",
            "stderr": "edit: no operation specified. Use --old/--new, --view, --insert, --create, --info, or --diff.\n",
            "exit_code": 1,
        }

    async def _intercept_apply_patch(self, command: str) -> dict:
        """Run the apply_patch command host-side using the V4A patch module."""
        from agentbox.box.patch.v4a import apply_v4a_diff, parse_v4a_patch

        # Extract heredoc content or file argument
        patch_text = None

        if "<<" in command:
            # Heredoc: extract content after the delimiter line
            parts = command.split("<<", 1)
            rest = parts[1].strip()
            # Find delimiter (e.g., 'EOF' or "EOF" or EOF)
            lines = rest.split("\n")
            delim_line = lines[0].strip().strip("'\"")
            # Find content between delimiter markers
            body_lines = []
            for line in lines[1:]:
                if line.strip() == delim_line:
                    break
                body_lines.append(line)
            patch_text = "\n".join(body_lines) + "\n"
        else:
            # apply_patch <file> — read patch from a file in the MicroVM
            try:
                args = shlex.split(command)
            except ValueError:
                args = command.split()
            if len(args) >= 2:
                path = self._resolve_path(args[1])
                patch_text = await self._engine.read_file(path)
                if patch_text is None:
                    return {"stdout": "", "stderr": f"apply_patch: {path}: No such file\n", "exit_code": 1}

        if not patch_text or not patch_text.strip():
            return {
                "stdout": "",
                "stderr": (
                    "apply_patch: no patch input.\n"
                    "Usage: apply_patch << 'EOF'\n"
                    "*** Update File: /path\n"
                    "@@ anchor\n"
                    " context\n"
                    "-old\n"
                    "+new\n"
                    "*** End Patch\n"
                    "EOF\n"
                ),
                "exit_code": 1,
            }

        try:
            ops = parse_v4a_patch(patch_text)
        except Exception as e:
            return {"stdout": "", "stderr": f"apply_patch: parse error: {e}\n", "exit_code": 1}

        if not ops:
            return {"stdout": "", "stderr": "apply_patch: no operations found in patch\n", "exit_code": 1}

        results = []
        errors = []

        for op in ops:
            path = self._resolve_path(op.path)

            if op.type == "add":
                existing = await self._engine.read_file(path)
                if existing is not None:
                    errors.append(f"  FAIL: {op.path} already exists")
                    continue
                try:
                    content = apply_v4a_diff("", op.diff, mode="create")
                    await self._engine.write_file(path, content)
                    results.append(f"  ADD: {op.path}")
                except Exception as e:
                    errors.append(f"  FAIL: {op.path}: {e}")

            elif op.type == "update":
                current = await self._engine.read_file(path)
                if current is None:
                    errors.append(f"  FAIL: {op.path}: file not found")
                    continue
                try:
                    new_content = apply_v4a_diff(current, op.diff)
                    await self._engine.write_file(path, new_content)
                    results.append(f"  UPDATE: {op.path}")
                except Exception as e:
                    errors.append(f"  FAIL: {op.path}: {e}")

            elif op.type == "delete":
                existing = await self._engine.read_file(path)
                if existing is None:
                    errors.append(f"  FAIL: {op.path}: file not found")
                    continue
                # Delete by writing empty — AgentCore doesn't have a delete API
                # Use shell rm instead
                rm_result = await self._engine.execute_shell(f"rm -f {path}")
                if rm_result["exit_code"] == 0:
                    results.append(f"  DELETE: {op.path}")
                else:
                    errors.append(f"  FAIL: {op.path}: {rm_result['stderr']}")

        stdout_parts = results + errors
        total = len(results) + len(errors)
        ok = len(results)
        stdout_parts.append(f"apply_patch: {ok}/{total} operations succeeded")
        stdout = "\n".join(stdout_parts) + "\n"

        exit_code = 1 if errors else 0
        return {"stdout": stdout, "stderr": "", "exit_code": exit_code}

    # ------------------------------------------------------------------
    # Git push/pull interception
    # ------------------------------------------------------------------

    async def _intercept_git_sync(self, subcmd: str, args: list[str]) -> dict:
        """Intercept git push/pull to route through S3 storage."""
        if args:
            return {
                "stdout": "",
                "stderr": f"git {subcmd}: arguments not supported. Use plain 'git {subcmd}' to sync with storage.\n",
                "exit_code": 1,
            }

        if not self.repo_id:
            return {
                "stdout": "",
                "stderr": f"git {subcmd}: no repo_id configured.\n",
                "exit_code": 1,
            }

        storage = self._storage or _get_storage()
        if storage is None:
            return {
                "stdout": "",
                "stderr": f"git {subcmd}: storage backend not configured.\n",
                "exit_code": 1,
            }

        if subcmd == "push":
            return await self._git_push(storage)
        else:
            return await self._git_pull(storage)

    async def _git_push(self, storage) -> dict:
        """Push workspace files to S3 storage."""
        from agentbox.box.git.engine_sync import push_to_store

        # Get current HEAD SHA
        head_result = await self._engine.execute_shell(
            f"cd {self.workspace} && git rev-parse HEAD 2>/dev/null"
        )
        head_sha = head_result["stdout"].strip() if head_result["exit_code"] == 0 else None

        if head_sha:
            # Check if already pushed
            last_pushed = await storage.read_file(self.repo_id, ".agentbox-push-ref")
            if last_pushed and last_pushed.decode("utf-8").strip() == head_sha:
                return {"stdout": "Everything up-to-date\n", "stderr": "", "exit_code": 0}

        files_pushed, errors = await push_to_store(
            self._engine, self.workspace, self.repo_id, storage
        )

        if errors:
            stderr = "\n".join(errors) + "\n"
            return {
                "stdout": f"Pushed {files_pushed} files to {self.repo_id}\n",
                "stderr": stderr,
                "exit_code": 1,
            }

        # Record pushed commit SHA
        if head_sha:
            await storage.write_file(self.repo_id, ".agentbox-push-ref", head_sha.encode("utf-8"))

        return {
            "stdout": f"Pushed {files_pushed} files to {self.repo_id}\n",
            "stderr": "",
            "exit_code": 0,
        }

    async def _git_pull(self, storage) -> dict:
        """Pull files from S3 storage into workspace."""
        from agentbox.box.git.engine_sync import pull_from_store

        exists = await storage.exists(self.repo_id)
        if not exists:
            return {"stdout": "Already up to date.\n", "stderr": "", "exit_code": 0}

        files_pulled, errors = await pull_from_store(
            self._engine, self.workspace, self.repo_id, storage
        )

        if files_pulled == 0 and not errors:
            return {"stdout": "Already up to date.\n", "stderr": "", "exit_code": 0}

        if errors:
            stderr = "\n".join(errors) + "\n"
            return {
                "stdout": f"Pulled {files_pulled} files from {self.repo_id}\n",
                "stderr": stderr,
                "exit_code": 1,
            }

        # Checkout working tree
        await self._engine.execute_shell(
            f"cd {self.workspace} && git checkout main 2>/dev/null || "
            f"git checkout master 2>/dev/null || true"
        )

        return {
            "stdout": f"Pulled {files_pulled} files from {self.repo_id}\n",
            "stderr": "",
            "exit_code": 0,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _inject_auth_env(self):
        """Inject auth environment into the MicroVM for browser_client.

        Mints a sandbox-scoped service token and starts a background task
        that refreshes it before expiry. The AGENTBOX_SERVICE_SECRET itself
        never enters the VM — only the derived short-lived JWT.
        """
        import asyncio

        orchestrator_url = os.environ.get("AGENTBOX_ORCHESTRATOR_URL")
        service_secret = os.environ.get("AGENTBOX_SERVICE_SECRET")

        if orchestrator_url:
            # Set in both shell (for subprocesses) and Python kernel (for os.environ)
            await self._engine.execute_shell(
                f"export AGENTBOX_ORCHESTRATOR_URL='{orchestrator_url}'"
            )
            await self._engine.execute(
                f"import os; os.environ['AGENTBOX_ORCHESTRATOR_URL'] = '{orchestrator_url}'",
                language="python",
            )

        if not service_secret:
            return

        # Mint initial token and inject it
        await self._refresh_token_in_vm(service_secret)

        # Start background refresh loop — refreshes at 50% of TTL
        token_ttl = self._engine._session_timeout
        refresh_interval = max(token_ttl // 2, 30)  # At least every 30s

        async def _refresh_loop():
            while True:
                await asyncio.sleep(refresh_interval)
                try:
                    await self._refresh_token_in_vm(service_secret)
                except Exception as e:
                    logger.warning("Token refresh in MicroVM failed: %s", e)

        self._token_refresh_task = asyncio.create_task(_refresh_loop())

    async def _refresh_token_in_vm(self, service_secret: str):
        """Mint a fresh token and update AGENTBOX_AUTH_TOKEN inside the MicroVM.

        Sets the token in both the shell environment (for subprocesses) and
        the IPython kernel's os.environ (for execute_code calls).
        """
        from agentbox.api.auth import mint_service_token

        token = mint_service_token(
            service_secret,
            subject=f"sandbox:{self._engine.session_id}",
            ttl=self._engine._session_timeout,
        )
        # Shell env (for bash subprocesses)
        await self._engine.execute_shell(
            f"export AGENTBOX_AUTH_TOKEN='{token}'"
        )
        # Python kernel env (for os.environ in execute_code)
        await self._engine.execute(
            f"import os; os.environ['AGENTBOX_AUTH_TOKEN'] = '{token}'",
            language="python",
        )

    def _resolve_path(self, path: str) -> str:
        """Resolve a relative path against the current working directory."""
        if path.startswith("/"):
            return path
        return os.path.normpath(os.path.join(self._cwd, path))

    def _rewrite_workspace_paths(self, command: str) -> str:
        """Rewrite /workspace references to the actual MicroVM workspace path.

        Only rewrites standalone /workspace (not when it appears as a suffix
        of the actual workspace path to avoid double-rewriting).
        """
        if not self._abs_workspace or self._abs_workspace == "/workspace":
            return command
        import re
        # Match /workspace only when not preceded by another path character
        return re.sub(
            r'(?<![/\w])(/workspace)(?=/|$|\s|[\'"])',
            self._abs_workspace,
            command,
        )

    def _ensure_started(self):
        if not self._started:
            raise RuntimeError("Box not started. Call await box.start() first.")


# ------------------------------------------------------------------
# Storage helper (shared with git_box.py)
# ------------------------------------------------------------------

def _get_storage():
    """Get the configured storage backend. Returns None if not configured."""
    import os
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
        access_key = os.environ.get("AGENTBOX_GIT_S3_ACCESS_KEY")
        secret_key = os.environ.get("AGENTBOX_GIT_S3_SECRET_KEY")
        return S3StorageBackend(
            bucket, prefix, endpoint_url=endpoint, region_name=region,
            access_key=access_key, secret_key=secret_key,
        )

    return None
