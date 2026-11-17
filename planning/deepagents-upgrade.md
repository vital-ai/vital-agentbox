# Deep Agents Upgrade: 0.4 → 0.6

**Date**: 2026-06-18
**Priority**: Do this FIRST, before engine extraction.
**Estimated effort**: 2–3 days

---

## Why First

- The Deep Agents `BaseSandbox` protocol is the **official integration point**
  for `create_deep_agent()`. Our current `AgentBoxBackend` doesn't implement it.
- This work is **independent** of the engine extraction (Phases 1–6 in
  `execution-engine-extraction.md`). It uses the existing client SDK.
- The upgrade unblocks using AgentBox with Deep Agents immediately, regardless
  of which execution engine is active.
- Doing it first gives us a working `create_deep_agent(backend=...)` demo —
  a much more compelling proof of viability than internal refactoring.

---

## Current State

| Item | Current | Target |
|------|---------|--------|
| `deepagents` version | 0.4.3 installed, `>=0.4` pinned | 0.6.10, `>=0.6.10` pinned |
| `langchain-core` version | 1.2.14 installed, `>=0.2` pinned | 1.4.8 (pulled by deepagents 0.6.10), `>=1.4.7` pinned |
| Backend class | `AgentBoxBackend` (custom, no protocol) | `AgentBoxSandbox(BaseSandbox)` |
| Integration entry | `AgentBoxBackend(base_url=...)` | `AgentBoxSandbox(base_url=...)` then `create_deep_agent(backend=...)` |
| Tests | 27/27 LangChain tests pass | Must remain green + new BaseSandbox tests |

### What deepagents 0.6.10 Pulls In

```
deepagents==0.6.10 requires:
  langchain-core    >=1.4.7, <2.0.0   (upgrade from 1.2.14)
  langchain         >=1.3.9, <2.0.0
  langchain-anthropic >=1.4.6, <2.0.0
  langchain-google-genai >=4.2.5, <5.0.0
  langsmith         >=0.8.11
  wcmatch           >=10.1
  langgraph         >=1.2.5, <1.3.0   (transitive via langchain)
```

Key upgrades: `langchain-core` jumps from 1.2.14 → 1.4.8. The `BaseSandbox`
class and `SandboxBackendProtocol` are in `deepagents.backends.sandbox` and
`deepagents.backends.protocol` respectively.

---

## Step-by-Step Plan

### Step 1: Upgrade Dependencies

```bash
pip install deepagents==0.6.10
```

Then check for import breakage:
```bash
python -c "from deepagents.backends.protocol import SandboxBackendProtocol, ExecuteResponse, FileUploadResponse, FileDownloadResponse"
python -c "from deepagents.backends.sandbox import BaseSandbox"
python -c "from agentbox.langchain import AgentBoxBackend"  # should still work
```

Update `pyproject.toml`:
```toml
langchain = [
    "httpx>=0.25",
    "langchain-core>=1.4.7",
    "deepagents>=0.6.10",
]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "httpx>=0.25",
    "asgi-lifespan>=2.0",
    "deepagents>=0.6.10",
    "langchain-core>=1.4.7",
    "build",
    "twine",
]
```

**Verify**: existing 27 LangChain tests still pass (the old `AgentBoxBackend`
class doesn't import from deepagents, so it should survive the upgrade).

---

### Step 2: Create `AgentBoxSandbox(BaseSandbox)`

New file: `agentbox/langchain/sandbox.py`

Must implement 4 abstract methods + 1 property:

```python
class AgentBoxSandbox(BaseSandbox):
    # ABSTRACT — must implement:
    execute(command, *, timeout=None) -> ExecuteResponse
    upload_files(files: list[tuple[str, bytes]]) -> list[FileUploadResponse]
    download_files(paths: list[str]) -> list[FileDownloadResponse]

    @property
    id -> str
```

Everything else (`read`, `write`, `edit`, `ls`, `glob`, `grep`) is inherited
from `BaseSandbox` and works by calling `execute()` with Python scripts.

#### Async Challenge

`BaseSandbox` methods are **sync**. Our `AgentBoxClient` is **async**.

Options:
1. **`asyncio.run()` wrappers** — simple but fails if event loop already running
2. **`nest_asyncio`** — we already use this pattern in the client SDK
3. **Sync HTTP client** — create a sync variant of AgentBoxClient using `httpx.Client`
4. **`anyio.from_thread.run()`** — if called from a thread without a loop

**Recommendation**: Option 3 (sync httpx client) for cleanest implementation.
`BaseSandbox` is sync-first by design, so our backend should be too. This
avoids all event loop gymnastics.

Alternatively, start with Option 1 + `nest_asyncio` for speed, refactor later.

#### Key Implementation Detail: `execute()` = Shell

Deep Agents' `execute(command)` runs a **shell command**, not Python code.
The inherited `BaseSandbox.read()`, `write()`, `edit()` methods generate
Python scripts like:

```bash
python3 -c "
import os, sys, base64, json
path = base64.b64decode('...').decode('utf-8')
...
" 2>&1
```

For this to work through AgentBox, we call `sandbox.execute(command, language="shell")`.

**Risk with Pyodide engine**: Our tree-sitter-bash shell executor may not
support `python3 -c "..."` because it's a virtual shell — there's no real
Python binary. If inherited methods fail:
- **Short-term**: Override `read()`, `write()`, `edit()`, `ls()` in
  `AgentBoxSandbox` to use our existing REST endpoints directly.
- **Long-term**: Once AgentCoreEngine is in place, the inherited methods
  work perfectly (real bash + real Python).

For the Pyodide path, we should override the file operation methods to call
the AgentBox REST API directly rather than relying on `execute()` to run
Python scripts. This is actually **better** because it avoids the round-trip
of executing Python inside the sandbox just to read a file.

---

### Step 3: Override File Operations for AgentBox

Since AgentBox already has native file operations via the REST API, override
the `BaseSandbox` file methods to use them directly:

Actual return types (verified against 0.4.3, recheck after 0.6.10 install):

```python
# Abstract (must implement):
execute(command, *, timeout=None) -> ExecuteResponse(output: str, exit_code: int|None, truncated: bool)
upload_files(files) -> list[FileUploadResponse(path: str, error: Optional[Literal[...]])]
download_files(paths) -> list[FileDownloadResponse(path: str, content: bytes|None, error: Optional[...])]
id -> str (property)

# Concrete (inherited, can override):
read(file_path, offset=0, limit=2000) -> str              # plain string, NOT a structured result
write(file_path, content) -> WriteResult(error, path, files_update)
edit(file_path, old_string, new_string, replace_all) -> EditResult(error, path, files_update, occurrences)
ls_info(path) -> list[FileInfo]                            # FileInfo is a TypedDict(path, is_dir, size, modified_at)
glob_info(pattern, path="/") -> list[FileInfo]
grep_raw(pattern, path=None, glob=None) -> list[GrepMatch] | str  # GrepMatch is TypedDict(path, line, text)
```

Override implementations using AgentBox REST API:

```python
class AgentBoxSandbox(BaseSandbox):
    def read(self, file_path, offset=0, limit=2000):
        """Read via AgentBox REST API instead of execute()."""
        content = self._sync_client.read_file(self._sandbox_id, file_path)
        if content is None:
            return f"Error: file '{file_path}' not found"
        # Apply offset/limit (BaseSandbox contract: return str)
        lines = content.splitlines(keepends=True)
        return "".join(lines[offset:offset + limit])

    def write(self, file_path, content):
        """Write via AgentBox REST API."""
        ok = self._sync_client.write_file(self._sandbox_id, file_path, content)
        if not ok:
            return WriteResult(error=f"Failed to write '{file_path}'")
        return WriteResult(path=file_path)

    def ls_info(self, path):
        """List via AgentBox REST API."""
        entries = self._sync_client.list_files(self._sandbox_id, path)
        return [FileInfo(path=e["name"], is_dir=e.get("is_dir", False),
                         size=e.get("size", 0)) for e in entries]

    def edit(self, file_path, old_string, new_string, replace_all=False):
        """Edit via AgentBox REST API (uses our fuzzy + AST patcher)."""
        # Read, apply edit, write back
        content = self._sync_client.read_file(self._sandbox_id, file_path)
        if content is None:
            return EditResult(error=f"File '{file_path}' not found")
        if old_string not in content:
            return EditResult(error=f"String not found in '{file_path}'")
        if replace_all:
            new_content = content.replace(old_string, new_string)
            count = content.count(old_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            count = 1
        self._sync_client.write_file(self._sandbox_id, file_path, new_content)
        return EditResult(path=file_path, occurrences=count)
```

**Why override instead of using inherited**:
1. AgentBox file ops already exist and are tested
2. Our `edit` uses fuzzy + AST matching (better than BaseSandbox's exact match)
3. Avoids the `python3 -c "..."` shell dependency for Pyodide engine
4. Faster — direct file access vs. shell command round-trip

**What stays inherited**: `glob_info()` and `grep_raw()` can use the
inherited implementations since they'll work via `execute()` on
AgentCoreEngine. For PyodideEngine, override these too if our shell
supports them as builtins (we already have `glob_info` and `grep` builtins).

---

### Step 4: Update `__init__.py` and Deprecate `AgentBoxBackend`

```python
# agentbox/langchain/__init__.py
from agentbox.langchain.sandbox import AgentBoxSandbox
from agentbox.langchain.backend import AgentBoxBackend  # deprecated

# agentbox/langchain/backend.py — add deprecation warning
import warnings

class AgentBoxBackend:
    def __init__(self, *args, **kwargs):
        warnings.warn(
            "AgentBoxBackend is deprecated. Use AgentBoxSandbox instead.",
            DeprecationWarning, stacklevel=2,
        )
        ...
```

---

### Step 5: Add Tests

**New test file**: `test/test_sandbox_protocol.py`

```python
# Unit tests (no docker-compose needed, mock the HTTP client)

def test_implements_protocol():
    """AgentBoxSandbox satisfies SandboxBackendProtocol."""
    from deepagents.backends.protocol import SandboxBackendProtocol
    assert issubclass(AgentBoxSandbox, SandboxBackendProtocol)

def test_has_required_methods():
    """Check execute, upload_files, download_files, id."""
    ...

def test_execute_returns_execute_response():
    """execute() returns ExecuteResponse with output, exit_code, truncated."""
    ...

def test_upload_files_returns_responses():
    """upload_files() returns list[FileUploadResponse]."""
    ...

def test_download_files_returns_responses():
    """download_files() returns list[FileDownloadResponse]."""
    ...
```

**Integration test** (requires docker-compose): `test/test_deepagent_integration.py`

```python
# Verify create_deep_agent(backend=AgentBoxSandbox(...)) works end-to-end

async def test_create_deep_agent():
    backend = AgentBoxSandbox(base_url="http://localhost:8090")
    agent = create_deep_agent(
        model=ChatAnthropic(model="claude-sonnet-4-6"),
        backend=backend,
        system_prompt="You are a helpful coding assistant.",
    )
    result = agent.invoke({
        "messages": [{"role": "user", "content": "What is 2+2? Use Python to calculate."}]
    })
    # Verify agent used the execute tool and got the answer
    ...
```

**Existing tests**: Update `test/test_langchain.py` to add `AgentBoxSandbox`
tests alongside existing `AgentBoxBackend` tests.

---

### Step 6: Update Documentation

- Update `planning/langchain-sandbox-integration.md` to reflect `BaseSandbox`
  inheritance
- Update `docs/` if any reference `AgentBoxBackend`
- Add usage example to README or docs showing `create_deep_agent()` with
  `AgentBoxSandbox`

---

## File Changes Summary

| File | Action |
|------|--------|
| `pyproject.toml` | Bump `deepagents>=0.6.10`, `langchain-core>=1.4.7` |
| `agentbox/langchain/sandbox.py` | **NEW** — `AgentBoxSandbox(BaseSandbox)` |
| `agentbox/langchain/__init__.py` | Add `AgentBoxSandbox` export |
| `agentbox/langchain/backend.py` | Add deprecation warning |
| `test/test_sandbox_protocol.py` | **NEW** — unit tests |
| `test/test_deepagent_integration.py` | **NEW** — integration test |
| `test/test_langchain.py` | Add `AgentBoxSandbox` tests |

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `langchain-core` 1.4.8 breaks existing code | Low | Our tools use `BaseTool` which is stable API |
| `BaseSandbox` inherited methods fail on Pyodide shell | **High** | Override `read`/`write`/`edit`/`ls` with direct REST calls |
| `deepagents` 0.6.10 heavy transitive deps | Medium | Already pulling `langchain`, `langchain-anthropic` — same as before |
| Sync wrapper for async client | Medium | Use `nest_asyncio` or sync httpx client |
| `AgentBoxBackend` tests break after upgrade | Low | Class doesn't import from deepagents |

---

## Sequencing with Engine Extraction

```
WEEK 1-2:  Deep Agents upgrade (this plan)
           ├── Step 1: pip install, pyproject.toml
           ├── Step 2: AgentBoxSandbox(BaseSandbox)
           ├── Step 3: Override file ops
           ├── Step 4: Deprecate AgentBoxBackend
           ├── Step 5: Tests
           └── Step 6: Docs

WEEK 2-4:  Engine extraction (execution-engine-extraction.md Phases 1-6)
           ├── Phase 1: Extract engine interface
           ├── Phase 2: AgentCoreEngine
           ├── Phase 3: AgentCoreBox
           ├── Phase 4-5: Edit + Git adapters
           └── Phase 6: Config & BoxManager

           After engine extraction, AgentBoxSandbox.execute() can route
           to real bash via AgentCoreEngine — inherited BaseSandbox methods
           for glob/grep then work natively.
```

---

## Success Criteria

- [x] `deepagents==0.6.10` installed, no import errors
- [x] `pyproject.toml` updated with correct version bounds
- [x] `AgentBoxSandbox(BaseSandbox)` implements `SandboxBackendProtocol`
- [x] `execute()` returns `ExecuteResponse` correctly
- [x] `upload_files()` / `download_files()` work
- [x] `read()`, `write()`, `edit()`, `ls_info()` work via REST API overrides
- [x] `create_deep_agent(backend=AgentBoxSandbox(...))` works end-to-end
- [x] Existing 27 LangChain tests still pass
- [x] New protocol unit tests pass (27 unit + 33 integration = 60/60)
- [x] `AgentBoxBackend` still works but emits `DeprecationWarning`

## Implementation Notes (2026-06-18)

- Used **sync `httpx.Client`** (not async) since `BaseSandbox` methods are sync.
  Async variants (`aexecute`, `aread`, etc.) are provided by `BaseSandbox` automatically.
- `execute()` routes through `/sandboxes/{id}/execute` with `language="shell"`
  (not `/shell`) for compatibility with existing Docker images.
- `ls_info()` handles entries returned as plain strings (current API) or dicts
  (future API with metadata).
- `files_update` field in `WriteResult`/`EditResult` is deprecated in 0.6.10
  (removed in 0.7.0) — we pass `None`.
- `glob_info()` and `grep_raw()` use inherited `BaseSandbox` implementations
  (will work natively once AgentCoreEngine provides real bash).
