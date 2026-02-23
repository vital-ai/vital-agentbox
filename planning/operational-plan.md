# AgentBox Operational Plan

## Overview

Turn the AgentBox prototype (Playwright + Pyodide browser-based sandboxes) into an
operational service and client library for use with LangGraph and LangChain Deep Agents.

The system provides AI agents with isolated code execution environments and virtual
file systems — comparable to Daytona, E2B, and Runloop — but running entirely on
self-hosted infrastructure with no external sandbox provider dependency.

## Security & Isolation (Primary Design Constraint)

Complete isolation is the most critical requirement. The Playwright + Chromium
stack is a deliberate architectural choice — not a convenience — because it
provides **two nested, independent security boundaries**:

```
┌─────────────────────────────────────────────────────────┐
│  Host Process (Python / FastAPI)                        │
│  - No untrusted code runs here                          │
│  - API keys, credentials, network access live here      │
├─────────────────────────────────────────────────────────┤
│  Sandbox Layer 1: Chromium Renderer Process             │
│  - Separate OS process per page (site isolation)        │
│  - seccomp-bpf syscall filter (Linux)                   │
│  - Seatbelt sandbox profile (macOS)                     │
│  - No filesystem access, no network access,             │
│    no access to other processes                         │
│  - 15+ years of adversarial hardening by the            │
│    security research community                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Sandbox Layer 2: WASM Linear Memory              │  │
│  │  - Pyodide runs inside WASM, which has its own    │  │
│  │    memory sandbox (cannot address outside its      │  │
│  │    linear memory region)                           │  │
│  │  - Even if WASM is compromised, the attacker      │  │
│  │    is still inside the Chromium renderer sandbox   │  │
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │  Agent Code (Python via Pyodide)            │  │  │
│  │  │  - Executes inside WASM                     │  │  │
│  │  │  - Only I/O: stdout capture + sendMessage   │  │  │
│  │  │  - MemFS is in-memory only (no disk)        │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Why not lighter runtimes?**

| Alternative | Isolation gap |
|---|---|
| **Node.js + Pyodide** | Only WASM sandbox — no outer OS-level sandbox. A V8 escape gives full OS access. |
| **Deno + Pyodide** | Deno permissions are coarse-grained process flags, not a true sandbox. |
| **Subprocess + nsjail** | Strong OS isolation, but runs real CPython (much larger attack surface than WASM). Linux-only. |
| **V8 isolates (PyMiniRacer)** | Only WASM sandbox. No process isolation between isolates. |

The Chromium sandbox is one of the most battle-tested security boundaries in
existence. An attacker must escape WASM, then escape the renderer process —
two independent exploit chains. This dual-layer model is stronger than any
single-layer alternative and is the reason we accept Chromium's higher memory
overhead.

**Controlled communication:** The only channel from sandbox to host is the
`sendMessage` bridge (`page.expose_function`). The host decides what data to
return. Agent code cannot initiate network requests, read host files, or
access environment variables.

---

## Architecture

Two deliverables:

1. **AgentBox Service** — A FastAPI server that manages a pool of browser-based
   sandboxes (Chromium + Pyodide + MemFS). Deployable locally, on ECS, or in any
   container environment.

2. **AgentBox Client Library** (`agentbox-client`) — A Python SDK that wraps the
   service API. Includes a LangChain/Deep Agents integration package
   (`langchain-agentbox`) that implements the `BackendProtocol` so Deep Agents can
   use AgentBox as a sandbox backend alongside Modal, Daytona, and Runloop.

```
┌──────────────────────────────────────────────┐
│  AI Agent (LangGraph / Deep Agents)          │
├──────────────────────────────────────────────┤
│  langchain-agentbox (BackendProtocol impl)   │
├──────────────────────────────────────────────┤
│  agentbox-client (Python SDK)                │
│  - SandboxClient: create, execute, files,    │
│    destroy, shell                            │
├──────────────────────────────────────────────┤
│              HTTP / WebSocket                 │
├──────────────────────────────────────────────┤
│  AgentBox Service (FastAPI + Uvicorn)        │
│  ┌────────────────────────────────────────┐  │
│  │  BoxManager (browser pool)             │  │
│  │  ┌──────────┐ ┌──────────┐            │  │
│  │  │ Browser 1│ │ Browser N│  ...       │  │
│  │  │ Page 1-M │ │ Page 1-M │            │  │
│  │  │ (Pyodide │ │ (Pyodide │            │  │
│  │  │ + MemFS  │ │ + MemFS  │            │  │
│  │  │ + Shell) │ │ + Shell) │            │  │
│  │  └──────────┘ └──────────┘            │  │
│  │                                        │  │
│  │  ShellExecutor (tree-sitter CST → MemFS)│  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

The Shell layer uses tree-sitter-bash to parse real bash command syntax into
a concrete syntax tree (CST), then walks the CST and dispatches operations
against the virtual MemFS — giving agents a familiar shell interface without
a real OS underneath.

---

## Phase 1: Core Service

Refactor the prototype into a proper server with sandbox lifecycle management.

### 1.1 Refactor CodeExecutorBox — Separate Init from Execution

Current: `run_python_with_pyodide()` creates a browser, loads Pyodide, runs code,
and closes the browser — all in one call.

Target: Split into distinct lifecycle stages:
- `create_sandbox()` — Launch page, load Pyodide, wire sendMessage bridge, init MemFS
- `execute(code)` — Run code in an already-initialized Pyodide (fast, no reload)
- `destroy()` — Close the page

This allows a sandbox to persist across multiple execute and file operations.

### 1.2 BoxManager — Browser Pool

Flesh out `agentbox/manager/box_manager.py`:

- Maintain a pool of Chromium browser instances
- Pre-warm pages with Pyodide loaded and ready
- Track sandbox state: WARMING → READY → EXECUTING → READY → ... → DESTROYED
- Assign sandboxes to least-loaded browser
- Recycle pages after a configurable max lifetime or idle timeout
- Expose pool metrics (total capacity, warm count, busy count)

Configuration (via env vars or config file):
- `AGENTBOX_MAX_BROWSERS` (default: 4)
- `AGENTBOX_PAGES_PER_BROWSER` (default: 50)
- `AGENTBOX_SANDBOX_TIMEOUT` (default: 300s idle, 3600s max lifetime)
- `AGENTBOX_PYODIDE_URL` (default: local bundle path, fallback CDN)
- `AGENTBOX_EXEC_TIMEOUT` (default: 30s per execution)

### 1.3 Local Pyodide Bundling

Eliminate the CDN dependency. Download the Pyodide distribution and serve it from
a local path or bundled into the Docker image. This:
- Removes a network dependency from the sandbox cold start
- Enables fully air-gapped deployment
- Speeds up page warming (local file:// or localhost fetch)

### 1.4 FastAPI Service

New directory: `agentbox/api/`

```
agentbox/api/
├── __init__.py
├── app.py              # FastAPI app, lifespan (BoxManager startup/shutdown)
├── deps.py             # Dependency injection (BoxManager singleton)
├── models.py           # Pydantic request/response schemas
└── routes/
    ├── __init__.py
    ├── health.py       # GET /health, GET /metrics
    ├── sandbox.py      # POST/GET/DELETE /sandboxes
    ├── execute.py      # POST /sandboxes/{id}/execute
    └── files.py        # GET/POST/DELETE /sandboxes/{id}/files/*
```

#### API Endpoints

**Sandbox Lifecycle:**
- `POST /sandboxes` → Create sandbox, returns `{sandbox_id, status}`
- `GET /sandboxes` → List active sandboxes
- `GET /sandboxes/{id}` → Sandbox status and metadata
- `DELETE /sandboxes/{id}` → Destroy sandbox

**Code Execution:**
- `POST /sandboxes/{id}/execute` → `{code, language: "python"|"shell", timeout?}`
  → `{success, output, error, exit_code}`
  - `language: "python"` → Pyodide execution (existing path)
  - `language: "shell"` → bashlex parse → AST walk → MemFS operations
  - Default: `"shell"` (matches Deep Agents `execute()` behavior)
- `POST /sandboxes/{id}/message` → Send message via sendMessage bridge

**File Operations (MemFS):**
- `GET /sandboxes/{id}/files?path=/&recursive=false&info=false` → List directory
- `GET /sandboxes/{id}/files/read?path=/foo.txt` → Read file content
- `POST /sandboxes/{id}/files/write` → `{path, content, append?}` → Write/append
- `POST /sandboxes/{id}/files/mkdir` → `{path}` → Create directory
- `DELETE /sandboxes/{id}/files?path=/foo.txt` → Remove file
- `DELETE /sandboxes/{id}/files/dir?path=/foo` → Remove directory
- `POST /sandboxes/{id}/files/copy` → `{src, dst}` → Copy file or directory

**System:**
- `GET /health` → `{status, pool_size, warm_count, busy_count}`
- `GET /metrics` → Detailed pool statistics for monitoring

### 1.5 Shell Command Layer (tree-sitter-bash)

Replace the current Lark-based `MemFSParser` with a shell execution layer
powered by **tree-sitter-bash** — the bash grammar used by every major code
editor (VS Code, Neovim, Helix, etc.).

#### Why tree-sitter-bash

The current `MemFSParser` (Lark grammar) handles a custom command syntax
(`ls`, `get`, `put`, `cp`, etc.). This works, but agents using Deep Agents'
`execute()` tool will emit real shell commands (`cat`, `echo`, `mv`, `find`,
pipes, redirects, `&&`/`||` chaining, etc.). tree-sitter-bash parses these
into a full concrete syntax tree (CST) that we can walk and execute against
MemFS.

Why tree-sitter-bash over bashlex:
- **MIT license** — compatible with AgentBox's Apache 2.0 (bashlex is GPL v3+)
- **Actively maintained** — 30 contributors, 1.8k dependents, part of the
  official tree-sitter org
- **More complete** — handles arrays, `case`, `[[ ]]`, heredocs, arithmetic
  expressions, `export`/`local` — all areas where bashlex has open bugs
- **Pre-compiled wheels** — `pip install tree-sitter tree-sitter-bash`, no
  build toolchain needed
- **Battle-tested** — powers syntax highlighting and code intelligence in
  every major editor

tree-sitter-bash understands:
- Simple commands: `ls /foo`, `cat /file.txt`
- Pipes (pipeline): `cat /file.txt | grep pattern`
- Redirects (redirected_statement): `echo "hello" > /file.txt`, `cat /a >> /b`
- Operators (list): `cmd1 && cmd2`, `cmd1 || cmd2`, `cmd1 ; cmd2`
- Command substitution: `echo $(cat /file.txt)`
- Variable assignment: `FOO=bar`
- Variable expansion: `$VAR`, `${VAR}`, `$?`
- Quoting: single, double, ANSI-C, escapes
- Declaration commands: `export`, `local`, `declare`
- Arithmetic: `$(( x + 1 ))`
- Conditionals: `[[ -f /path ]]`, `if`/`then`/`fi`

#### Architecture

```
agentbox/box/shell/
├── __init__.py
├── shell_executor.py     # Top-level: parse with tree-sitter, walk CST, return output
├── cst_walker.py         # Traverse tree-sitter nodes, dispatch to builtins
├── builtins.py           # Registry — imports and registers all builtins from buildin_exec/
├── virtual_bin.py        # Virtual /bin and /usr/bin directory (exposes builtins as executables)
├── pipeline.py           # Pipe stdout of one command into stdin of next
├── environment.py        # Shell variables, cwd tracking, env vars
└── buildin_exec/         # Modular builtin implementations (one class per command)
    ├── __init__.py       # BuiltinExec base class (path resolution, MemFS wrappers)
    ├── ls.py             # LsExec — ls with virtual /bin support, file stat fallback
    ├── cat.py            # CatExec — cat with virtual /bin stub script support
    ├── echo.py           # EchoExec, PrintfExec
    ├── fileops.py        # CpExec, MvExec, RmExec, MkdirExec, RmdirExec, TouchExec
    ├── env_cmds.py       # CdExec, PwdExec, ExportExec, EnvExec
    ├── shell_info.py     # WhichExec, CommandExec, TypeExec, TestExec — return /bin/<name> paths
    ├── grep.py           # GrepExec
    ├── text_cmds.py      # HeadExec, TailExec, WcExec, SortExec, UniqExec, CutExec, TrExec, SedExec
    ├── find.py           # FindExec
    ├── misc.py           # TeeExec, TrueExec, FalseExec
    ├── python_exec.py    # PythonExec — Pyodide delegation (Tier 2)
    └── pip.py            # PipExec — micropip + importlib.metadata
```

#### CST Walking

tree-sitter-bash produces a concrete syntax tree with these node types
(relevant subset for our virtual shell):

- `program` → root node, contains statements
- `command` → simple command with `command_name` + arguments
  → dispatch to builtin or error ("command not found")
- `pipeline` → `cmd1 | cmd2 | cmd3`
  → chain stdout between commands
- `list` → `cmd1 && cmd2`, `cmd1 || cmd2`, `cmd1 ; cmd2`
  → control flow based on exit codes
- `redirected_statement` → wraps a command with redirect operators
  → `>`, `>>`, `<`, `2>`, `2>>` mapped to MemFS read/write
- `command_substitution` → `$(...)` or backticks
  → recursive execution, capture stdout
- `variable_assignment` → `FOO=bar`
  → store in shell environment
- `declaration_command` → `export`, `local`, `declare`
  → environment variable management
- `simple_expansion` → `$VAR`
- `expansion` → `${VAR}`, `${VAR:-default}`, etc.
- `string` → double-quoted (with expansion)
- `raw_string` → single-quoted (literal)
- `word` → unquoted arguments/paths
- `if_statement`, `while_statement`, `for_statement`, `case_statement`
  → control flow (support as needed)

The walker executes the CST depth-first, threading a virtual stdout/stderr
between nodes. Named fields (e.g., `node.child_by_field_name("name")`) make
it clean to extract command names, arguments, and redirect targets.

#### Virtual Shell Builtins

All builtins are implemented as async classes inheriting `BuiltinExec` in
`buildin_exec/`. Each class has a `run(args, stdin, env, memfs)` method
returning `ShellResult`. The `builtins.py` registry imports and maps
command names → exec classes (33 builtins across 15 files).

| Builtin | MemFS Operation | Notes |
|---------|-----------------|-------|
| `ls` | `memfs.list_dir()` | `-r`, `-l`, virtual `/bin`, file stat fallback |
| `cat` | `memfs.read_file()` | Concatenate files, virtual `/bin` stub scripts |
| `echo` / `printf` | Return string | With redirect → `memfs.write_file()` |
| `cp` | `memfs.copy()` | `-r` for recursive |
| `mv` | `memfs.copy()` + `memfs.remove_file()` | Copy then delete source |
| `rm` | `memfs.remove_file()` | `-r` for recursive directory removal |
| `mkdir` | `memfs.mkdir()` | `-p` for parents |
| `rmdir` | `memfs.rmdir()` | |
| `touch` | `memfs.write_file(path, "")` | Create empty / update timestamp |
| `head` / `tail` | `memfs.read_file()` + slice | `-n N` lines |
| `wc` | `memfs.read_file()` + count | `-l`, `-w`, `-c` |
| `grep` | `memfs.read_file()` + regex match | `-i`, `-r`, `-n`, `-c`, `-l`, `-v` |
| `find` | `memfs.list_dir(recursive=True)` + filter | `-name`, `-type` |
| `sort` / `uniq` / `cut` / `tr` / `sed` | Text processing | Pipe-friendly |
| `tee` | Write to file and pass through | |
| `cd` / `pwd` | cwd in environment | |
| `env` / `export` | Environment variable management | |
| `which` / `command` / `type` | Shell introspection | Return `/bin/<name>` paths |
| `test` / `[` | File/string tests | `-f`, `-d`, `-e`, `-z`, `-n`, `=`, `!=` |
| `true` / `false` | Exit code only | |
| `python` / `python3` | Delegate to Pyodide `execute()` | `-c`, script, stdin |
| `pip` / `pip3` | micropip + importlib.metadata | `install`, `list`, `show`, `freeze` |

#### Virtual `/bin` Directory

All builtins are exposed as virtual files at `/bin/<name>` and `/usr/bin/<name>`
via `virtual_bin.py`. No real MemFS files are created — the module intercepts
path lookups and returns synthetic responses:

- `ls /bin` → lists all builtin names
- `which ls` → `/bin/ls`
- `cat /bin/ls` → `#!/bin/sh\n# builtin: ls\nexec ls "$@"\n`
- `type ls` → `ls is /bin/ls`
- `test -f /bin/python3` → true

This makes the environment look like a real Linux system to LLMs, which
expect commands to have paths in `/bin` or `/usr/bin`.

#### Redirect Handling

bashlex parses redirects as part of the AST. The walker handles:
- `>` → `memfs.write_file(path, output, append=False)`
- `>>` → `memfs.write_file(path, output, append=True)`
- `<` → `memfs.read_file(path)` as stdin for command
- `2>` / `2>>` → stderr redirect

#### Pipe Handling

For `cmd1 | cmd2 | cmd3`:
1. Execute `cmd1`, capture stdout as string
2. Pass as stdin to `cmd2`
3. Pass result as stdin to `cmd3`

All in-memory, no OS processes.

#### Operator Handling

- `&&` → execute next only if previous exit code == 0
- `||` → execute next only if previous exit code != 0
- `;` → execute next unconditionally

#### Shell Environment

Each sandbox maintains:
- `cwd` — current working directory (default `/`)
- `env` — environment variables dict
- `last_exit_code` — for `&&`/`||` logic
- Variable expansion: `$VAR`, `${VAR}`, `$?` (last exit code)

#### Replacing MemFSParser and MemFSCommand

The tree-sitter-based `ShellExecutor` **replaces** the existing Lark-based
`MemFSParser` and `MemFSCommand`. The Lark grammar was a prototype stub
for a custom command syntax (`get`, `put`, `ls`, etc.). With tree-sitter-bash,
agents use real bash syntax which is what they will naturally emit. The
custom grammar and its Lark dependency are removed.

Migration:
- `MemFSParser` (Lark grammar) → removed, replaced by tree-sitter-bash parser
- `MemFSCommand` (dispatch by command name) → replaced by `cst_walker.py`
  dispatching to `builtins.py`
- `lark` dependency → removed from `setup.py`
- `get /path` → `cat /path`
- `put` with `>` / `>>` → `echo "content" > /path` or `echo "content" >> /path`
- `POST /sandboxes/{id}/command` endpoint → removed, use
  `POST /sandboxes/{id}/execute` with `language: "shell"` instead

```
API: POST /sandboxes/{id}/execute
  → {code: "ls -la /foo && cat /bar.txt | grep hello", language: "shell"}
  → ShellExecutor.run(code)
    → tree-sitter-bash parse
      → CST walk
        → MemFS operations
    → {exit_code, stdout, stderr}

API: POST /sandboxes/{id}/execute
  → {code: "print('hello')", language: "python"}
  → Pyodide execution (existing path)
```

#### Example: Walking a Parsed Command

```python
import tree_sitter_bash as tsbash
from tree_sitter import Language, Parser

BASH_LANGUAGE = Language(tsbash.language())
parser = Parser(BASH_LANGUAGE)

# Agent sends: echo "hello world" > /output.txt && cat /output.txt
tree = parser.parse(b'echo "hello world" > /output.txt && cat /output.txt')

# tree-sitter-bash produces:
# (program
#   (list
#     (redirected_statement
#       body: (command
#         name: (command_name (word))          # echo
#         argument: (string (string_content)))  # "hello world"
#       redirect: (file_redirect
#         destination: (word)))                 # /output.txt
#     (command
#       name: (command_name (word))             # cat
#       argument: (word))))                     # /output.txt
#
# The && operator is captured as a child of the list node.

# Walker:
# 1. Visit list node, see && operator
# 2. Visit redirected_statement:
#    a. Execute command "echo" with arg "hello world" → stdout = "hello world"
#    b. Apply file_redirect > → memfs.write_file("/output.txt", "hello world")
# 3. exit_code = 0, so && proceeds
# 4. Execute command "cat" with arg "/output.txt"
#    → memfs.read_file("/output.txt") → stdout = "hello world"
# 5. Return {exit_code: 0, stdout: "hello world", stderr: ""}
```

#### Security: Command Allowlist

Only virtual builtins are executable. Any unrecognized command returns:
```
bash: <command>: command not found
```

This prevents agents from attempting to run system commands that don't
exist in the virtual environment. The `python` builtin is special — it
delegates to the sandbox's Pyodide runtime.

### 1.6 Host-Delegated Commands

Some operations require host-native binaries that cannot run inside WASM
(e.g., pandoc, LaTeX). Rather than exposing real binaries directly, the
shell provides **safe wrapper commands** with restricted CLIs that delegate
to host-side execution.

#### Design Principle

Never expose raw host binaries to the sandbox. Instead, define purpose-built
commands with a minimal, controlled parameter set. The wrapper:
- Validates all arguments before anything touches the host
- Prevents shell injection, path traversal, and arbitrary flag usage
- Enforces options that cannot trigger local code execution (e.g., no
  `--lua-filter`, no `--filter`, no `--include-in-header` pointing outside
  MemFS)

#### Command Dispatch Tiers

The `ShellExecutor` dispatches commands through three tiers:

```
Agent runs a shell command
  │
  ├─ Tier 1: MemFS Builtins (ls, cat, echo, cp, rm, mkdir, ...)
  │    → Runs entirely in-memory against MemFS
  │    → Zero host interaction
  │
  ├─ Tier 2: Pyodide Commands (python, python3)
  │    → Delegates to Pyodide runtime inside the same sandbox page
  │    → Still inside the WASM sandbox
  │
  └─ Tier 3: Host-Delegated Commands (reportgen, git push/pull, boxcp, ...)
       → Routes through the sendMessage bridge (page.expose_function)
       → Purpose-built safe wrappers with restricted CLIs
       → Files extracted from MemFS → host temp dir (transient)
       → Host runs real binary with validated args
       → Output files written back into MemFS
       → Temp dir cleaned up
       → Returns {exit_code, stdout, stderr}
```

#### `reportgen` — PDF Report Generation

A safe wrapper around pandoc + LaTeX. The agent uses it like any other
shell command:

```bash
# Basic usage — convert markdown to PDF
reportgen /chapters/*.md -o /output/report.pdf

# With template
reportgen /chapters/*.md -o /output/report.pdf --template /templates/report.tex

# With metadata
reportgen /chapters/*.md -o /output/report.pdf \
  --title "Quarterly Report" \
  --author "Agent" \
  --date "2025-02-22"

# With table of contents
reportgen /chapters/*.md -o /output/report.pdf --toc
```

**Allowed CLI parameters (exhaustive — nothing else accepted):**

| Flag | Description |
|---|---|
| `-o`, `--output` | Output file path (must end in `.pdf`) |
| `--template` | LaTeX template path (from MemFS) |
| `--title` | Document title (string, sanitized) |
| `--author` | Author name (string, sanitized) |
| `--date` | Date string (sanitized) |
| `--toc` | Include table of contents |
| `--toc-depth N` | TOC depth (1-6) |
| `--highlight-style` | Code highlight style (from fixed list) |
| `--margin` | Page margin (e.g., `1in`, `2cm`) |

**Explicitly blocked** (pandoc flags that could trigger execution):
- `--filter` / `--lua-filter` — runs arbitrary code on host
- `--include-in-header` / `--include-before-body` / `--include-after-body`
  with host paths
- `--pdf-engine` — locked to a safe engine (currently using latexmk;
  tectonic is under consideration as a safer alternative — see below)
- `--metadata-file` — could reference host paths
- `--bibliography` / `--csl` — could reference host paths
- Any flag not in the allowed list is rejected

#### LaTeX Security: Input Scanning

LaTeX has commands that can execute arbitrary code or read host files. These
are scanned and rejected **before any files are copied to the host temp
directory** — the dangerous content never leaves MemFS.

All input files (markdown, `.tex` templates) are scanned for blocked patterns:

```python
BLOCKED_LATEX_PATTERNS = [
    r'\\write18',                  # shell command execution
    r'\\immediate\s*\\write',      # immediate shell execution
    r'\\input\s*\{',               # file inclusion (arbitrary paths)
    r'\\include\s*\{',             # file inclusion
    r'\\input\s*\|\s*"',           # pipe input from command
    r'\\openin',                   # low-level file read
    r'\\openout',                  # low-level file write
    r'\\newread',                  # file handle allocation
    r'\\newwrite',                 # file handle allocation
    r'\\directlua',               # Lua code execution (LuaLaTeX)
    r'\\latelua',                  # deferred Lua execution
    r'\\catcode',                  # character code redefinition (bypass tricks)
    r'\\usepackage\s*\{bashful\}', # bashful package enables shell commands
    r'\\usepackage\s*\{shellesc\}', # shell escape package
]
```

If any pattern is found, `reportgen` returns an error immediately — nothing
is extracted, no temp directory is created, no subprocess is spawned:

```
reportgen: blocked unsafe LaTeX command: \write18 (in /chapters/chapter2.md, line 14)
```

#### Execution Flow

```
1. Agent: reportgen /chapters/*.md -o /output/report.pdf --template /templates/report.tex

2. ShellExecutor:
   a. tree-sitter-bash parses → command_name: "reportgen"
   b. Tier 3 lookup → found in host-delegated commands
   c. Argument validation:
      - Parse args against reportgen's allowed CLI spec
      - Reject any unrecognized flags → exit_code=1, stderr="reportgen: unknown option: --filter"
      - Validate output path ends in .pdf

3. Security scan (BEFORE any files leave MemFS):
   - Glob /chapters/*.md against MemFS → chapter1.md, chapter2.md, chapter3.md
   - Read /templates/report.tex from MemFS
   - Scan ALL text files against BLOCKED_LATEX_PATTERNS
   - If any match → exit_code=1, stderr with file + line number, STOP
   - No temp directory created, no files copied to host

4. File extraction (only reached if scan passes):
   - Read validated files from MemFS
   - Scan markdown for image references (![...](path)) → read chart.png etc.
   - Write all to host temp dir preserving relative structure:
     /tmp/agentbox-{id}/chapters/chapter1.md
     /tmp/agentbox-{id}/chapters/chapter2.md
     /tmp/agentbox-{id}/chapters/chapter3.md
     /tmp/agentbox-{id}/chapters/chart.png
     /tmp/agentbox-{id}/templates/report.tex

5. Host execution (defense-in-depth even after scan):
   - Build pandoc command from validated args:
     pandoc /tmp/.../chapters/chapter1.md /tmp/.../chapters/chapter2.md ... \
       -o /tmp/.../output/report.pdf \
       --template=/tmp/.../templates/report.tex \
       --pdf-engine=latexmk --pdf-engine-opt=-pdf \
       -no-shell-escape \
       --sandbox
   - Defense-in-depth flags:
     - --sandbox (pandoc 2.19+): restricts pandoc's own file access
     - -no-shell-escape: disables \write18 in latexmk/pdflatex
     - NOTE: Consider switching to tectonic, which has no shell escape
       support at all by design (~50MB vs ~500MB+ for texlive,
       single binary). Would replace latexmk + texlive entirely.
   - Subprocess restrictions:
     - No network access (Linux: unshare --net)
     - Timeout (default 60s, configurable)
     - Read-only inputs, writable output dir only
     - chroot or bind-mount to temp dir (process cannot see host filesystem)
   - Capture exit_code, stdout, stderr

6. Result injection:
   - Read /tmp/.../output/report.pdf
   - Write into MemFS at /output/report.pdf
   - Clean up temp dir

7. Return: {exit_code: 0, stdout: "", stderr: ""}
```

#### Security Layers Summary

| Layer | When | Protection |
|---|---|---|
| 1. CLI validation | Before scan | Only allowed flags accepted |
| 2. Input scanning | Before temp dir | Blocked LaTeX patterns rejected |
| 3. `pandoc --sandbox` | During execution | Pandoc restricts its own file access |
| 4. `--no-shell-escape` | During execution | Disables \write18 in latexmk (tectonic under consideration — has no shell escape at all) |
| 5. chroot / bind-mount | During execution | Process cannot see host filesystem |
| 6. No network | During execution | `unshare --net` prevents exfiltration |
| 7. Timeout | During execution | Kills runaway processes |

#### Host-Delegated Command Registration

```python
# In BoxManager / service config
HOST_COMMANDS = {
    "reportgen": {
        "handler": "agentbox.box.shell.host_commands.reportgen",
        "binary": "/usr/bin/pandoc",        # actual host binary
        "timeout": 60,
        "max_input_size_mb": 50,
        "max_output_size_mb": 100,
        "requires": ["pandoc", "latexmk"],  # checked at startup
    },
    # Future host-delegated commands would follow the same pattern:
    # "imgconvert": { ... }  # ImageMagick wrapper
    # "csvformat": { ... }   # csvkit wrapper
}
```

Each host-delegated command is implemented as a Python module in
`agentbox/box/shell/host_commands/` that:
1. Defines the allowed CLI spec (argparse-style)
2. Validates arguments
3. Handles file extraction from MemFS
4. Builds the real subprocess command
5. Handles result injection back to MemFS

```
agentbox/box/shell/host_commands/
├── __init__.py
├── base.py               # HostCommand base class with extract/inject/validate
└── reportgen.py          # reportgen implementation
```

#### Adding New Host-Delegated Commands

To add a new host-delegated command:
1. Create a module in `host_commands/` extending `HostCommand`
2. Define the allowed CLI parameters
3. Implement `extract_files()` — which MemFS files need to go to the host
4. Implement `build_command()` — how to translate to the real binary
5. Implement `inject_results()` — which output files go back to MemFS
6. Register in `HOST_COMMANDS` config
7. Ensure the binary is installed in the Docker image

### 1.7 Messaging Bridge Enhancement

The current `sendMessage` bridge is hardcoded with a stub response. Make it
pluggable so the service can route messages to external systems:

- Define a `MessageHandler` protocol/interface
- Default: echo handler (current behavior)
- Configurable: HTTP callback URL, or in-process handler
- This enables agents to query knowledge graphs, databases, or other services
  from inside the sandbox

### 1.8 Dependencies Update

Add to `setup.py` or migrate to `pyproject.toml`:
- `fastapi`
- `uvicorn[standard]`
- `pydantic>=2.0`
- `httpx` (for client library)
- `tree-sitter` (parsing library — MIT license, pre-compiled wheels)
- `tree-sitter-bash` (bash grammar — MIT license, pre-compiled wheels)
- Remove `lark` (replaced by tree-sitter-bash)

### 1.9 Docker Image

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y \
    <chromium-deps> \
    pandoc \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    latexmk \
    && rm -rf /var/lib/apt/lists/*
# NOTE: Currently using latexmk + texlive (~500MB+).
# Consider switching to tectonic (~50MB, single binary, no shell escape
# by design). Would replace the texlive + latexmk packages above.
RUN pip install vital-agentbox && playwright install chromium
COPY pyodide-bundle/ /opt/pyodide/
EXPOSE 8000
CMD ["uvicorn", "agentbox.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 1.10 Tests

- Unit tests for BoxManager (mock Playwright)
- Integration tests for API endpoints (TestClient)
- Load test: create N sandboxes, execute code concurrently, verify isolation
- Timeout and error handling tests
- Shell command tests:
  - Simple commands: `ls /`, `cat /file.txt`, `echo hello`
  - Redirects: `echo content > /file.txt`, `cat /a >> /b`
  - Pipes: `cat /file.txt | grep pattern | wc -l`
  - Chaining: `mkdir /foo && echo test > /foo/bar.txt && cat /foo/bar.txt`
  - Error handling: `cat /nonexistent || echo fallback`
  - Variable expansion: `export FOO=bar && echo $FOO`
  - Command substitution: `echo $(cat /file.txt)`
  - Python delegation: `python -c "print('hello')"`
  - Command allowlist: verify unknown commands return "command not found"
  - cwd tracking: `cd /foo && ls` lists /foo contents
- Host-delegated command tests:
  - `reportgen` with valid args produces PDF in MemFS
  - `reportgen` rejects blocked flags (`--filter`, `--lua-filter`)
  - `reportgen` rejects unknown flags
  - File extraction correctly resolves image references in markdown
  - Timeout enforcement on long-running host commands
  - Large file size limits enforced

---

## Box Types

The sandbox has two modes, determined at creation time. Both run in the
same Chromium + Pyodide + WASM sandbox — the difference is persistence
and versioning.

### MemBox (default)

Purely in-memory. Files live in Emscripten MemFS. When the sandbox is
destroyed, everything is gone. This is the `CodeExecutorBox`.

```
POST /sandboxes  →  {type: "mem"}  (default)
```

- Agent reads/writes files, executes code, runs shell commands
- All state is ephemeral
- Fastest — no sync overhead
- Use for: stateless tasks, one-shot code execution, data analysis

### GitBox

Same sandbox, but with **isomorphic-git** loaded in the browser page,
using MemFS as its filesystem backend. The agent sees a git repo and
can use standard git commands. Commits are synced to a **permanent store**
on the host via Tier 3 host-delegated commands.

```
POST /sandboxes  →  {type: "git", repo: "task-12345"}
  - Creates sandbox with isomorphic-git initialized on MemFS
  - If repo exists in permanent store, clones it into MemFS on startup
  - If repo is new, initializes an empty git repo at /workspace
```

#### Agent Experience

```bash
# Files are in a git repo at /workspace
cd /workspace
echo "# Report" > report.md
git add report.md
git commit -m "Initial draft"

# Run code that generates output
python -c "import matplotlib.pyplot as plt; plt.savefig('/workspace/chart.png')"
git add chart.png
git commit -m "Add chart"

# View history
git log --oneline
# a1b2c3d Add chart
# e4f5g6h Initial draft

# Push to permanent store (Tier 3 → host-side sync)
git push

# Branch
git branch analysis
git checkout analysis
```

#### Shell Command Dispatch for Git

Git commands are dispatched as follows:

| Command | Tier | Runs where |
|---|---|---|
| `git init`, `git add`, `git commit` | **Tier 1** (in-sandbox) | isomorphic-git on MemFS |
| `git log`, `git status`, `git ls-files` | **Tier 1** (in-sandbox) | isomorphic-git on MemFS |
| `git diff` | **Tier 1** (in-sandbox) | Unified diff via `gitHelpers.readFileAtRef()` + FS, filepath filter |
| `git show` | **Tier 1** (in-sandbox) | Commit info + `ref:path` file content via `gitHelpers` |
| `git branch`, `git checkout`, `git merge` | **Tier 1** (in-sandbox) | isomorphic-git on MemFS |
| `git tag` (list, create, delete) | **Tier 1** (in-sandbox) | `git.tag()`, `git.listTags()`, `git.deleteTag()` |
| `git rev-parse` | **Tier 1** (in-sandbox) | `git.resolveRef()`, `git.currentBranch()`, `--show-toplevel` |
| `git cat-file -p` | **Tier 1** (in-sandbox) | `git.readObject()` / `readCommit()` / `readTree()` |
| `git mv` | **Tier 1** (in-sandbox) | `FS.rename()` + `git.remove()` + `git.add()` |
| `git rm` | **Tier 1** (in-sandbox) | `git.remove()` + `FS.unlink()` |
| `git reset --hard` | **Tier 1** (in-sandbox) | `git.checkout({ force: true })` |
| `git config` | **Tier 1** (in-sandbox) | Env vars (`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`) |
| `git push` | **Tier 3** (host-delegated) | Extract objects from MemFS → S3 permanent store |
| `git pull` | **Tier 3** (host-delegated) | S3 permanent store → inject into MemFS |
| `git clone <uri>` | **Tier 3** (host-delegated) | Fetch remote → inject into MemFS |

Local git operations (20 subcommands) happen **entirely inside the sandbox**
via isomorphic-git — no security boundary crossed, no host interaction.
Only push/pull/fetch/clone cross to the host.

#### isomorphic-git in the Browser Page

isomorphic-git is a pure JavaScript git implementation (~500KB) that runs
in browsers and Node.js. It uses a pluggable filesystem backend — we point
it at Emscripten's FS (the same MemFS already in use).

Two JS modules are injected into the browser page at GitBox startup
(defined in `agentbox/box/git/fs_adapter.py`):

1. **`window.fsAdapter`** — Wraps Emscripten's synchronous FS as the
   `fs.promises.*` interface isomorphic-git expects. Handles `mkdirp` for
   nested `.git/objects/` paths and translates errors to Node.js error codes.

2. **`window.gitHelpers`** — Higher-level helpers composing isomorphic-git
   primitives. Reusable across subcommands:
   - `readFileAtRef(dir, ref, filepath)` — Resolves ref → commit → tree,
     walks path segments, reads blob. Returns file content as string, or
     `null` if not found. Used by `git show ref:path` and `git diff`.

```javascript
// Loaded in the Chromium page alongside Pyodide
const git = window.git;           // isomorphic-git UMD
const fs = window.fsAdapter;      // Emscripten FS adapter

await git.init({ fs, dir: '/workspace' });
await git.add({ fs, dir: '/workspace', filepath: 'report.md' });
await git.commit({
  fs, dir: '/workspace',
  message: 'Initial draft',
  author: { name: 'Agent', email: 'agent@agentbox' }
});

// Higher-level helper
const content = await window.gitHelpers.readFileAtRef('/workspace', 'HEAD', 'report.md');
```

Each git subcommand is implemented as a module-level JS constant
(`_GIT_INIT_JS`, `_GIT_MERGE_JS`, etc.) in `builtin_git.py`. The Python
dispatcher parses args and calls `memfs.page.evaluate(JS_CONST, [args])`.

#### Permanent Store: S3

The host is **stateless** — it does not store repos on its filesystem. When
the agent pushes, the host reads files from MemFS and writes them as
individual S3 objects. The host is just a proxy between the sandbox and
the permanent store.

The storage backend is **pluggable** — S3, MinIO (self-hosted S3-compatible),
or local filesystem. Each file is stored individually, preserving the path
structure:

```
{store}/{repo-id}/workspace/report.md
{store}/{repo-id}/workspace/chart.png
{store}/{repo-id}/workspace/output/report.pdf
{store}/{repo-id}/.git/refs/heads/main
{store}/{repo-id}/.git/objects/ab/cdef1234...
```

This means:
- **Individual asset access** — fetch `report.pdf` directly without pulling
  the entire repo
- **Incremental sync** — only push/pull changed objects, not the whole repo
- **Standard tooling** — browse, list, download individual files with
  any S3/filesystem client

**Push flow:**
```
Agent: git push
  → Tier 3 host-delegated command (via sendMessage bridge)
  → Host reads /workspace/.git/* from MemFS (via page.evaluate)
  → Diff against store listing (or track dirty objects) → upload only changed objects
  → Each object → individual PUT to storage backend
  → Return {exit_code: 0}
```

**Pull / clone flow (or sandbox restore):**
```
Agent: git pull (or sandbox created with existing repo)
  → Tier 3 host-delegated command (via sendMessage bridge)
  → Host lists {store}/{repo-id}/.git/*
  → Downloads objects (all on first clone, or incremental on pull)
  → Writes into MemFS (via page.evaluate)
  → isomorphic-git sees its own data, checks out working tree
  → Return {exit_code: 0}
```

**Direct asset access (outside the sandbox):**
```
# Retrieve a specific file from an agent's repo — no sandbox needed
GET /repos/{repo-id}/files/read?path=/workspace/output/report.pdf
  → Reads from storage backend, returns the file
```

#### Sync Model

By default, every `git commit` automatically syncs to S3 behind the
scenes (`auto_sync: true`). This ensures no committed work is lost if the
sandbox is destroyed unexpectedly.

- `git commit` (auto_sync on) — isomorphic-git commits locally, then the
  shell builtin automatically triggers an S3 sync of changed objects.
  The agent sees normal commit output and doesn't know about the sync.
- `git commit` (auto_sync off) — local only, no S3 sync. Standard git
  behavior. Only `git push` persists.
- `git push` — always triggers S3 sync regardless of auto_sync setting.
  Also works for explicit control when auto_sync is off.
- Uncommitted changes (dirty working tree) are always lost on sandbox
  destroy — only committed state can be synced.

```
POST /sandboxes {type: "git", repo: "task-12345"}               # auto_sync: true (default)
POST /sandboxes {type: "git", repo: "task-12345", auto_sync: false}  # explicit push only
```

#### Sandbox Lifecycle with GitBox

```
1. Create: POST /sandboxes {type: "git", repo: "task-12345"}
   → Chromium page created, Pyodide + isomorphic-git loaded
   → If repo exists in S3: download .git/ + working tree into MemFS
   → If new: git init /workspace

2. Work: Agent edits files, commits, branches — all in-memory
   → git commit automatically syncs to S3 (default)
   → Uncommitted changes remain in MemFS only

3. Destroy: DELETE /sandboxes/{id}
   → MemFS freed
   → All committed (and synced) state persists in S3
   → Uncommitted changes are lost

4. Resume: POST /sandboxes {type: "git", repo: "task-12345"}
   → New sandbox, restores last synced state from S3
```

#### Configuration

```python
# BoxManager config — pluggable storage backend
GIT_STORE = {
    "backend": "s3",  # "s3" | "minio" | "local"

    # S3 / MinIO
    "s3_bucket": "agentbox-repos",
    "s3_prefix": "repos/",
    "s3_endpoint": None,  # Set for MinIO, e.g. "http://localhost:9000"

    # Local filesystem (for development / testing)
    "local_path": "/data/agentbox-repos/",
}
```

#### Dependencies for GitBox

- `isomorphic-git` — loaded into browser page (bundled JS, ~500KB)
- `boto3` or `httpx` — for S3/MinIO uploads/downloads on the host
- No Dulwich, no SQLite, no git binary on the host

### FileSystemBox (local development)

For running locally without a browser sandbox. Backed by a host directory.
Useful for development and testing where isolation isn't required.
Not used in production deployments.

---

## Implementation Priority

Within Phase 1, the priority order is:

1. ~~**tree-sitter-bash parsing + Tier 1 builtins**~~ — **DONE**.
   Implemented in `agentbox/box/shell/`:
   - `shell_executor.py` — top-level entry, parses with tree-sitter-bash
   - `cst_walker.py` — walks CST, dispatches to builtins, handles
     pipelines, `&&`/`||`, redirects (`>`, `>>`, `2>&1`), variable
     expansion, command substitution
   - `builtins.py` — registry importing 33 builtins from `buildin_exec/`
   - `environment.py` — shell state (cwd, variables, path resolution)
   - 37/37 Tier 1 tests pass (`test/test_shell_executor.py`)

2. ~~**Tier 2: Pyodide command dispatch**~~ — **DONE**.
   `python` / `python3` commands delegate to Pyodide on the same
   Playwright page via `memfs.page.evaluate()`. Supports:
   - `python -c "code"` — inline execution
   - `python script.py [args]` — read script from MemFS, set sys.argv
   - `echo "code" | python` — stdin piping
   - Python ↔ MemFS file I/O (open/read/write work on shared FS)
   - stdout/stderr capture, error handling, cwd sync
   - `SystemExit(0)` handled cleanly (no traceback for clean exits)
   - 48/48 tests pass (Tier 1 + Tier 2 combined)

3. ~~**isomorphic-git spike**~~ — **DONE** (see spike results below).

4. ~~**Builtins refactor + virtual /bin**~~ — **DONE**.
   - All 33 builtins moved into modular `buildin_exec/` exec classes
     (15 files), `builtins.py` reduced to imports-only registry
   - Virtual `/bin` directory: `ls /bin`, `which`, `type`, `cat /bin/<name>`
     all work without creating real MemFS files
   - `pip`/`pip3` builtin added (micropip + importlib.metadata)

5. ~~**Git subcommand expansion**~~ — **DONE**.
   20 Tier 1 git subcommands implemented in `builtin_git.py`:
   - Core: `init`, `add`, `commit`, `log`, `status`, `ls-files`
   - Branching: `branch`, `checkout`, `merge`
   - Inspection: `show` (commit info + `ref:path`), `diff` (unified format
     with filepath filter), `cat-file -p`, `rev-parse`
   - Mutation: `rm`, `mv`, `reset --hard`
   - Tagging: `tag` (list, create lightweight/annotated, delete)
   - Config: `config` (user.name, user.email via env vars)
   - `gitHelpers` JS layer in `fs_adapter.py` provides `readFileAtRef()`
     reusable across subcommands
   - Deep Agents git example passes cleanly (0 SystemExit, 0 TextIOWrapper
     errors, only expected pytest ImportError failures)

6. ~~**Pyodide upgrade**~~ — **DONE**. Updated to v0.29.3 (Python 3.13).
   Local bundling supported via `AGENTBOX_PYODIDE_URL` env var and
   `scripts/download_pyodide.sh`. Docker worker image bundles Pyodide
   locally (no CDN dependency at runtime).

7. ~~**Sandbox lifecycle + BoxManager + FastAPI**~~ — **DONE**.
   - `BoxManager` (`agentbox/manager/box_manager.py`): sandbox pool with
     create/destroy/execute, background reaper (idle + max lifetime),
     configurable via env vars (`AGENTBOX_MAX_SANDBOXES`, `AGENTBOX_IDLE_TIMEOUT`,
     `AGENTBOX_MAX_LIFETIME`). Supports both MemBox and GitBox creation.
   - Worker FastAPI app (`agentbox/api/app.py`): lifespan manages BoxManager,
     serves public routes (health, sandbox CRUD, execute, files) and internal
     routes (for orchestrator proxying). Self-registers with orchestrator on
     startup, heartbeat loop, deregisters on shutdown.
   - Worker routes: `health.py`, `sandbox.py`, `execute.py`, `files.py`,
     `internal.py` — full API surface from the plan.
   - Local Pyodide bundle served via `StaticFiles` mount.

8. ~~**JWT authentication**~~ — **DONE** (was Phase 3.2, pulled forward).
   - `agentbox/api/auth.py`: configurable JWT middleware supporting
     JWKS URI (Keycloak/OIDC auto-key-fetch), static public key (RS256/ES256),
     and shared secret (HS256). Keycloak `realm_access.roles` + `resource_access`
     mapped to scopes. Token claims available to route handlers. Admin role
     enforcement via `require_scope()`. Exempt paths: `/health`, `/internal/*`.

9. ~~**Orchestrator**~~ — **DONE** (was Phase 3.5, pulled forward).
   - `agentbox/orchestrator/app.py`: lightweight FastAPI gateway, Redis-backed
     (standalone + Cluster/MemoryDB), JWT middleware.
   - `agentbox/orchestrator/state.py`: `OrchestratorState` with worker registry,
     sandbox routing table, sandbox database, per-tenant indexes, aggregate
     metrics. All single-key Redis commands (cluster-safe).
   - `agentbox/orchestrator/proxy.py`: HTTP proxy to forward requests to
     owning worker via sandbox→worker routing lookup.
   - `agentbox/orchestrator/routes/workers.py`: self-registration, heartbeat,
     deregistration, admin worker listing.
   - `agentbox/orchestrator/routes/sandboxes.py`: create (picks best worker),
     list (tenant-scoped), get, destroy, execute, shell, file ops — all proxied.
     S3-safe repo_id validation, tenant-scoped repo paths.
   - `agentbox/orchestrator/routes/admin.py`: admin list/inspect/browse/read/
     force-destroy/bulk-destroy sandboxes, tenant summary. Requires admin scope.
   - Health + metrics endpoints with aggregate worker stats.

10. ~~**Tier 3 host-delegated commands**~~ — **DONE**.
    - `agentbox/box/shell/host_commands/__init__.py`: HOST_COMMANDS registry
      with `reportgen`, `git-push`, `git-pull`, `git-fetch`, `git-clone`.
    - `host_commands/reportgen.py`: full pandoc wrapper — arg validation,
      LaTeX security scanning (13 blocked patterns), glob resolution, MemFS
      extraction to temp dir, pandoc subprocess with timeout, PDF injection
      back to MemFS, temp cleanup.
    - `host_commands/git_sync.py`: push/pull/fetch/clone via pluggable
      storage backend. Incremental push (tracks last-pushed SHA),
      pull with checkout, fetch (objects only).
    - `agentbox/box/git/storage.py`: `StorageBackend` ABC with
      `LocalStorageBackend` (filesystem) and `S3StorageBackend` (boto3).
    - `agentbox/box/git/sync.py`: `push_to_store()` and `pull_from_store()`
      — recursive MemFS walk, base64 binary transfer, incremental object sync.

11. ~~**Deep Agents integration**~~ — **DONE** (was Phase 2.2).
    - `agentbox/deepagents/sandbox.py`: `AgentBoxSandbox(BaseSandbox)` —
      implements `execute()`, `upload_files()`, `download_files()`, `id`.
      Background event loop for httpx IO, command logging with exit status.
    - `AgentBoxSandbox.create()` classmethod for one-shot sandbox creation.
    - Deep Agents git example (`examples/deep_agents_git.py`) passes cleanly.

12. ~~**Docker images + docker-compose**~~ — **DONE**.
    - `Dockerfile.orchestrator`: thin image (FastAPI + redis, no Chromium).
    - `Dockerfile.worker`: heavy image (Chromium + Pyodide bundle).
    - `docker-compose.yml`: orchestrator + worker + MinIO, local dev mode.

13. ~~**Ops integration**~~ — **DONE**.
    - `agentbox/box/shell/host_commands/boxcp.py`: `boxcp` Tier 3 host command.
      URI dispatch: `s3://bucket/key`, `local:///path`, bare MemFS paths.
    - S3 provider: reuses boto3, `AGENTBOX_S3_ENDPOINT` for MinIO compat.
    - local provider: restricted to `AGENTBOX_BOXCP_LOCAL_ALLOW` dirs (path
      traversal safe). Size limit via `AGENTBOX_BOXCP_MAX_SIZE` (default 100MB).
    - Binary-safe (base64 MemFS transfer). At least one side must be MemFS.
    - Registered in HOST_COMMANDS + virtual `/bin` (39 total commands).
    - `test/test_boxcp.py`: 24/24 tests (MemFS, local, S3/MinIO, binary
      round-trip, security allowlist, error handling).

### Spike Results: Binary Transfer + isomorphic-git

Validated in `test/test_spike_binary_and_git.py`.

**Binary file transfer: base64 via `page.evaluate()`**

| Size | Write | Read | Total |
|------|-------|------|-------|
| 1KB | 2ms | 1.5ms | 3.5ms |
| 10KB | 2.3ms | 2ms | 4.3ms |
| 100KB | 5.8ms | 6.3ms | 12ms |
| 1MB | 46ms | 48ms | 94ms |

Base64 is fast enough for any realistic agent repo. A list-of-ints approach
(passing ArrayBuffer as JS array) was 50x slower and eliminated.

**isomorphic-git on Emscripten MemFS: all operations pass**

Confirmed working: `git init`, `git add`, `git commit`, `git log`,
`git status`, `git branch` — all on MemFS inside Chromium.

Key findings:
- **FS adapter required** — Emscripten's FS is not directly compatible
  with isomorphic-git's expected `fs.promises` API. A thin adapter wraps
  each method as an arrow function (avoids `this` binding issues when
  isomorphic-git destructures methods).
- **`mkdirp` required** — Emscripten FS does not auto-create parent
  directories. The adapter's `writeFile` calls `mkdirp` on the parent
  path before writing (isomorphic-git writes to paths like
  `.git/objects/ab/cdef...`).
- **isomorphic-git loaded via CDN** — `~500KB` UMD bundle. Will be
  bundled locally for production (same as Pyodide).

---

## Phase 2: Client Library

### 2.1 AgentBox Python Client (`agentbox-client`)

A lightweight SDK that wraps the HTTP API. No Playwright dependency — just `httpx`.

```
agentbox_client/
├── __init__.py
├── client.py           # AgentBoxClient class
├── sandbox.py          # Sandbox resource object
├── models.py           # Response types
└── exceptions.py       # AgentBoxError, SandboxNotFound, ExecutionTimeout
```

Usage:

```python
from agentbox_client import AgentBoxClient

client = AgentBoxClient(base_url="http://localhost:8000")

# Create a MemBox (default — ephemeral, in-memory)
sandbox = client.create_sandbox()

# Or create a GitBox (persistent, versioned)
sandbox = client.create_sandbox(type="git", repo="task-12345")

# Execute code
result = sandbox.execute("print('hello world')")
print(result.output)

# File operations
sandbox.write_file("/data.txt", "some content")
content = sandbox.read_file("/data.txt")
files = sandbox.list_dir("/")

# Shell command execution
result = sandbox.shell("ls -la / && cat /data.txt")

# Cleanup
sandbox.destroy()
```

Async variant:

```python
from agentbox_client import AsyncAgentBoxClient

async with AsyncAgentBoxClient(base_url="http://localhost:8000") as client:
    sandbox = await client.create_sandbox()
    result = await sandbox.execute(code)
    await sandbox.destroy()
```

### 2.2 LangChain Deep Agents Integration (`langchain-agentbox`)

Implements `BackendProtocol` and `SandboxBackendProtocol` from Deep Agents so
AgentBox can be used as a drop-in sandbox backend.

```
langchain_agentbox/
├── __init__.py
└── sandbox.py          # AgentBoxSandbox(BaseSandbox)
```

BackendProtocol methods mapped to AgentBox API:

| Deep Agents Method | AgentBox API Call |
|--------------------|-------------------|
| `ls_info(path)` | `GET /sandboxes/{id}/files?path=...&info=true` |
| `read(file_path)` | `GET /sandboxes/{id}/files/read?path=...` |
| `write(file_path, content)` | `POST /sandboxes/{id}/files/write` |
| `edit(file_path, old, new)` | Read → replace → write (client-side) |
| `glob_info(pattern)` | Implement via ls + client-side glob matching, or add server endpoint |
| `grep_raw(pattern)` | Implement via file listing + content search, or add server endpoint |
| `execute(command)` | `POST /sandboxes/{id}/execute` (language: "shell") |

Usage with Deep Agents:

```python
from agentbox_client import AgentBoxClient
from langchain_agentbox import AgentBoxSandbox
from deepagents import create_deep_agent

client = AgentBoxClient(base_url="http://localhost:8000")
sandbox = client.create_sandbox()
backend = AgentBoxSandbox(sandbox=sandbox)

agent = create_deep_agent(
    backend=backend,
    system_prompt="You are a coding assistant with sandbox access.",
)

result = agent.invoke({
    "messages": [{"role": "user", "content": "Create and run a Python script"}]
})

sandbox.destroy()
```

---

## Phase 3: Production Hardening

### 3.1 WebSocket Support for Streaming Output

Add `WS /sandboxes/{id}/execute/stream` for real-time stdout streaming during
long-running code execution. Currently output is only available after completion.

### 3.2 Authentication — JWT Enforcement

Both the orchestrator and worker support **configurable JWT authentication**.
When enabled, every request must include a valid `Authorization: Bearer <token>`
header. Tokens are verified against a shared secret or public key.

**Configuration (env vars):**
- `AGENTBOX_JWT_ENABLED` — `true` to enforce JWT on all endpoints (default: `false`)
- `AGENTBOX_JWT_SECRET` — HMAC secret for HS256 tokens (simple shared-secret mode)
- `AGENTBOX_JWT_PUBLIC_KEY` — RSA/EC public key for RS256/ES256 tokens (asymmetric mode)
- `AGENTBOX_JWT_ALGORITHM` — `HS256`, `RS256`, or `ES256` (default: `HS256`)
- `AGENTBOX_JWT_ISSUER` — expected `iss` claim (optional, for validation)
- `AGENTBOX_JWT_AUDIENCE` — expected `aud` claim (optional, for validation)

**Behavior:**
- When `AGENTBOX_JWT_ENABLED=false` (default): no auth — suitable for local dev
  and internal-only workers behind a firewall.
- When `AGENTBOX_JWT_ENABLED=true`: all endpoints except `GET /health` require a
  valid JWT. Invalid/missing tokens return `401 Unauthorized`.
- The orchestrator and workers can use the **same** JWT secret (simple) or the
  orchestrator can sign tokens that workers verify (asymmetric). In the asymmetric
  model, only the orchestrator holds the private key; workers hold the public key.
- JWT claims can carry tenant/scope info for multi-tenancy:
  - `sub` — tenant identifier
  - `scope` — `admin`, `sandbox:create`, `sandbox:execute`, etc.
  - `sandbox_limit` — max concurrent sandboxes for this tenant

**Multi-Tenancy (via JWT claims):**
- Per-tenant sandbox limits and quotas (enforced by orchestrator)
- Sandbox ownership — tenants can only access their own sandboxes
- Admin scope grants access to all sandboxes and worker management endpoints

### 3.3 Ops Integration

Wire up the existing `agentbox/ops/` stubs as host-delegated commands
using the `boxcp` shell command and direct API endpoints:

#### `boxcp` — Copy Between Sandbox and External Services

A Tier 3 host-delegated command for importing/exporting files:

```bash
# Import from S3 into sandbox
boxcp s3://bucket/data/report.csv /data/report.csv

# Export from sandbox to S3
boxcp /output/report.pdf s3://bucket/reports/report.pdf

# Import from GitHub repo
boxcp github://owner/repo/src/main.py /workspace/main.py --branch main

# Import from Google Cloud Storage
boxcp gs://bucket/models/config.json /config.json

# Copy from local host directory (restricted allowlist)
boxcp local:///data/shared/templates/ /templates/
```

| URI Scheme | Service | Ops Module |
|---|---|---|
| `/path` | MemFS (current sandbox) | — |
| `s3://bucket/key` | AWS S3 | `agentbox/ops/s3/` |
| `github://owner/repo/path` | GitHub API | `agentbox/ops/github/` |
| `gs://bucket/key` | Google Cloud Storage | `agentbox/ops/gs/` |
| `gdrive://path` | Google Drive | `agentbox/ops/gdrive/` |
| `local://path` | Host filesystem (restricted) | `agentbox/ops/drive/` |

Security:
- URI schemes must be in a per-sandbox allowlist
- Credentials (AWS keys, GitHub tokens) stored on host — never in sandbox
- `local://` is heavily restricted to allowlisted directories
- Rate limits and size limits per service

These also have API endpoints for the client library:
- `POST /sandboxes/{id}/ops/copy` → `{src, dst}` (URI-based)
- `POST /sandboxes/{id}/ops/import/s3` → `{bucket, key, dest_path}`
- `POST /sandboxes/{id}/ops/export/s3` → `{src_path, bucket, key}`

### 3.5 ECS Deployment — Orchestrator + Worker Architecture

AgentBox uses a two-service architecture for production ECS deployment.
The **Orchestrator** is a lightweight API gateway that manages sandbox routing
and worker lifecycle. **Workers** are headless Chromium containers that run
sandboxes. Each has its own Docker image, ECS service, and REST API.

```
                    ┌─────────────────────────────────────┐
                    │          ALB (public)                │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │       Orchestrator (ECS Service)     │
                    │  - Sandbox routing table             │
                    │  - Worker registry + health polling  │
                    │  - ECS RunTask / StopTask            │
                    │  - Auto-scale decisions              │
                    │  - Auth / rate limiting               │
                    │  - No Playwright, no Chromium        │
                    └──┬──────────────┬──────────────┬────┘
                       │              │              │
              ┌────────▼───┐  ┌──────▼─────┐  ┌────▼───────┐
              │  Worker 1  │  │  Worker 2  │  │  Worker N  │
              │  (ECS Task)│  │  (ECS Task)│  │  (ECS Task)│
              │  Chromium  │  │  Chromium  │  │  Chromium  │
              │  Pyodide   │  │  Pyodide   │  │  Pyodide   │
              │  BoxManager│  │  BoxManager│  │  BoxManager│
              └────────────┘  └────────────┘  └────────────┘
```

#### 3.5.1 Shared State (Redis / AWS MemoryDB)

Because the orchestrator runs as a multi-instance ECS Service (for HA), all
state must be shared across orchestrator instances. Redis provides:

- **Sandbox routing table** — `agentbox:route:{sandbox_id} → worker_id`
  (string key-value, TTL = sandbox max lifetime)
- **Worker registry** — `agentbox:worker:{worker_id} → {endpoint, capacity,
  state, last_heartbeat}` (hash per worker, TTL-based liveness)
- **Sandbox database** — `agentbox:sandbox:{sandbox_id} → {id, worker_id,
  box_type, repo_id, state, created_at, last_active, created_by, metadata}`
  (hash per sandbox, persists after destruction for audit trail)
- **Index sets** — `agentbox:sandboxes:index` (sorted set by created_at),
  `agentbox:sandboxes:by_tenant:{tid}` (set), `agentbox:workers:index` (set)
- **Global metrics** — aggregated counters for CloudWatch emission
- **Distributed locking** — for scale-up decisions (only one orchestrator
  instance should call `ecs:RunTask` at a time)

**Redis Cluster / AWS MemoryDB compatibility:**

The state layer is designed to work with both standalone Redis and Redis
Cluster (including AWS MemoryDB). Key design constraints:

- Every Redis command operates on a **single key**. No multi-key operations
  (MGET, MSET, SUNION, KEYS, SCAN) are used anywhere.
- Methods that touch multiple keys (e.g., `create_sandbox_record` writes a
  hash, updates a sorted set index, and updates a per-tenant set) issue
  separate single-key commands. These are not atomic across keys, which is
  acceptable — eventual consistency is fine for indexes.
- The `update_sandbox_state` method uses a single `HSET` with a mapping
  to update multiple fields atomically on the same key.
- No `KEYS`, `SCAN`, `FLUSHDB`, or other cluster-unfriendly commands.

**Supported backends:**
- **Standalone Redis** — local dev, single-node ElastiCache
- **Redis Cluster** — ElastiCache Cluster Mode Enabled
- **AWS MemoryDB** — Redis-compatible, durable, cluster-mode, TLS required
- **Valkey** — Redis-compatible, AWS-managed alternative

**Configuration (env vars):**
- `AGENTBOX_REDIS_URL` — Connection URL (default: `redis://localhost:6379`).
  Use `rediss://` for TLS (required for MemoryDB).
- `AGENTBOX_REDIS_CLUSTER` — Set to `true` for Redis Cluster mode (MemoryDB).
  Uses `redis.asyncio.RedisCluster` instead of `redis.asyncio.Redis`.
- `AGENTBOX_REDIS_USERNAME` — ACL username (optional, for MemoryDB ACL auth)
- `AGENTBOX_REDIS_PASSWORD` — Password / auth token (optional)
- `AGENTBOX_REDIS_TLS_SKIP_VERIFY` — Set to `true` to skip TLS cert
  verification (not recommended for production)
- `AGENTBOX_REDIS_PREFIX` — Key prefix (default: `agentbox:`)

#### 3.5.2 Orchestrator

Lightweight FastAPI service — no Playwright, no Chromium. Thin Docker image.

**Responsibilities:**
- Accept client requests and route to the correct worker
- Maintain the **sandbox routing table** in Redis: `sandbox_id → worker_id`
- Maintain the **worker registry** in Redis: `worker_id → {endpoint, capacity, health}`
- Accept **worker self-registration** (workers call orchestrator on startup)
- Spin up new worker ECS tasks via `ecs:RunTask` when capacity is low
- Drain and stop idle worker tasks via `ecs:StopTask`
- Periodic health polling of workers (calls `GET /internal/health`)
- Auth, rate limiting, request validation (workers trust the orchestrator)
- Aggregate metrics from all workers for CloudWatch

**Docker image:** `agentbox-orchestrator`
- Python 3.11 slim
- FastAPI + uvicorn + boto3 (AWS SDK) + redis
- No Playwright, no Chromium → ~200MB image

**ECS configuration:**
- ECS Service with desired count ≥ 2 (HA, stateless — all state in Redis)
- ALB target group with `/health` health check
- Task CPU: 0.5 vCPU, Memory: 1 GB
- IAM role: `ecs:RunTask`, `ecs:StopTask`, `ecs:DescribeTasks`,
  `ecs:ListTasks`, `servicediscovery:*` (Cloud Map)

**Orchestrator REST API (public-facing):**

```
# Sandbox lifecycle
POST   /sandboxes                    → Create sandbox (orchestrator picks worker, creates on it)
GET    /sandboxes                    → List all sandboxes across all workers
GET    /sandboxes/{id}               → Get sandbox status (proxied to worker)
DELETE /sandboxes/{id}               → Destroy sandbox (proxied to worker, clears routing)

# Execution (proxied to owning worker)
POST   /sandboxes/{id}/execute       → {code, language}
POST   /sandboxes/{id}/message       → sendMessage bridge

# File operations (proxied to owning worker)
GET    /sandboxes/{id}/files         → List directory
GET    /sandboxes/{id}/files/read    → Read file
POST   /sandboxes/{id}/files/write   → Write file
POST   /sandboxes/{id}/files/mkdir   → Create directory
DELETE /sandboxes/{id}/files         → Remove file
DELETE /sandboxes/{id}/files/dir     → Remove directory
POST   /sandboxes/{id}/files/copy    → Copy file
POST   /sandboxes/{id}/files/glob    → Glob match
POST   /sandboxes/{id}/files/grep    → Grep search

# Worker management (admin only)
GET    /workers                      → List all workers + capacity
POST   /workers/scale                → {desired_workers: N} manual scale
DELETE /workers/{id}                 → Drain + stop a specific worker

# Admin: sandbox management across all workers
GET    /admin/sandboxes              → List ALL sandboxes across all workers (with filters)
GET    /admin/sandboxes/{id}         → Full sandbox detail (state, worker, created_at, last_active)
GET    /admin/sandboxes/{id}/files   → Browse sandbox file tree (proxied to worker)
GET    /admin/sandboxes/{id}/files/read → Read file from sandbox (proxied to worker)
DELETE /admin/sandboxes/{id}         → Force-destroy sandbox on any worker

# System
GET    /health                       → Orchestrator + aggregate worker health
GET    /metrics                      → Aggregate pool metrics for CloudWatch
```

**Routing logic for `POST /sandboxes`:**
1. Read worker registry from Redis — get all workers with `state=active`
2. Pick worker with most `available` slots
3. If no worker has capacity, acquire Redis lock → call `ecs:RunTask` → release
4. `POST /internal/sandboxes` on chosen worker
5. Store `sandbox_id → worker_id` in Redis routing table (with TTL)
6. Return sandbox info to client

**Routing logic for `POST /sandboxes/{id}/execute` and all proxied calls:**
1. Look up `sandbox_id` in Redis routing table → `worker_id`
2. Look up `worker_id` in Redis worker registry → `endpoint`
3. Forward request to `{endpoint}/internal/sandboxes/{id}/execute`
4. Return worker response to client

Because all routing state is in Redis, **any orchestrator instance** can
handle any request — no sticky sessions needed on the orchestrator ALB.

#### 3.5.2a Orchestrator Sandbox Database

The orchestrator maintains a **persistent record of every sandbox** that has
been created through it. This goes beyond the Redis routing table (which is
for live routing) — it's a durable log of sandbox lifecycle.

**Storage:** Redis hash per sandbox, plus a secondary index for listing.

```
agentbox:sandbox:{sandbox_id} → {
    id: "sandbox_id",
    worker_id: "worker-xyz",
    box_type: "mem" | "git",
    repo_id: "task-123" | null,
    state: "running" | "idle" | "destroyed",
    created_at: "2026-02-22T17:00:00Z",
    last_active: "2026-02-22T17:05:00Z",
    created_by: "tenant-abc",       # from JWT sub claim
    metadata: { ... },               # arbitrary key-value from create request
}

agentbox:sandboxes:index → sorted set (score = created_at timestamp)
agentbox:sandboxes:by_tenant:{tenant_id} → set of sandbox_ids
```

This enables:
- **List all sandboxes** across all workers with filtering (by tenant, state, type)
- **Sandbox history** — records persist after destruction (marked `state=destroyed`)
- **Admin inspection** — view any sandbox's files and state without needing the
  owning worker's endpoint cached
- **Audit trail** — who created what, when, and how long it lived

**Admin management functions (orchestrator):**

| Function | Endpoint | Description |
|---|---|---|
| List all sandboxes | `GET /admin/sandboxes?state=running&tenant=X` | Filterable listing across all workers |
| Inspect sandbox | `GET /admin/sandboxes/{id}` | Full metadata + state + worker location |
| Browse files | `GET /admin/sandboxes/{id}/files?path=/` | Proxied directory listing |
| Read file | `GET /admin/sandboxes/{id}/files/read?path=/file.txt` | Proxied file read |
| Force destroy | `DELETE /admin/sandboxes/{id}` | Destroy on worker + update DB record |
| Bulk destroy | `POST /admin/sandboxes/bulk-destroy` | Destroy multiple sandboxes by filter |
| Tenant summary | `GET /admin/tenants` | Sandbox counts per tenant |

Admin endpoints require JWT with `scope=admin`. Regular tenant endpoints
(`/sandboxes/*`) only show sandboxes owned by the token's `sub` claim.

#### 3.5.3 Worker

Heavy container — runs Chromium + Pyodide sandboxes. This is the current
`agentbox.api.app` with an additional internal-only API prefix.

**Responsibilities:**
- **Self-register with orchestrator on startup** (POST to orchestrator)
- **Periodic heartbeat** to orchestrator (updates capacity + health in Redis)
- Manage a local pool of sandboxes via BoxManager
- Execute code, shell commands, file operations on its sandboxes
- **Deregister on graceful shutdown** (SIGTERM handler)
- No auth (trusts orchestrator, internal network only)

**Self-registration flow:**
1. Worker starts, initializes BoxManager, gets its own IP/port
2. Worker calls `POST {AGENTBOX_ORCHESTRATOR_URL}/internal/workers/register`
   with `{worker_id, endpoint, capacity}`
3. Orchestrator stores worker in Redis registry with TTL
4. Worker sends heartbeat every `AGENTBOX_HEARTBEAT_INTERVAL` seconds
   (re-registers with current capacity/metrics)
5. If heartbeat stops, Redis TTL expires → orchestrator considers worker dead
6. On SIGTERM, worker calls `POST .../internal/workers/deregister`

This means workers launched by ECS auto-scaling rules (not orchestrator)
also self-register and become available for sandbox placement automatically.

**Docker image:** `agentbox-worker`
- Python 3.11 + Playwright + Chromium
- Local Pyodide bundle (no CDN dependency)
- ~1.5-2GB image (Chromium is the bulk)

**ECS configuration:**
- Can be ECS Tasks (orchestrator-managed) OR an ECS Service (ECS-managed scaling)
- Task CPU: 2-4 vCPU, Memory: 4-8 GB
- `/dev/shm` size: 2 GB (required for Chromium)
- Security group: only accepts traffic from orchestrator SG
- No public ALB — workers are internal only

**Worker REST API (internal only, no auth):**

```
# Sandbox lifecycle
POST   /internal/sandboxes           → Create sandbox on this worker
GET    /internal/sandboxes           → List sandboxes on this worker
GET    /internal/sandboxes/{id}      → Get sandbox status
DELETE /internal/sandboxes/{id}      → Destroy sandbox

# Execution
POST   /internal/sandboxes/{id}/execute   → {code, language}
POST   /internal/sandboxes/{id}/message   → sendMessage bridge

# File operations
GET    /internal/sandboxes/{id}/files         → List directory
GET    /internal/sandboxes/{id}/files/read    → Read file
POST   /internal/sandboxes/{id}/files/write   → Write file
POST   /internal/sandboxes/{id}/files/mkdir   → Create directory
DELETE /internal/sandboxes/{id}/files         → Remove file
DELETE /internal/sandboxes/{id}/files/dir     → Remove directory
POST   /internal/sandboxes/{id}/files/copy    → Copy file

# Health + metrics (called by orchestrator)
GET    /internal/health              → {status, sandbox_count, capacity}
GET    /internal/metrics             → Full BoxManager metrics
```

#### 3.5.4 Scaling Strategy — Dual Scaling

Two complementary scaling mechanisms coexist:

**1. Orchestrator-driven scaling (application-level):**
- Orchestrator monitors aggregate capacity across all workers (via Redis)
- Scale-up: all workers report `available < 5` → acquire Redis lock →
  `ecs:RunTask` → new worker self-registers on startup
- Scale-up: `POST /sandboxes` arrives with no capacity → same flow
- Scale-down: worker idle (0 sandboxes) for > `AGENTBOX_WORKER_IDLE_DRAIN`
  → mark "draining" in Redis → no new sandboxes routed → once empty,
  `ecs:StopTask`
- Respects `AGENTBOX_MIN_WORKERS` floor — never scales below minimum

**2. ECS auto-scaling rules (infrastructure-level):**
- Workers can also be an ECS Service with target-tracking or step-scaling
- ECS scales based on CPU/memory utilization or custom CloudWatch metrics
  (e.g., `AgentBox/WorkerAvailableSlots` emitted by orchestrator)
- Workers launched by ECS auto-scaling self-register with orchestrator
  on startup — they automatically join the pool
- Workers stopped by ECS scale-in deregister via SIGTERM handler

Both mechanisms are safe to run simultaneously because:
- Worker self-registration is idempotent (re-register = update)
- Redis routing table is the single source of truth
- Orchestrator's `ecs:RunTask` checks current worker count before launching
- Redis distributed lock prevents duplicate scale-up from multiple
  orchestrator instances

**Configuration (env vars on orchestrator):**
- `AGENTBOX_MIN_WORKERS` — minimum worker count (default: 1)
- `AGENTBOX_MAX_WORKERS` — maximum worker count (default: 10)
- `AGENTBOX_WORKER_IDLE_DRAIN` — seconds before idle worker is drained (default: 300)
- `AGENTBOX_WORKER_TASK_DEFINITION` — ECS task definition ARN for workers
- `AGENTBOX_WORKER_CLUSTER` — ECS cluster name
- `AGENTBOX_WORKER_SUBNETS` — VPC subnets for worker tasks
- `AGENTBOX_WORKER_SECURITY_GROUP` — SG allowing orchestrator → worker traffic
- `AGENTBOX_REDIS_URL` — Redis connection (default: `redis://localhost:6379`)

**Configuration (env vars on worker):**
- `AGENTBOX_MAX_SANDBOXES` — max sandboxes per worker (default: 50)
- `AGENTBOX_IDLE_TIMEOUT` — per-sandbox idle timeout (default: 300)
- `AGENTBOX_MAX_LIFETIME` — per-sandbox max lifetime (default: 3600)
- `AGENTBOX_ORCHESTRATOR_URL` — orchestrator endpoint for self-registration
- `AGENTBOX_HEARTBEAT_INTERVAL` — seconds between heartbeats (default: 15)

#### 3.5.5 Docker Images

**Dockerfile.orchestrator:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install ".[server]" boto3 redis
COPY agentbox/ agentbox/
EXPOSE 8000
CMD ["uvicorn", "agentbox.api.orchestrator_app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Dockerfile.worker:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
    libgbm1 libpango-1.0-0 libasound2 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN pip install ".[server]" && python -m playwright install chromium
# Bundle Pyodide locally (no CDN dependency)
# COPY pyodide-bundle/ /app/pyodide-bundle/
COPY agentbox/ agentbox/
EXPOSE 8000
CMD ["uvicorn", "agentbox.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### 3.5.6 Deployment Modes

The architecture supports multiple deployment modes depending on scale:

**Mode 1: Single Worker (local dev / small deployment)**
```bash
make serve  # starts worker with BoxManager, no orchestrator needed
```
Client talks directly to the worker. No Redis, no orchestrator.

**Mode 2: Workers behind LB (no orchestrator)**
Multiple workers behind an ALB. No global sandbox routing — clients must
include a session cookie/header so the ALB routes to the same worker.
Simpler, but no global tracking or orchestrator-driven scaling.

**Mode 3: Full Orchestrator + Workers (production)**
Full architecture with Redis-backed routing, worker self-registration,
dual scaling. Clients always talk to orchestrator.

**docker-compose.yml (Mode 3 local testing):**
```yaml
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
  orchestrator:
    build:
      dockerfile: Dockerfile.orchestrator
    ports: ["8000:8000"]
    environment:
      AGENTBOX_REDIS_URL: "redis://redis:6379"
    depends_on: [redis]
  worker-1:
    build:
      dockerfile: Dockerfile.worker
    shm_size: 2g
    environment:
      AGENTBOX_ORCHESTRATOR_URL: "http://orchestrator:8000"
  worker-2:
    build:
      dockerfile: Dockerfile.worker
    shm_size: 2g
    environment:
      AGENTBOX_ORCHESTRATOR_URL: "http://orchestrator:8000"
```

Workers self-register with orchestrator on startup. No static endpoint
configuration needed — workers find orchestrator via env var, orchestrator
discovers workers via their registration calls.

#### 3.5.7 ECR Pipeline

- GitHub Actions workflow on push to `main`:
  1. Build `agentbox-orchestrator` image → push to ECR
  2. Build `agentbox-worker` image → push to ECR
  3. Update ECS orchestrator service (rolling deploy)
  4. Workers self-register on startup — no separate deploy step needed
  5. Workers launched by ECS auto-scaling also self-register automatically

### 3.6 Glob and Grep on Server

Add server-side `glob` and `grep` endpoints to avoid round-tripping all file
contents to the client for search operations:

- `GET /sandboxes/{id}/files/glob?pattern=**/*.py` → List matching files
- `POST /sandboxes/{id}/files/grep` → `{pattern, path?, glob?}` → Matching lines

These directly support Deep Agents' `glob_info` and `grep_raw` protocol methods.

---

## Phase 4: Advanced Features

### 4.1 Multi-Language Execution

Beyond Python and shell, for JavaScript/TypeScript execution, the browser
page can natively run JS via `page.evaluate()`. Extend the language parameter:

- `POST /sandboxes/{id}/execute` → `{code, language: "python"|"shell"|"javascript"}`

### 4.2 Package Installation

Support installing Pyodide-compatible packages within a sandbox:

- `POST /sandboxes/{id}/packages/install` → `{packages: ["numpy", "pandas"]}`
- Uses `pyodide.loadPackage()` under the hood
- Cached across sandboxes sharing the same browser (Pyodide package cache)

### 4.3 Hybrid Mode

For workloads that exceed Pyodide's capabilities (native C extensions, GPU,
large memory), integrate with external sandbox providers as a fallback:

- AgentBox detects when a package isn't Pyodide-compatible
- Optionally delegates to Modal/Daytona/E2B for that specific execution
- Transparent to the agent — same API, different backend

### 4.4 Deep Agents CompositeBackend Integration

Enable mixed backends where AgentBox handles file operations and lightweight
code execution while a cloud provider handles heavy compute:

```python
from deepagents.backends import CompositeBackend

composite = CompositeBackend(
    default=AgentBoxSandbox(sandbox),
    routes={
        "/gpu/": ModalSandbox(modal_sandbox),
    }
)
```

---

## Package Structure (Final)

```
vital-agentbox/              # Service + core library (this repo)
├── agentbox/
│   ├── api/                 # FastAPI service layer
│   │   ├── app.py           # Worker app (BoxManager + sandbox endpoints)
│   │   ├── orchestrator_app.py  # Orchestrator app (routing + worker mgmt)
│   │   ├── deps.py          # Dependency injection
│   │   ├── models.py        # Pydantic request/response schemas
│   │   └── routes/
│   │       ├── health.py    # GET /health, GET /metrics
│   │       ├── sandbox.py   # POST/GET/DELETE /sandboxes
│   │       ├── execute.py   # POST /sandboxes/{id}/execute
│   │       ├── files.py     # GET/POST/DELETE /sandboxes/{id}/files/*
│   │       └── workers.py   # GET/POST/DELETE /workers (orchestrator only)
│   ├── orchestrator/        # Orchestrator logic
│   │   ├── router.py        # Sandbox routing table (sandbox_id → worker_id)
│   │   ├── registry.py      # Worker registry + health polling
│   │   └── scaler.py        # Scale-up / drain / scale-down decisions
│   ├── box/                 # Sandbox implementation
│   │   ├── memfs/           # Emscripten MemFS interface
│   │   ├── shell/           # tree-sitter-bash shell executor
│   │   │   ├── buildin_exec/   # Modular builtin implementations (33 builtins, 15 files)
│   │   │   ├── host_commands/  # Tier 3: reportgen, boxcp, git push/pull
│   │   │   ├── builtins.py     # Registry — imports and maps all buildin_exec/ classes
│   │   │   └── virtual_bin.py  # Virtual /bin and /usr/bin directory
│   │   └── git/             # isomorphic-git integration
│   │       ├── builtin_git.py  # 20 Tier 1 git subcommands (JS constants + Python dispatch)
│   │       ├── fs_adapter.py   # window.fsAdapter + window.gitHelpers JS modules
│   │       ├── sync.py         # S3 push/pull sync
│   │       └── storage.py      # Pluggable storage backend
│   ├── manager/             # Browser pool and sandbox lifecycle
│   ├── ops/                 # Import/export: s3/, github/, gs/, gdrive/, drive/
│   ├── doc/                 # Document handling
│   └── pdf/                 # PDF generation
├── pyodide-bundle/          # Local Pyodide distribution
├── isomorphic-git-bundle/   # Bundled JS for browser page (~500KB)
├── Dockerfile.orchestrator  # Thin image: FastAPI + boto3, no Chromium (~200MB)
├── Dockerfile.worker        # Heavy image: Chromium + Pyodide (~1.5-2GB)
├── docker-compose.yml       # Local dev: orchestrator + 2 workers
├── Makefile
├── pyproject.toml
└── environment.yml

agentbox-client/             # Separate package — Python SDK (no Playwright dep)
├── agentbox_client/
│   ├── client.py
│   ├── sandbox.py
│   └── models.py
└── pyproject.toml

langchain-agentbox/          # Separate package — Deep Agents integration
├── langchain_agentbox/
│   └── sandbox.py           # BackendProtocol + SandboxBackendProtocol impl
└── pyproject.toml
```

---

## Milestone Summary

| Phase | Deliverable | Status |
|-------|-------------|--------|
| **1** | Core Service: Shell executor (33 builtins, virtual `/bin`), Pyodide v0.29.3, BoxManager, FastAPI worker, Tier 3 host commands (`reportgen`, `git push/pull/fetch`), storage backends (local + S3) | **✅ DONE** |
| **1b** | Git: 20 Tier 1 subcommands, `gitHelpers` JS layer, unified diff, `fsAdapter` | **✅ DONE** |
| **2** | Deep Agents integration: `AgentBoxSandbox(BaseSandbox)` with `execute`, `upload_files`, `download_files` | **✅ DONE** |
| **3a** | JWT auth (JWKS/Keycloak, RS256, HS256), orchestrator + Redis state, worker self-registration, admin API, Docker images | **✅ DONE** |
| **3b** | ECS deploy pipeline | Remaining |
| **3c** | Ops integration: `boxcp` host command (S3 + local providers, binary-safe, allowlist security). 24/24 tests. | **✅ DONE** |
| **4** | Multi-language, packages, hybrid mode, composite backends | Remaining |

