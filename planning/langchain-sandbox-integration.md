# LangChain Sandbox Integration Plan

**Status**: Planning (not publishing immediately)
**Date**: 2026-02-23
**Reference implementation**: Daytona (`daytona/` in this repo, from `langchain-ai/deepagents`)

---

## 1. What We're Building

A `langchain-agentbox` PyPI package — a LangChain partner integration that
provides `AgentBoxSandbox` as a sandbox backend for Deep Agents. This lets
any LangChain Deep Agent use AgentBox for isolated code execution, file
editing, git operations, etc.

### Target usage

```python
from agentbox.client import AgentBoxClient
from langchain_agentbox import AgentBoxSandbox
from deepagents import create_deep_agent

client = AgentBoxClient("http://localhost:8090")
sandbox_info = client.create_sandbox_sync(box_type="git")

backend = AgentBoxSandbox(
    base_url="http://localhost:8090",
    sandbox_id=sandbox_info.sandbox_id,
)

agent = create_deep_agent(
    backend=backend,
    system_prompt="You are a coding assistant with sandbox access.",
)

result = agent.invoke({
    "messages": [{"role": "user", "content": "Create and run hello.py"}]
})

sandbox_info.destroy_sync()
```

---

## 2. Architecture Decision

### Option A: Thin wrapper — `langchain-agentbox` depends on `vital-agentbox[client]`

The `langchain-agentbox` package imports `AgentBoxSandbox` from
`agentbox.deepagents` and re-exports it. Minimal code in the partner
package itself.

**Pros**: No code duplication, single source of truth for the sandbox impl.
**Cons**: Heavy dependency chain — pulls in all of `vital-agentbox` + httpx.

### Option B: Self-contained — `langchain-agentbox` has its own HTTP client ✅ RECOMMENDED

The partner package contains its own lightweight `AgentBoxSandbox` class
that makes HTTP calls to the AgentBox API directly (like Daytona wraps
`daytona.Sandbox`). No dependency on `vital-agentbox` at all — only
depends on `deepagents` and `httpx`.

**Pros**: Clean separation, minimal deps, easy for external users to install.
**Cons**: Separate codebase from the internal `agentbox.deepagents.sandbox`.

### Decision

**Option B**. The partner package should be self-contained. The internal
`agentbox.deepagents.sandbox` module can remain for direct use within the
monorepo, but the public LangChain integration should only depend on
`deepagents` + `httpx` (like Daytona only depends on `deepagents` + `daytona`).

This keeps the install minimal for external users:
```bash
pip install langchain-agentbox
```

---

## 3. Interface Contract

From `deepagents.backends.sandbox.BaseSandbox`:

### Abstract methods (MUST implement)

| Method | Signature | Notes |
|--------|-----------|-------|
| `execute()` | `(command, *, timeout) -> ExecuteResponse` | POST `/sandboxes/{id}/execute` |
| `id` | `@property -> str` | Sandbox ID from creation |
| `upload_files()` | `(files: list[tuple[str, bytes]]) -> list[FileUploadResponse]` | POST `/sandboxes/{id}/files/write` per file |
| `download_files()` | `(paths: list[str]) -> list[FileDownloadResponse]` | GET `/sandboxes/{id}/files/read` per file |

### Inherited methods (BaseSandbox provides defaults via `execute()`)

These work out of the box by delegating to `python3 -c` commands:
- `read(file_path, offset, limit) -> str`
- `write(file_path, content) -> WriteResult`
- `edit(file_path, old_string, new_string, replace_all) -> EditResult`
- `ls_info(path) -> list[FileInfo]`
- `grep_raw(pattern, path, glob) -> list[GrepMatch] | str`
- `glob_info(pattern, path) -> list[FileInfo]`

### Overrides — use Tier 1 builtins

We WILL override the inherited methods to use AgentBox's Tier 1 shell
builtins (`edit --view`, `edit --old --new`, heredoc `cat`, etc.) instead
of BaseSandbox's `python3 -c` defaults. This matches what
`agentbox.deepagents.sandbox.AgentBoxSandbox` already does.

**Decision**: Override `read`, `write`, `edit`, `ls_info`, `glob_info` from
the start. Our builtins are purpose-built for MemFS and are more reliable
than the generic `python3 -c` templates. The code is ~80 lines copied from
`agentbox.deepagents.sandbox` — acceptable for a self-contained package.

---

## 4. Package Structure

Following the Daytona reference exactly:

```
libs/partners/agentbox/           # or standalone repo
├── langchain_agentbox/
│   ├── __init__.py               # exports AgentBoxSandbox
│   └── sandbox.py                # AgentBoxSandbox(BaseSandbox)
├── tests/
│   ├── __init__.py
│   ├── test_import.py            # smoke test
│   ├── unit_tests/
│   │   ├── __init__.py
│   │   └── test_import.py
│   └── integration_tests/
│       ├── __init__.py
│       └── test_integration.py   # SandboxIntegrationTests
├── pyproject.toml                # hatchling build, deps on deepagents + httpx
├── Makefile                      # test, lint, format targets
├── README.md
└── LICENSE                       # MIT
```

---

## 5. Implementation Details

### `sandbox.py` — Core class (~120 lines)

```python
class AgentBoxSandbox(BaseSandbox):
    """AgentBox sandbox backend for Deep Agents."""

    def __init__(
        self,
        *,
        base_url: str,
        sandbox_id: str,
        default_timeout: int = 120,
    ) -> None: ...

    @property
    def id(self) -> str: ...

    def execute(self, command, *, timeout=None) -> ExecuteResponse:
        """POST /sandboxes/{id}/execute {code, language: "shell"}"""

    def upload_files(self, files) -> list[FileUploadResponse]:
        """POST /sandboxes/{id}/files/write per file"""

    def download_files(self, paths) -> list[FileDownloadResponse]:
        """GET /sandboxes/{id}/files/read per file"""
```

HTTP client: `httpx` (sync). Matches our internal implementation.

### API endpoints used

| Endpoint | Method | Body / Params |
|----------|--------|---------------|
| `/sandboxes/{id}/execute` | POST | `{code: str, language: "shell"}` |
| `/sandboxes/{id}/files/write` | POST | `{path: str, content: str}` |
| `/sandboxes/{id}/files/read` | GET | `?path=...&binary=true/false` |
| `/sandboxes` | POST | `{box_type: "mem"|"git", repo_id?: str}` |
| `/sandboxes/{id}` | DELETE | — |

### Convenience factory (optional)

```python
@classmethod
def create(
    cls,
    base_url: str,
    *,
    box_type: str = "mem",
    repo_id: str | None = None,
    default_timeout: int = 120,
) -> "AgentBoxSandbox":
    """Create a new sandbox and return a connected backend."""
```

This is NOT required by the protocol but is nice UX (mirrors Daytona's
`Daytona().create()`). Could also provide `destroy()`.

---

## 6. pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "langchain-agentbox"
description = "AgentBox sandbox integration for Deep Agents"
license = { text = "MIT" }
version = "0.0.1"
requires-python = ">=3.11,<4.0"
dependencies = [
    "deepagents>=0.4.3",
    "httpx>=0.24.0",
]

[tool.hatch.build.targets.wheel]
packages = ["langchain_agentbox"]

[dependency-groups]
test = [
    "pytest>=7.3.0",
    "pytest-asyncio>=1.3.0",
    "pytest-socket",
    "langchain-tests>=1.1.4",
    "ruff>=0.13.0",
]
```

Key: **no dependency on `vital-agentbox`**. The partner package talks to
AgentBox over HTTP only.

---

## 7. Tests

### Unit tests (no network, no server)

- **Import test**: `import langchain_agentbox` succeeds
- **Mock execute**: Verify `execute()` builds correct HTTP request
- **Mock upload/download**: Verify file ops map correctly
- **Error handling**: HTTP errors → appropriate error responses

### Integration tests (requires running AgentBox server)

Standard LangChain test suite:

```python
from langchain_tests.integration_tests import SandboxIntegrationTests

class TestAgentBoxSandboxStandard(SandboxIntegrationTests):
    @pytest.fixture(scope="class")
    def sandbox(self) -> Iterator[SandboxBackendProtocol]:
        backend = AgentBoxSandbox.create("http://localhost:8090", box_type="mem")
        try:
            yield backend
        finally:
            backend.destroy()
```

The `SandboxIntegrationTests` base class tests:
- `execute()` with successful and failing commands
- File upload/download round-trip
- Read/write/edit operations
- ls_info, glob_info, grep_raw

---

## 8. What Differs From Our Internal Implementation

| Aspect | Internal (`agentbox.deepagents`) | Partner (`langchain_agentbox`) |
|--------|----------------------------------|-------------------------------|
| HTTP client | Async httpx on bg thread | Sync httpx (simpler) |
| Dependencies | Full `vital-agentbox` | Only `deepagents` + `httpx` |
| Overrides | `read`/`write`/`edit` use builtins | Same — use builtins (copied ~80 lines) |
| Lifecycle | External (client manages sandbox) | Optional `create()`/`destroy()` |
| Logging | `self._log()` to file + stdout | Standard `logging` module |
| Binary download | Extension-based detection | Same logic (copy) |

---

## 9. Eligibility Checklist

From LangChain's contributing guidelines:

- [x] **Authored by provider company** — We are the AgentBox provider
- [ ] **OR 10K daily PyPI downloads** — Not yet (pre-launch)
- [x] **Implements BaseSandbox** — Yes, via `execute()` + file ops
- [ ] **Passes standard tests** — `langchain-tests` `SandboxIntegrationTests`
- [ ] **Published to PyPI** — Not yet
- [ ] **Documentation PR** — `langchain-ai/docs` repo

---

## 10. Implementation Steps

### Phase A: Create the package (local, not published)

1. Create `langchain-agentbox/` directory (in this repo or separate)
2. Write `langchain_agentbox/sandbox.py` — the core class
3. Write `langchain_agentbox/__init__.py` — exports
4. Write `pyproject.toml`, `Makefile`, `README.md`, `LICENSE`
5. Write unit tests with mocked HTTP
6. Test locally against running AgentBox server

### Phase B: Standard tests

7. Install `langchain-tests` in dev env
8. Write integration test class extending `SandboxIntegrationTests`
9. Run standard test suite against local AgentBox
10. Fix any failures

### Phase C: Publish (when ready)

11. Publish `langchain-agentbox` to PyPI
12. Submit docs PR to `langchain-ai/docs`
13. Submit integration PR to `langchain-ai/deepagents` (optional — could be standalone repo)
14. Co-marketing (blog post, etc.)

---

## 11. Open Questions

1. **Package location**: Should `langchain-agentbox/` live in this repo
   (`libs/partners/agentbox/`) or a separate repo? Daytona lives in the
   `langchain-ai/deepagents` monorepo. We'd need a PR accepted there, or
   host our own.

2. **Convenience factory**: Should `AgentBoxSandbox.create()` handle
   sandbox creation, or require the user to create via `AgentBoxClient`
   separately? Daytona's pattern: `Daytona().create()` returns a sandbox
   object, then `DaytonaSandbox(sandbox=sandbox)` wraps it.

3. ~~**Override inherited methods?**~~ **Decided: YES.** Use our Tier 1
   builtins from the start. ~80 lines copied from `agentbox.deepagents.sandbox`.

4. **Auth**: Current AgentBox API has no auth. When we add API keys, the
   partner package needs to support them (header or constructor param).

5. **Async**: `BaseSandbox` provides `aexecute()`, `aread()`, etc. that
   wrap sync methods in `asyncio.to_thread()`. Do we need native async?
   Probably not initially — the thread-wrapping is fine.
