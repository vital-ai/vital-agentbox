# Sandbox Overview

AgentBox provides three sandbox types, each with different isolation and
persistence characteristics.

## MemBox (default)

Purely in-memory sandbox. All files live in Emscripten's MemFS inside a
Chromium + Pyodide WASM page. Ephemeral — destroyed when the sandbox ends.

**Create:**
```python
sandbox = client.create_sandbox_sync(box_type="mem")
```

**Best for:**
- Data analysis and computation
- Code generation and testing
- One-shot tasks
- Anything that doesn't need persistence

**Properties:**
- Fast startup (~2s cold, <100ms warm)
- Full Python via Pyodide (CPython 3.11 compiled to WASM)
- 30+ shell builtins (ls, cat, grep, find, sed, edit, git, etc.)
- No host filesystem access
- No network access from inside the sandbox
- Files lost when sandbox is destroyed

## GitBox

Same Chromium + Pyodide sandbox as MemBox, but with **isomorphic-git**
loaded on the page. Provides in-sandbox git operations and optional
sync to persistent storage (S3, MinIO, or local files).

**Create:**
```python
sandbox = client.create_sandbox_sync(box_type="git", repo_id="my-project")
```

**Best for:**
- Coding agents that need version control
- Multi-session work on the same codebase
- Tasks requiring commit history, branching, merging
- Collaboration between multiple sandbox instances

**Properties:**
- Everything MemBox has, plus:
- `git init`, `add`, `commit`, `log`, `diff`, `branch`, `checkout`, `merge`, `rm`, `reset`
- Merge conflict resolution with conflict markers
- `git push` / `git pull` sync to S3/MinIO storage
- Auto-restore: if `repo_id` exists in storage, files are loaded on startup
- Auto-sync on commit (configurable)
- Each file stored individually in S3 for direct asset access

### Git command tiers

| Tier | Commands | Where they run |
|------|----------|---------------|
| **Tier 1** (in-sandbox) | init, add, commit, log, status, branch, checkout, diff, rm, reset, merge | isomorphic-git in Chromium |
| **Tier 3** (host-delegated) | push, pull | Worker process → S3/MinIO |

### Storage backends

GitBox supports pluggable storage:

| Backend | Config | Use case |
|---------|--------|----------|
| **S3** | `AGENTBOX_S3_BUCKET`, `AWS_*` env vars | Production |
| **MinIO** | `AGENTBOX_S3_ENDPOINT` | Self-hosted / dev |
| **Local files** | `AGENTBOX_LOCAL_STORAGE_PATH` | Development only |

## FileSystemBox

Backed by a host directory. For local development only — **not for production**.

**Properties:**
- Reads/writes directly to host filesystem
- No isolation (agent code runs on host)
- Useful for debugging shell builtins against real files

## Security model

Both MemBox and GitBox run inside two nested security boundaries:

```
┌──────────────────────────────────────┐
│  Chromium Renderer Sandbox           │
│  (seccomp-bpf on Linux,             │
│   Seatbelt on macOS)                │
│                                      │
│  ┌──────────────────────────────┐   │
│  │  WASM Linear Memory          │   │
│  │  (Pyodide / Emscripten)     │   │
│  │                              │   │
│  │  - No host FS access         │   │
│  │  - No raw network sockets    │   │
│  │  - Memory isolated           │   │
│  └──────────────────────────────┘   │
└──────────────────────────────────────┘
```

- **Layer 1 — Chromium sandbox**: OS-level process isolation. The renderer
  process cannot access the host filesystem, make syscalls, or open network
  connections except through the browser's IPC.
- **Layer 2 — WASM sandbox**: All Python/shell execution runs in WASM linear
  memory. Even if the WASM sandbox were compromised, the Chromium sandbox
  provides a second independent boundary.

This dual-layer model was deliberately chosen over lighter alternatives
(Node.js, Deno, subprocess+nsjail) because complete isolation is the
primary design constraint.

## Communication model

The host (Python worker process) communicates with the sandbox via
Playwright's `page.evaluate()`:

```
Worker Process                    Chromium Page
     │                                 │
     │  page.evaluate(js_code)         │
     ├────────────────────────────────►│
     │                                 │ executes in WASM
     │  return result                  │
     │◄────────────────────────────────┤
     │                                 │
```

- File transfer: base64 encoding via `page.evaluate()` (~94ms for 1MB round-trip)
- Shell commands: parsed by tree-sitter-bash, dispatched to Python builtin handlers
- Python code: executed by Pyodide's `runPythonAsync()`

## Comparison

| Feature | MemBox | GitBox | FileSystemBox |
|---------|--------|--------|---------------|
| Isolation | Chromium + WASM | Chromium + WASM | None |
| Persistence | None | S3/MinIO/local | Host filesystem |
| Git | No | Yes (isomorphic-git) | No |
| Python | Pyodide (WASM) | Pyodide (WASM) | Host Python |
| Shell | Virtual builtins | Virtual builtins | Host shell |
| Startup | ~2s | ~3s | Instant |
| Use case | Ephemeral tasks | Coding agents | Dev/debug |
