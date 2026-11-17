# Execution Engine Extraction & AgentCore Implementation

**Date**: 2026-06-18
**Goal**: Refactor AgentBox to separate the execution engine from the feature layer,
then add AgentCore Code Interpreter as a second execution engine.

> **Sequencing decision**: The Deep Agents API upgrade (Phase 7 in this doc)
> is done **first**, before Phases 1–6. See `deepagents-upgrade.md` for the
> detailed step-by-step plan. The upgrade is independent of the engine
> refactor and immediately unblocks `create_deep_agent(backend=...)` usage.

---

## 1. Current Architecture

```
BoxManager
  └── create_sandbox()
        ├── CodeExecutorBox (MemBox)   ← Playwright + Pyodide + MemFS + ShellExecutor
        └── GitBox (extends CodeExecutorBox) ← + isomorphic-git + S3 sync
```

The existing `Box` ABC (`agentbox/box/box.py`) defines:
- `start()` / `stop()`
- `run_code(code, language)` → `{stdout, stderr, exit_code}`
- `run_shell(command)` → `{stdout, stderr, exit_code}`
- `read_file(path)` → `str | None`
- `write_file(path, content)` → `bool`

Currently, `CodeExecutorBox` tightly couples:
1. **Execution** (Pyodide `runPythonAsync`, tree-sitter-bash shell)
2. **Filesystem** (MemFS via Playwright page)
3. **Features** (shell builtins, git, patch/edit, messaging bridge)

The problem: to add AgentCore as an alternative engine, we need to separate
"how code runs" from "what features sit on top."

---

## 2. Target Architecture

```
BoxManager
  └── create_sandbox(engine="pyodide"|"agentcore")
        │
        ├── FeatureLayer (engine-agnostic)
        │     ├── PersistentFileSync (S3 restore/save)
        │     ├── GitOperations (commit, branch, diff, push/pull)
        │     ├── EditCommand (fuzzy + AST str_replace)
        │     └── SessionLifecycle (state tracking, idle timeout)
        │
        └── ExecutionEngine (pluggable)
              ├── PyodideEngine (existing: Playwright + Pyodide + MemFS)
              └── AgentCoreEngine (new: bedrock-agentcore CodeInterpreter)
```

---

## 3. ExecutionEngine Protocol

Minimal interface that both engines must implement:

```python
# agentbox/engine/base.py
from typing import Protocol

class ExecutionEngine(Protocol):
    """Pluggable code execution backend."""

    async def start(self) -> None:
        """Initialize the engine (launch browser, start session, etc.)."""
        ...

    async def stop(self) -> None:
        """Shut down the engine and release resources."""
        ...

    async def execute(self, code: str, language: str = "python") -> dict:
        """Execute code. Returns {stdout, stderr, exit_code}."""
        ...

    async def execute_shell(self, command: str) -> dict:
        """Execute a shell command. Returns {stdout, stderr, exit_code}."""
        ...

    async def read_file(self, path: str) -> str | None:
        """Read a file from the engine's filesystem."""
        ...

    async def write_file(self, path: str, content: str) -> bool:
        """Write a file to the engine's filesystem."""
        ...

    async def list_files(self, path: str = "/") -> list[str]:
        """List files/directories at path."""
        ...

    @property
    def engine_type(self) -> str:
        """Identifier: 'pyodide' or 'agentcore'."""
        ...
```

---

## 4. Implementation Phases

### Phase 1: Extract Engine Interface (refactor only, no behavior change) ✅ DONE

**Goal**: Introduce `ExecutionEngine` protocol and wrap existing code as
`PyodideEngine` without changing any external behavior. All existing tests
must continue to pass.

**Completed 2026-06-18.**

**Files created:**
- `agentbox/engine/__init__.py` — package with lazy `__getattr__` imports
- `agentbox/engine/base.py` — `ExecutionEngine` protocol (`@runtime_checkable`)
- `agentbox/engine/pyodide_engine.py` — Playwright/Pyodide/MemFS lifecycle + `execute()`

**Files modified:**
- `agentbox/box/code_exec_box.py` — thin wrapper composing `PyodideEngine` +
  `ShellExecutor`. Properties `_page`, `memfs`, `_started`, `_message_handler`
  delegate to engine for backward compat.
- `agentbox/box/git_box.py` — removed unused `PYODIDE_URL` import
- `agentbox/manager/box_manager.py` — added `engine` param (defaults to
  `"pyodide"`, validated). `SandboxInfo` tracks engine type.
- `agentbox/api/models.py` — `CreateSandboxRequest` and `SandboxResponse`
  include `engine` field
- `agentbox/api/routes/sandbox.py` — passes `engine` through
- `agentbox/api/routes/internal.py` — passes `engine` through
- `agentbox/orchestrator/routes/sandboxes.py` — passes `engine` through to worker

**Key implementation notes:**
- `MemFS` is late-imported inside `PyodideEngine.start()` to break a circular
  import chain: `box/__init__` → `code_exec_box` → `engine/pyodide_engine` →
  `box.memfs.memfs` → (triggers `box/__init__` again).
- `engine/__init__.py` uses `__getattr__` for lazy `PyodideEngine` import
  (same circular import mitigation).
- `PyodideEngine.execute_shell()` raises `NotImplementedError` — shell runs
  via `ShellExecutor` at the Box layer, not the engine layer. Future engines
  (AgentCore) will implement this directly.
- `isinstance(PyodideEngine(), ExecutionEngine)` returns `True` at runtime.

**Test results (zero regressions):**

| Suite | Result |
|-------|--------|
| Box Lifecycle | 15/16 (1 pre-existing) |
| Shell Executor | 109/109 |
| BoxManager | 31/31 |
| API | 35/35 |
| LangChain | 27/27 |
| Sandbox Protocol | 33/33 |
| GitBox | 54/54 |
| Patch | 90/90 |

---

### Phase 2: Implement AgentCoreEngine ✅ DONE

**Goal**: Add a second engine that delegates execution to AWS AgentCore
Code Interpreter.

**Completed 2026-06-18.**

**Files created:**
- `agentbox/engine/agentcore_engine.py` — full engine implementation

**Key implementation details:**
- SDK version: `bedrock-agentcore>=1.15.0` (latest; planning doc said 1.1.4)
- All boto3 calls wrapped in `asyncio.to_thread()` — SDK is sync-only
- `CodeInterpreter(region=...)` — constructor takes region, creates control
  plane + data plane boto3 clients internally
- `start(identifier, session_timeout_seconds)` → returns session_id
- `execute_code(code, language)` → dict with streaming event structure
- `execute_command(command)` → dict with streaming event structure
- `download_file(path)` → str or bytes
- `upload_file(path, content)` → dict
- Response parsing: `_parse_execution_result()` handles both streaming
  event format and top-level stdout/stderr/exit_code format
- `execute_shell()` implemented directly (real bash in MicroVM)
- `list_files()` implemented via `execute_shell("ls -1 {path}")`
- Error handling: SDK exceptions caught and returned as exit_code=1
- Timeout: client-side `asyncio.wait_for()` wrapping

**Config env vars:**
- `AGENTBOX_AGENTCORE_REGION` (default: us-east-1)
- `AGENTBOX_AGENTCORE_SESSION_TIMEOUT` (default: 1800 = 30 min)
- `AGENTBOX_AGENTCORE_INTERPRETER_ID` (default: None = system default)

**Test results:** 48/48 mocked unit tests passing (see Phase 3)

---

### Phase 3: AgentCoreBox (feature layer on AgentCoreEngine) ✅ DONE

**Goal**: Create a Box implementation that uses AgentCoreEngine with the
feature layer (persistence, git, editing).

**Completed 2026-06-18.** (Core box created; persistence/git/edit intercept
deferred to Phases 4–5.)

**Files created:**
- `agentbox/box/agentcore_box.py` — `AgentCoreBox(Box)` implementation

**Files modified:**
- `agentbox/box/__init__.py` — exports `AgentCoreBox`
- `agentbox/manager/box_manager.py` — `engine="agentcore"` creates `AgentCoreBox`
  (lazy import to avoid hard dep on bedrock-agentcore)
- `agentbox/api/models.py` — `engine` field in request/response (done in Phase 1)
- `pyproject.toml` — added `[agentcore]` extra: `bedrock-agentcore>=1.15.0`, `boto3>=1.42`

**Key implementation details:**
- Thin wrapper: delegates all Box methods directly to `AgentCoreEngine`
- No `ShellExecutor` — shell runs in real bash via `execute_shell()`
- No `MemFS` — filesystem lives in the AgentCore MicroVM
- Properties: `_started`, `session_id` delegate to engine
- Context manager support (`async with AgentCoreBox() as box:`)
- Default timeout: 300s (vs 30s for PyodideEngine — AgentCore sessions
  support heavier workloads)

**What's deferred:**
- Persistence (S3 restore/sync) → Phase 5
- Edit command intercept → Phase 4
- Git push/pull intercept → Phase 5

**Test results:** 48/48 mocked tests passing across:
- AgentCoreEngine lifecycle, execute, shell, file ops, errors
- AgentCoreBox lifecycle and delegation
- BoxManager `engine="agentcore"` integration
- ExecutionEngine protocol check

**Persistence design for AgentCoreEngine (future):**

The existing `git/sync.py` module handles `pull_from_store()` and
`push_to_store()` by reading/writing files via the Playwright page (MemFS).
For AgentCoreEngine, we need an adapter that does the same operations but
uses `engine.read_file()`/`engine.write_file()` instead of MemFS page calls.

Options:
1. **Abstract the file-access in sync.py** — make it accept a file accessor
   interface (either MemFS or engine). More elegant but larger refactor.
2. **Separate sync implementation for AgentCore** — simpler, some duplication.
   Iterate files in storage, `write_file()` each into engine on restore.
   List files in engine workspace, `read_file()` each on sync.

**Recommendation:** Option 1. The sync module should accept a `FileAccessor`
protocol (read, write, list, mkdir) that both MemFS and AgentCoreEngine satisfy.

---

### Phase 4: Edit Command Adapter ✅ DONE

**Goal**: Make the AI file editing (`agentbox/box/patch/`) work with
AgentCoreEngine.

**Completed 2026-06-18.** Option 1 (host-side edit) was implemented.

**What was done:**
- `AgentCoreBox.run_shell()` intercepts `edit` and `apply_patch` commands
- Intercepted commands run host-side using the patch module
  (`patcher.str_replace`, `patcher.insert`, `patcher.view`, etc.)
- File I/O uses `engine.read_file()`/`engine.write_file()` (AgentCore API)
- All other commands pass through to real bash in the MicroVM
- Path resolution: relative paths resolved against `_cwd` (/workspace)

**Key implementation details:**
- `_try_intercept(command)` → detects first word (`edit`, `apply_patch`)
- `_intercept_edit(command)` — mirrors `EditExec.run()` argument parsing
  using `shlex.split()` for proper shell quoting. All modes: str_replace,
  view, insert, create, info, diff.
- `_intercept_apply_patch(command)` — handles heredoc extraction (splits on
  `<<`, finds delimiter, extracts body). Also handles file-argument mode.
  Uses `parse_v4a_patch()` + `apply_v4a_diff()`. File delete uses `rm -f`
  via engine shell since AgentCore has no native delete API.
- Patch module imports are lazy (inside method bodies) to avoid startup cost

**Test results:** 42/42 new tests in `test/test_agentcore_intercept.py`:
- edit --view, --view --range, --old/--new (str_replace), --insert,
  --create, --create (exists), --info, --diff, missing file, no args,
  relative path resolution
- apply_patch heredoc (update), add file, delete file, no input
- Non-intercepted commands (echo, ls, pip, git status) pass through
- Path resolution: absolute, relative, dot-dot, simple name

---

### Phase 5: Git Adapter + Persistence for AgentCore ✅ DONE

**Goal**: Support git operations and S3 persistence in AgentCoreBox.

**Completed 2026-06-18.**

**Files created:**
- `agentbox/box/git/engine_sync.py` — engine-agnostic `push_to_store()`
  and `pull_from_store()` functions. Unlike `sync.py` (which uses
  `page.evaluate` for MemFS), this uses `engine.execute_shell()` with
  `find`, `base64`, `echo | base64 -d` for binary-safe file I/O.

**Files modified:**
- `agentbox/box/agentcore_box.py` — added:
  - `repo_id`, `workspace`, `auto_sync` constructor params
  - S3 restore on `start()` (pull_from_store if repo exists in storage)
  - Git init for new repos (real git, not isomorphic-git)
  - Auto-sync on `stop()` (push_to_store when auto_sync=True)
  - `git push`/`git pull` interception in `_try_intercept()`
  - `_git_push()`: find files → base64 → push to storage, track HEAD SHA
  - `_git_pull()`: pull from storage → base64 -d → write files, checkout
  - `_get_storage()` helper (reuses same env vars as git_box.py)

**Key design decisions:**
- Real git CLI: `git init`, `git checkout`, `git rev-parse HEAD` etc.
  run in the MicroVM's real bash — no isomorphic-git needed
- Binary-safe sync: `base64` encoding in shell for both push and pull
  (handles .git/objects, images, etc.)
- Same env vars as GitBox: `AGENTBOX_GIT_STORE`, `AGENTBOX_GIT_S3_BUCKET`, etc.
- Push tracking: `.agentbox-push-ref` in storage (same as git_box.py)
- `git push`/`git pull` with args rejected (same as git_box.py)
- All other git commands (status, log, commit, branch, diff) pass through

**Test results:** 27/27 in `test/test_agentcore_git.py`:
- git push/pull with repo_id + local storage
- git push/pull without repo_id (error)
- git push with args (rejected)
- git status/log/commit/branch pass through
- Auto-restore on start (existing storage)
- Git init for new repos
- Auto-sync on stop / auto_sync=False
- _get_storage() helper (local, s3 without bucket, invalid)
- Ephemeral box (no repo_id)

---

### Phase 6: BoxManager & Config Integration ✅ DONE

**Goal**: Wire everything together so the engine is selectable via config.

**Completed 2026-06-18.** (Implemented incrementally across Phases 1–3.)

**What was done:**
- `BoxManager.create_sandbox(engine=...)` — defaults to `"pyodide"`, accepts
  `"agentcore"`. Falls back to `AGENTBOX_ENGINE` env var.
- `SandboxInfo` tracks engine type; included in `to_dict()` response
- API routes (worker + orchestrator) pass `engine` through
- `CreateSandboxRequest` and `SandboxResponse` include `engine` field
- `pyproject.toml` has `[agentcore]` extra: `bedrock-agentcore>=1.15.0`, `boto3>=1.42`
- `AgentCoreBox` imported lazily in BoxManager to avoid hard dep

**Config env vars (all implemented):**
```bash
AGENTBOX_ENGINE=pyodide                      # or "agentcore"
AGENTBOX_AGENTCORE_REGION=us-east-1          # AWS region
AGENTBOX_AGENTCORE_SESSION_TIMEOUT=1800      # session idle timeout (seconds)
AGENTBOX_AGENTCORE_INTERPRETER_ID=           # custom interpreter ID (optional)
```

---

### Phase 7: Deep Agents API Compatibility (CRITICAL) ✅ DONE

**Goal**: Rewrite `AgentBoxBackend` to implement the current `BaseSandbox` /
`SandboxBackendProtocol` interface from `deepagents>=0.6`.

**Completed 2026-06-18.** See `deepagents-upgrade.md` for details.

**Summary:**
- Created `agentbox/langchain/sandbox.py` — `AgentBoxSandbox(BaseSandbox)`
- Sync httpx client; abstract methods: `execute()`, `upload_files()`,
  `download_files()`, `id` property
- Overridden: `read()`, `write()`, `edit()`, `ls_info()` (use REST API directly)
- Inherited: `glob_info()`, `grep_raw()` (work with AgentCoreEngine)
- `AgentBoxBackend` now emits `DeprecationWarning` on init
- Tests: 27 unit + 33 integration = 60/60 passing
- Dependencies: `deepagents>=0.6.10`, `langchain-core>=1.4.7` in pyproject.toml

#### The Gap (resolved)

Our installed `deepagents` is **0.4.3**. The latest stable is **0.6.10**
(June 13, 2026). The API has changed significantly between 0.4 and 0.6:

| Aspect | Our current `AgentBoxBackend` | Required `BaseSandbox` (0.6.x) |
|--------|-----------------------------|---------------------------------|
| **Inheritance** | Standalone class, no protocol | Must inherit `BaseSandbox(SandboxBackendProtocol, ABC)` |
| **`execute()`** | `execute(code, language=)` → custom `BackendResult` | `execute(command, *, timeout=None)` → `ExecuteResponse` (shell command) |
| **`id` property** | Missing | Required — unique sandbox identifier |
| **`upload_files()`** | Missing | Required — `list[tuple[str, bytes]]` → `list[FileUploadResponse]` |
| **`download_files()`** | Missing | Required — `list[str]` → `list[FileDownloadResponse]` |
| **Return types** | Custom `BackendResult` | `ExecuteResponse`, `ReadResult`, `WriteResult`, `EditResult`, `LsResult`, `GlobResult`, `GrepResult` |
| **`read()`** | Custom `read_file()` | Inherited from `BaseSandbox` — uses `execute()` server-side Python script with pagination |
| **`write()`** | Custom `write_file()` | Inherited from `BaseSandbox` — uses `upload_files()` + existence check |
| **`edit()`** | Not exposed | Inherited from `BaseSandbox` — server-side str_replace via `execute()` |
| **`ls()`** | Custom `list_files()` | Inherited from `BaseSandbox` — via `execute()` |
| **`glob()`** | Missing | Inherited from `BaseSandbox` |
| **`grep()`** | Missing | Inherited from `BaseSandbox` |
| **Async variants** | Custom async methods | `aexecute()`, etc. — async versions of all methods |

#### What `BaseSandbox` Provides for Free

If we inherit from `BaseSandbox` and implement only the 4 abstract methods,
we get **all file operations for free**:

| Method | Source | How it works |
|--------|--------|-------------|
| `ls()` | Inherited | Runs `python3 -c "import os; os.scandir()"` via `execute()` |
| `read()` | Inherited | Runs paginated Python script via `execute()` |
| `write()` | Inherited | Existence check via `execute()`, then `upload_files()` |
| `edit()` | Inherited | str_replace via server-side Python script |
| `glob()` | Inherited | `python3 -c "import glob"` via `execute()` |
| `grep()` | Inherited | `rg` or Python fallback via `execute()` |

This is extremely convenient — we only need to implement the **execution
and file transfer** primitives. Everything else is derived.

#### New `AgentBoxSandbox` Implementation

```python
# agentbox/langchain/sandbox.py (NEW FILE — replaces backend.py)

from __future__ import annotations

import asyncio
from typing import Optional

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

from agentbox.client import AgentBoxClient, Sandbox


class AgentBoxSandbox(BaseSandbox):
    """AgentBox sandbox conforming to Deep Agents SandboxBackendProtocol.

    Wraps an AgentBoxClient to execute shell commands and manage files
    in an AgentBox sandbox (PyodideEngine or AgentCoreEngine).

    The caller manages the client lifecycle. The sandbox is lazily created
    on first use.

    Example::

        from agentbox.langchain import AgentBoxSandbox
        from deepagents import create_deep_agent

        backend = AgentBoxSandbox(base_url="http://localhost:8090")
        agent = create_deep_agent(
            model=...,
            backend=backend,
            system_prompt="You are a coding assistant.",
        )
        result = agent.invoke({"messages": [...]})
        backend.close_sync()
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8090",
        *,
        token: Optional[str] = None,
        box_type: str = "mem",
        engine: Optional[str] = None,
    ):
        self._client = AgentBoxClient(base_url, token=token)
        self._box_type = box_type
        self._engine = engine
        self._sandbox: Optional[Sandbox] = None

    def _ensure_sandbox(self) -> Sandbox:
        """Lazily create sandbox (sync)."""
        if self._sandbox is None or self._sandbox.state == "destroyed":
            self._sandbox = asyncio.run(
                self._client.create_sandbox(
                    box_type=self._box_type,
                    engine=self._engine,
                )
            )
        return self._sandbox

    @property
    def id(self) -> str:
        sandbox = self._ensure_sandbox()
        return sandbox.sandbox_id

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Execute a shell command in the AgentBox sandbox."""
        sandbox = self._ensure_sandbox()
        result = asyncio.run(sandbox.execute(command, language="shell"))
        output = result.stdout
        if result.stderr:
            output = output + result.stderr if output else result.stderr
        return ExecuteResponse(
            output=output or "",
            exit_code=result.exit_code,
            truncated=False,
        )

    def upload_files(
        self,
        files: list[tuple[str, bytes]],
    ) -> list[FileUploadResponse]:
        """Upload files to the AgentBox sandbox."""
        sandbox = self._ensure_sandbox()
        responses = []
        for path, content in files:
            ok = asyncio.run(sandbox.write_file(path, content.decode("utf-8")))
            responses.append(
                FileUploadResponse(path=path, error=None if ok else "write_failed")
            )
        return responses

    def download_files(
        self,
        paths: list[str],
    ) -> list[FileDownloadResponse]:
        """Download files from the AgentBox sandbox."""
        sandbox = self._ensure_sandbox()
        responses = []
        for path in paths:
            content = asyncio.run(sandbox.read_file(path))
            if content is not None:
                responses.append(
                    FileDownloadResponse(
                        path=path,
                        content=content.encode("utf-8"),
                        error=None,
                    )
                )
            else:
                responses.append(
                    FileDownloadResponse(
                        path=path, content=None, error="file_not_found"
                    )
                )
        return responses

    def close_sync(self) -> None:
        """Clean up sandbox and client."""
        if self._sandbox:
            asyncio.run(self._sandbox.destroy())
        asyncio.run(self._client.close())
```

#### Key Design Decisions

1. **Inherit from `BaseSandbox`** — get `read()`, `write()`, `edit()`, `ls()`,
   `glob()`, `grep()` for free. Only implement `execute()`, `upload_files()`,
   `download_files()`, and `id`.

2. **`execute()` runs shell commands** — the Deep Agents contract is
   `execute(command)` = shell command, not Python code. For AgentBox's Pyodide
   engine, this maps to `run_shell()`. For AgentCore engine, this maps to
   real bash.

3. **Sync-first** — `BaseSandbox` methods are sync by default. Deep Agents
   calls them from a sync context. Our client SDK is async, so we wrap with
   `asyncio.run()` (or `asyncio.get_event_loop().run_until_complete()`).
   Need to handle the case where an event loop is already running (Jupyter)
   via `nest_asyncio` or `anyio.from_thread`.

4. **Keep `AgentBoxBackend`** as deprecated alias for backward compat.

5. **Keep `AgentBoxToolkit`** — the LangChain `BaseTool` tools are separate
   from the Deep Agents `BaseSandbox` protocol. Both can coexist:
   - `AgentBoxSandbox` → for `create_deep_agent(backend=...)` 
   - `AgentBoxToolkit` → for `create_react_agent(tools=...)` / LangGraph

#### Dependency Update

```toml
# pyproject.toml
[project.optional-dependencies]
langchain = [
    "httpx>=0.25",
    "langchain-core>=0.3.56",
    "deepagents>=0.6.10",
]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "httpx>=0.25",
    "asgi-lifespan>=2.0",
    "deepagents>=0.6.10",
    "langchain-core>=0.3.56",
    "build",
    "twine",
]
```

The `deepagents` package went from requiring `langchain`, `langchain-anthropic`,
`langchain-google-genai`, `wcmatch` in 0.4.x. Check what 0.6.10 requires to
avoid dependency conflicts.

#### Migration Plan

1. `pip install deepagents==0.6.10` in the dev environment
2. Check for breaking imports (`from deepagents.backends.protocol import ...`)
3. Create `agentbox/langchain/sandbox.py` with `AgentBoxSandbox(BaseSandbox)`
4. Keep `agentbox/langchain/backend.py` with deprecation warning
5. Update `agentbox/langchain/__init__.py` to export `AgentBoxSandbox`
6. Update all tests that use `AgentBoxBackend`
7. Run `langchain-tests.SandboxIntegrationTests` if available
8. Verify with `create_deep_agent(backend=AgentBoxSandbox(...))` end-to-end

---

### Phase 8: Testing

**Unit tests:**
- `test/test_engine_protocol.py` — verify both engines satisfy protocol
- `test/test_agentcore_engine.py` — mock `CodeInterpreter`, test execute/files
- `test/test_agentcore_box.py` — mock engine, test persistence/edit/git intercept

**Integration tests (require AWS credentials):**
- `test/integration/test_agentcore_live.py` — real AgentCore session
  - Start session, execute Python, verify stdout
  - Write file, read back, verify content
  - Shell command (ls, pwd)
  - File persistence: write → stop → start new session → verify restored
  - Git: init → commit → push → new session → pull → verify

**Existing test suites must remain green:**
- 35/35 E2E (Docker Compose with PyodideEngine)
- 19/19 Client SDK
- 27/27 LangChain integration

---

## 5. File Accessor Protocol (for sync abstraction)

To share persistence logic between PyodideEngine (MemFS) and AgentCoreEngine:

```python
# agentbox/engine/file_accessor.py
from typing import Protocol

class FileAccessor(Protocol):
    """Unified file access interface for sync/persistence layer."""

    async def read_file(self, path: str) -> bytes | None: ...
    async def write_file(self, path: str, content: bytes) -> None: ...
    async def list_dir(self, path: str) -> list[str]: ...
    async def mkdir_p(self, path: str) -> None: ...
    async def exists(self, path: str) -> bool: ...
```

**Implementations:**
- `MemFSAccessor` — wraps `MemFS` page calls (existing behavior)
- `AgentCoreAccessor` — wraps `AgentCoreEngine` file methods

The `git/sync.py` module would accept a `FileAccessor` instead of directly
calling Playwright page evaluations.

---

## 5a. FileBox — Auto-Persisted Sandbox

### Motivation

The three current sandbox modes leave a gap:

| | **MemBox** | **GitBox** | **FileBox** (new) |
|---|---|---|---|
| Persistence | None | Explicit `git push` | **Automatic** (git under the hood) |
| Data loss risk | Always (ephemeral) | Reaped before push | **None** (auto-commit on stop) |
| Concurrent access | N/A | Branch isolation + explicit merge | **Branch isolation + auto-merge** |
| Git visible to agent? | N/A | Yes — agent runs git commands | **No** — fully transparent |
| Agent complexity | None | Must know git | **None** |
| Best for | Throwaway compute | Explicit version control | **Persistent workspaces (any scale)** |

Most agent tasks don't need git history — they need "write a file, come
back later, file is still there." FileBox provides this with zero agent
ceremony: no `git add`, no `git commit`, no `git push`.

### Key Insight: FileBox IS GitBox Under the Hood

Rather than building a separate persistence layer, **FileBox is GitBox
with transparent auto-commit/push/merge.** The agent never sees git, but
all the git machinery runs automatically. This gives FileBox users:

- **Persistence** — auto-commit + auto-push, no data loss
- **Concurrency safety** — each sandbox gets its own branch, auto-merged
- **Version history for free** — every stop is a commit, undo is trivial
- **No new code** — reuses all existing GitBox/isomorphic-git infrastructure

### Lifecycle

```
FileBox.start():
  1. Pull from S3 (same as GitBox)
  2. Auto-create a working branch: "session-{sandbox_id}"
     git checkout -b session-abc123
  3. Agent sees /workspace with their files. No git awareness needed.

During work:
  - Agent writes files normally (write_file, shell redirection, etc.)
  - No git commands needed. Agent doesn't know git exists.

FileBox.stop():
  1. git add -A
  2. git commit -m "auto: session abc123"
  3. git checkout main
  4. git merge session-abc123 (fast-forward or recursive)
  5. git push (sync to S3)
  6. Tear down sandbox
```

### Option: Separated Git Directory

By default, `.git/` lives inside `/workspace`, making it visible to the
agent (`ls -a` shows it). This has downsides:

- Agent may get confused by `.git/` or try to use it
- `.git/` history grows over time (bloats S3 sync)
- Need a `.gitignore` to exclude `node_modules/`, `__pycache__/`, etc.

**Alternative: split worktree.** Keep the git repo outside the workspace:

```
/var/agentbox/.git/   ← git internals (hidden from agent)
/workspace/           ← agent's working directory (clean, no .git)
```

All git commands use `--git-dir` and `--work-tree` flags:

```bash
git --git-dir=/var/agentbox/.git --work-tree=/workspace init
git --git-dir=/var/agentbox/.git --work-tree=/workspace add -A
git --git-dir=/var/agentbox/.git --work-tree=/workspace commit -m "auto"
```

This works on both engines:

- **AgentCore (real git)** — native `--git-dir` / `--work-tree` support
- **Pyodide (isomorphic-git)** — the `git.init()`, `git.add()`, etc.
  functions accept separate `dir` (worktree) and `gitdir` parameters

Benefits:

- Agent sees a clean `/workspace` with no git artifacts
- `.git/` can be excluded from S3 sync of the workspace (synced
  separately or stored as a distinct S3 prefix)
- Prevents agents from accidentally running `git reset --hard` or
  other destructive git commands in their workspace

**Recommendation**: Pursue the separated gitdir approach for FileBox.
GitBox (where the agent explicitly uses git) keeps `.git/` in the
workspace as expected.

### Concurrency — Solved for Free

Because each FileBox sandbox gets its own branch, parallel access to
the same `persist_id` is safe:

```
Agent A: FileBox(persist_id="project-x")
  → branch: session-aaa
  → works on files independently

Agent B: FileBox(persist_id="project-x")
  → branch: session-bbb
  → works on files independently

Agent A stops:
  → commit on session-aaa
  → merge session-aaa → main (fast-forward, no conflict)
  → push

Agent B stops:
  → commit on session-bbb
  → pull latest main (has A's changes now)
  → merge session-bbb → main
  → if conflict: auto-resolve with last-writer-wins strategy
    (or flag conflict for caller — configurable)
  → push
```

This is the feature-branch model applied transparently. The agent never
knows it's happening.

### Conflict Resolution Strategy

When auto-merge encounters conflicts:

| Strategy | Behavior | Config |
|----------|----------|--------|
| **last-writer-wins** (default) | Accept incoming changes, discard conflicting lines from main | `merge_strategy="theirs"` |
| **first-writer-wins** | Keep main's version, discard session changes | `merge_strategy="ours"` |
| **fail** | Stop returns error, caller must resolve | `merge_strategy="fail"` |
| **caller-merge** | Push branch only, let caller merge externally | `merge_strategy="branch-only"` |

For most FileBox use cases (single-agent, sequential sessions),
conflicts never occur — merges are always fast-forwards.

### Implementation

```python
# agentbox/box/file_box.py

class FileBox(GitBox):
    """Persistent sandbox with transparent auto-commit/push/merge.

    Wraps GitBox so the agent never sees git. All persistence happens
    automatically on start/stop.

    Usage:
        async with FileBox(persist_id="project-alpha") as box:
            await box.run_shell('echo "hello" > /workspace/notes.txt')
            # stop → auto-commit, auto-merge to main, auto-push
        # Later:
        async with FileBox(persist_id="project-alpha") as box:
            content = await box.read_file("/workspace/notes.txt")
            # → "hello"
    """

    def __init__(self, persist_id: str, workspace="/workspace",
                 merge_strategy: str = "theirs", **kwargs):
        super().__init__(
            repo_id=persist_id,
            workspace=workspace,
            auto_sync=False,  # We handle sync ourselves
            **kwargs,
        )
        self._merge_strategy = merge_strategy
        self._session_branch = None

    async def start(self):
        await super().start()  # GitBox.start() handles pull + restore

        # Create session branch for isolation
        self._session_branch = f"session-{self.sandbox_id}"
        await self.run_shell(f"git checkout -b {self._session_branch}")

    async def stop(self):
        # Auto-commit all changes
        await self.run_shell("git add -A")
        status = await self.run_shell("git status --porcelain")
        if status.get("stdout", "").strip():
            await self.run_shell(
                f'git commit -m "auto: {self._session_branch}"'
            )

            # Merge back to main
            await self.run_shell("git checkout main")
            merge_result = await self.run_shell(
                f"git merge {self._session_branch}"
            )

            # Handle conflicts based on strategy
            if merge_result.get("exit_code", 0) != 0:
                await self._resolve_conflicts()

            # Push to S3
            await self.run_shell("git push")

        await super().stop()  # GitBox.stop() handles teardown

    async def _resolve_conflicts(self):
        if self._merge_strategy == "theirs":
            # Accept session's changes over main
            await self.run_shell(
                f"git merge --abort && "
                f"git merge -X theirs {self._session_branch}"
            )
        elif self._merge_strategy == "ours":
            await self.run_shell(
                f"git merge --abort && "
                f"git merge -X ours {self._session_branch}"
            )
        elif self._merge_strategy == "fail":
            await self.run_shell("git merge --abort")
            raise RuntimeError("Merge conflict — caller must resolve")
        elif self._merge_strategy == "branch-only":
            await self.run_shell("git merge --abort")
            # Just push the branch, don't merge
            await self.run_shell(f"git checkout {self._session_branch}")
            await self.run_shell("git push")
```

### Changes Required

- **`FileBox` extends `GitBox`** — no new persistence layer, no separate
  sync code. All git infrastructure is reused.
- **`BoxManager`** — accept `box_type="file"`, create `FileBox`.
- **Orchestrator** — `CreateSandboxRequest` accepts `persist_id` (alias
  for `repo_id`).
- **isomorphic-git merge** — verify `git merge -X theirs/ours` works in
  isomorphic-git. If not, implement the merge strategies as host commands
  using the isomorphic-git JS API directly.
- **Reaper safety** — the idle sandbox reaper must call `stop()` (which
  triggers auto-commit + push) rather than hard-killing.

### FileBox vs GitBox — When to Use Which

Both use git under the hood. The difference is **visibility**:

| | **FileBox** | **GitBox** |
|---|---|---|
| Git visible to agent? | **No** — fully transparent | **Yes** — agent runs git commands |
| Commits | Auto on stop | Agent runs `git commit` |
| Push/pull | Auto on stop/start | Agent runs `git push/pull` |
| Branching | Auto session branches | Agent manages branches explicitly |
| Merge | Auto with configurable strategy | Agent/caller merges explicitly |
| Use when | Agent doesn't know or care about git | Agent needs fine-grained version control |

| Use case | Recommended | Why |
|----------|-------------|-----|
| Single agent, persistent workspace | **FileBox** | Auto-sync, zero ceremony |
| Parallel agents on shared code | **FileBox** or **GitBox** | Both use branches; FileBox auto-merges, GitBox gives caller control |
| Agent needs `git log/diff/blame` | **GitBox** | Agent must see git |
| Caller wants explicit merge control | **GitBox** | `merge_strategy="branch-only"` also works with FileBox |
| Throwaway computation | **MemBox** | No persistence needed |

---

## 5b. Persist ID Ownership

### Design Philosophy

AgentBox is a **dumb execution + storage layer**. It does not maintain a
registry of users, projects, or workspaces. It has no concept of "which
persist_ids exist for which user."

**The calling application owns the mapping.** The caller decides the
`persist_id`, tracks it in its own database, and passes it when creating
sandboxes. AgentBox's only responsibilities are:

1. **Store files** under the given `persist_id` (scoped to S3 key)
2. **Restore files** when a sandbox is created with the same `persist_id`
3. **Scope by tenant** using the JWT `sub` claim (security boundary only)

### How It Works

```
Caller's DB:
  user "alice" → projects: ["report-q2", "experiment-3"]

Caller creates sandbox:
  POST /sandboxes {box_type: "file", persist_id: "report-q2"}
  Authorization: Bearer <JWT with sub: "alice">

AgentBox:
  → S3 key: repos/alice/report-q2/...
  → Doesn't know or care what "alice" or "report-q2" mean
  → Just stores and retrieves files at that path
```

### What AgentBox Provides

- **`persist_id` is an opaque key** — AgentBox treats it as a string.
  The caller can use UUIDs, slugs, paths, whatever.
- **JWT `sub` scoping** — prevents tenant cross-access at the storage
  layer. User A cannot access user B's files even if they guess the
  `persist_id`. This is a security boundary, not a feature.
- **Idempotent restore** — creating a sandbox with an existing
  `persist_id` restores files. Creating with a new `persist_id` starts
  fresh. AgentBox doesn't distinguish between these cases.
- **No lifecycle management** — AgentBox does not track, list, or
  garbage-collect persist_ids. The caller is responsible for cleanup
  (calling `DELETE /sandboxes/{id}` or directly managing S3 objects)

### Usage Patterns

The opaque `persist_id` supports multiple access models simultaneously
from the same AgentBox deployment. The calling application decides the
mapping — AgentBox imposes no user model.

**Pattern 1: N Private Workspaces per User**

Each user has their own set of workspaces. The calling app maintains a
`user → [workspace_ids]` mapping in its own database.

```
App DB: alice → ["analysis-q2", "experiment-7", "draft-paper"]

POST /sandboxes {box_type: "file", persist_id: "analysis-q2"}
JWT sub: "alice"
→ S3: repos/alice/analysis-q2/...

Only alice's app sessions ever reference these persist_ids.
```

**Pattern 2: N Shared Workspaces (e.g. Slack Channels)**

Workspaces are shared among channel members. The Slack channel_id is
the `persist_id`. Access control is delegated to Slack — the Slack app
checks channel membership before creating a sandbox.

```
Slack app: user invokes agent in #data-team (C05XXXXX)
  → App verifies user is member of C05XXXXX (users.conversations API)
  → POST /sandboxes {box_type: "file", persist_id: "C05XXXXX"}
  JWT sub: "T01WORKSPACE" (Slack team_id)
  → S3: repos/T01WORKSPACE/C05XXXXX/...

Any team member in that channel can access the same workspace.
No AgentBox-side access control needed — Slack is the ACL.
```

**Pattern 3: Mixed Private + Shared**

A single calling app can use both patterns. Private workspaces use
user-scoped persist_ids, shared workspaces use channel/team-scoped ids.
AgentBox doesn't distinguish — they're all just opaque keys under the
same JWT tenant.

```
Private: persist_id = "user:{user_id}:{workspace_name}"
Shared:  persist_id = "channel:{channel_id}"
Team:    persist_id = "team:{team_id}:{project_name}"

All scoped under the same JWT sub (e.g. org_id).
The calling app decides who can reference which persist_id.
```

---

## 6. Migration & Backward Compatibility

### What does NOT change:
- `Box` ABC interface
- Client SDK (`AgentBoxClient`, `Sandbox`)
- REST API contract (all existing endpoints)
- LangChain `AgentBoxToolkit` tools (BaseTool-based)
- Docker Compose stack behavior (defaults to PyodideEngine)

### What changes (internal only):
- `CodeExecutorBox` internally composes `PyodideEngine` (delegation, not inheritance)
- `BoxManager.create_sandbox()` gains `engine` parameter (optional, backward compat)
- New `agentbox/engine/` package
- New `[agentcore]` install extra
- New `AgentBoxSandbox(BaseSandbox)` replaces `AgentBoxBackend` for Deep Agents
- `deepagents` dependency bumped from `>=0.4` to `>=0.6.10`
- New `FileBox` sandbox type (`box_type="file"`)
- `persist_id` accepted as alias for `repo_id` in create sandbox request
- Sync code moved from `agentbox/box/git/sync.py` to `agentbox/box/sync.py`

### Deprecation plan:
- `AgentBoxBackend` deprecated in favor of `AgentBoxSandbox`. Will emit
  `DeprecationWarning` and remain functional for 2 minor versions.
- Both execution engines are first-class.
- If AgentCore becomes the primary production target, PyodideEngine remains
  supported for local development.

---

## 7. Deployment Model with AgentCoreEngine

When using AgentCoreEngine, the production deployment **simplifies dramatically**:

```
Before (PyodideEngine, self-hosted on AWS):
┌─────────────┐     ┌───────────┐     ┌──────────────────┐
│ ALB         │────→│ Orchestr. │────→│ Worker (Chromium) │ × N
│             │     │ (FastAPI) │     │ ~1.5GB image      │
└─────────────┘     │ + Redis   │     └──────────────────┘
                    └───────────┘

After (AgentCoreEngine on AWS):
┌─────────────┐     ┌───────────────────────────────────┐
│ ALB         │────→│ Orchestrator (FastAPI + boto3)     │
│             │     │ ~200MB image, no Chromium          │
└─────────────┘     │ Routes to AgentCore via AWS SDK    │
                    └───────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────────────┐
                    │ AWS AgentCore (managed)  │
                    │ MicroVM per sandbox      │
                    │ Pay-per-use              │
                    └─────────────────────────┘
```

- No Chromium workers to manage
- No Redis (unless needed for routing; with AgentCore, the orchestrator can
  be a single stateless instance)
- Docker image drops from ~1.5GB to ~200MB
- Auto-scales via AgentCore (each sandbox = new MicroVM, no pool management)
- Cost: only pay when agent is actually computing

---

## 8. Priority & Effort Estimates

| Phase | Effort | Risk | Dependencies | Status |
|-------|--------|------|-------------|--------|
| 1. Extract engine interface | ~1 day (actual) | Low (pure refactor) | None | ✅ Done |
| 2. AgentCoreEngine | ~0.5 day (actual) | Low | Phase 1 | ✅ Done |
| 3. AgentCoreBox | ~0.5 day (actual) | Low | Phase 2 | ✅ Done |
| 4. Edit adapter | ~0.5 day (actual) | Low | Phase 3 | ✅ Done |
| 5. Git adapter / persistence | ~0.5 day (actual) | Low | Phase 3 | ✅ Done |
| 6. Config & BoxManager | done w/ Phases 1–3 | — | — | ✅ Done |
| 7. Deep Agents API compat | ~2 days (actual) | **High** (breaking API) | Phase 1+ | ✅ Done |
| 8. Integration testing | ~0.5 day (actual) | Medium (needs AWS creds) | All above | ✅ Done |

**All phases complete.**

Phases 1–8 are **all done**. The engine abstraction is fully functional
with both PyodideEngine and AgentCoreEngine, including:
- Host-side edit/apply_patch interception
- Git push/pull interception with S3 persistence
- Auto-restore on start, auto-sync on stop
- Live integration tested with AWS Bedrock AgentCore (39/39)
- Deep Agent E2E: `create_deep_agent(backend=AgentBoxSandbox(..., engine="agentcore"))` ✓

All existing tests pass (zero regressions), plus 156 new AgentCore tests:
- 48 mocked engine tests
- 42 mocked intercept tests
- 27 mocked git/persistence tests
- 39 live integration tests (AWS_PROFILE=cardiffprod)
- 2 Deep Agent E2E tests via docker-compose (AgentCore engine)

### Key fixes for AgentCore Docker deployment:
- Orchestrator proxy timeout increased 30s → 120s (MicroVM provisioning)
- `files/write` and `files/read` API routes handle boxes without `memfs`
- `AgentCoreEngine.write_file` uses SDK-relative path for `mkdir -p`
- `AgentCoreBox._rewrite_workspace_paths()` translates `/workspace/` → actual MicroVM path
- `AgentBoxSandbox.write()` uses files/write API instead of `cat` heredoc
- Explicit MinIO credentials (`AGENTBOX_GIT_S3_ACCESS_KEY/SECRET_KEY`) avoid conflict with AWS creds

---

## 9. Open Questions

1. ~~**Does `bedrock-agentcore` SDK support async?**~~ **RESOLVED**: No, SDK
   is sync-only (boto3). All calls wrapped in `asyncio.to_thread()`.

2. ~~**AgentCore session timeout**~~ **RESOLVED**: Configurable via
   `AGENTBOX_AGENTCORE_SESSION_TIMEOUT` env var, defaults to 1800s (30 min).
   SDK's `start()` accepts `session_timeout_seconds` param.

3. **File sync granularity** — sync all files on stop, or track dirty files?
   For MVP: sync all files in /workspace on stop. Optimize later.

4. **ShellExecutor builtins in AgentCore mode** — which builtins still apply?
   - `edit` → intercepted host-side (keep)
   - `cd`, `pwd`, `ls`, `cat`, etc. → pass through to real bash
   - `pip install` → pass through (real pip)
   - Custom builtins (file_info, glob_info, outline) → intercept host-side

5. **Cost control** — should AgentBox enforce a max session budget?
   AgentCore charges per-second. Could add per-sandbox cost ceiling.

6. **Concurrent sandboxes** — AgentCore allows multiple simultaneous sessions.
   BoxManager pool limits still apply (configurable). Each sandbox = one
   AgentCore session.

7. **`BaseSandbox.execute()` runs shell commands, not Python** — Deep Agents'
   `execute()` = shell command string. Our Pyodide engine's `run_shell()` runs
   through tree-sitter-bash + builtins, which is synthetic bash. The inherited
   `BaseSandbox.read()`/`write()`/`edit()` methods run Python scripts via
   `execute()` — these scripts must work in our virtual shell. **Risk**: our
   shell may not support the exact Python invocations `BaseSandbox` generates
   (e.g. `python3 -c "..."` with heredoc stdin). If not, we may need to
   override `read()`/`write()`/`edit()` with direct MemFS implementations
   for PyodideEngine and only use the inherited versions for AgentCoreEngine.

8. **`deepagents` 0.6.10 transitive dependencies** — 0.4.x required
   `langchain`, `langchain-anthropic`, `langchain-google-genai`, `wcmatch`.
   Need to check what 0.6.10 pulls in and whether it conflicts with our
   existing deps. May need to adjust version bounds.

---

## 10. Success Criteria

- [x] `ExecutionEngine` protocol defined and documented
- [x] `PyodideEngine` wraps existing code; all existing tests pass unchanged
- [x] `engine` param plumbed through API → orchestrator → worker → BoxManager
- [x] `AgentCoreEngine` passes unit tests with mocked CodeInterpreter (48/48)
- [x] `AgentCoreBox` supports: execute, shell, read/write files
- [x] `AgentCoreBox` persistence (S3 restore/sync on start/stop, 27/27 tests)
- [x] Edit command works in AgentCore mode (host-side intercept, 42/42 tests)
- [x] Git push/pull works in AgentCore mode (S3 sync, 27/27 tests)
- [x] `AGENTBOX_ENGINE=agentcore` selects AgentCoreEngine in BoxManager
- [x] Integration test with live AgentCore session passes (39/39)
- [x] Existing Docker Compose stack unaffected (PyodideEngine default)
- [x] `[agentcore]` extra in pyproject.toml (`bedrock-agentcore>=1.15.0`)
- [x] `AgentBoxSandbox(BaseSandbox)` passes `SandboxBackendProtocol` checks
- [x] `AgentBoxSandbox.execute()` returns correct `ExecuteResponse`
- [x] `upload_files()` / `download_files()` work via AgentBox client SDK
- [x] `create_deep_agent(backend=AgentBoxSandbox(...))` works end-to-end (2/2 tests, both Pyodide and AgentCore engines)
- [x] `deepagents>=0.6.10` in pyproject.toml, all existing tests still pass
- [x] `AgentBoxBackend` emits deprecation warning but remains functional
- [ ] `FileBox` auto-syncs to S3 on stop; files survive sandbox restart
- [ ] `box_type="file"` accepted by BoxManager and orchestrator
- [ ] Sync code shared between FileBox and GitBox (not duplicated)
