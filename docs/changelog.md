# Changelog

All notable changes to AgentBox are documented here.

## 0.1.3 (2026-06-20)

### Added

- **AgentCore engine** — AWS Bedrock Code Interpreter execution engine with real
  Python, real bash, and real filesystem (MicroVM). Full lifecycle, file I/O,
  host-intercepted commands (`edit`, `apply_patch`, `git push/pull`).
- **Browser sessions** — SessionPool, WebSocket-based real-time browser control,
  browser bridge for worker-to-orchestrator communication.
- **S3 data access modes** — three modes (`tenant`, `path`, `path_credentials`)
  for flexible S3 scoping. Credential refresh via webhook + PATCH endpoint.
- **Credential expiry checker** — background task monitors Mode 3 sandboxes,
  fires HMAC-signed webhooks before expiry, graceful shutdown on timeout.
- **Worker heartbeat health** — consecutive heartbeat failures trigger 503 on
  `/health`, allowing ECS to replace unhealthy tasks.
- **JWT middleware fix** — returns proper 401 JSON instead of 500 (Starlette
  `HTTPException` in middleware issue).
- **ECS task definitions** — `deploy/` directory with orchestrator and worker
  Fargate task definitions and deployment README.
- **Deep Agents 0.6.10** — `AgentBoxSandbox(BaseSandbox)` replaces deprecated
  `AgentBoxBackend`. 60/60 tests passing.
- **Browser bridge `/internal` prefix** — worker-to-orchestrator calls bypass JWT.

## 0.1.2 (2026-05-15)

### Fixed

- **Redis ssl=None bug** — don't pass `ssl` kwarg to `from_url()` when TLS is
  not used (redis-py 7.x rejects it).
- **Pyodide loading in Docker** — serve `sandbox.html` from Pyodide bundle to
  establish a proper `http://` origin for script loading.
- **Worker Dockerfile** — added `libxfixes3` for Playwright/Chromium.
- **Proxy error handling** — worker 500 responses may not be JSON; wrapped in
  try/except.

### Added

- **Docker Compose integration** — full stack (orchestrator + 2 workers + Redis +
  MinIO) verified with 35/35 E2E tests passing.

## 0.1.1 (2026-04-10)

### Added

- **Orchestrator Redis state** — shared state backend for multi-instance
  orchestrator (workers, sandboxes, routing).
- **Worker self-registration** — heartbeat loop with auto-re-registration on
  orchestrator restart or Redis key expiry.
- **JWT authentication** — JWKS/Keycloak support with configurable claims,
  roles, tenant extraction, and admin role.
- **Orchestrator proxy** — routes sandbox CRUD and execution to workers via
  capacity-based selection.

## 0.1.0 (2026-02-23)

### Changed

- **First public release** — pushed to GitHub and PyPI.
- **Dependencies restructured** — removed unused internal deps
  (`vital-ai-vitalsigns`, `vital-ai-domain`, `kgraphservice`). Core package
  now only requires `tree-sitter`, `tree-sitter-bash`, `ast-grep-py`.
  Heavy deps (`playwright`, `python-magic`, etc.) moved to `[worker]` extra.
- **`[server]` extra** now wraps `[worker]` for convenience.
- **Makefile** — removed hardcoded conda paths, added `make release` and
  `make docs` targets.
- **README** — rewritten for PyPI landing page with quick start, install
  extras, LangChain example, and docs links.
- **Package excludes** — `examples/`, `daytona/`, `docs/`, `scripts/` no
  longer included in sdist/wheel.

### Added

- **Full documentation** — 20 Markdown files in `docs/`: getting started,
  sandbox reference, API reference, integrations, operations, config.
- **`py.typed` marker** — enables type checking for consumers.

## 0.0.3 (2026-02-23)

### Added

- **V4A patch support** — `apply_patch` shell builtin reads OpenAI V4A patch
  format from stdin and applies add/update/delete operations to MemFS files.
  Parser adapted from OpenAI Agents SDK with 3-tier fuzzy matching.
- **AST-aware matching fallback** — When text-based `str_replace` fails in
  the `edit` builtin, an optional AST-aware tier uses `ast-grep-py` to find
  structurally similar code. Supports Python, JS, TS, Rust, Go, Java, C/C++.
- **Git merge conflict resolution** — `git merge` now writes conflict markers
  to working tree instead of aborting. Added `git merge --continue` and
  `git merge --abort` support.
- **BaseSandbox shell overrides** — Deep Agents `AgentBoxSandbox` now uses
  Tier 1 shell builtins (`edit --view`, `edit --old --new`, heredoc `cat`)
  instead of `python3 -c` commands.
- **CSTWalker backslash escape fix** — Shell parser correctly handles bash
  single-quote escape pattern (`'\''`).
- **Auto-generated API docs** — `scripts/generate_api_docs.py` generates
  Markdown API reference from FastAPI OpenAPI schemas.

## 0.0.2 (2026-02-15)

### Added

- **Patch module** — `edit` shell builtin with `str_replace`, `insert`,
  `view`, `create`, `info`, `diff` subcommands. 5-tier matching: exact,
  line-stripped, indent-offset, fuzzy, AST-aware.
- **Outline module** — `edit --info` uses `ast-grep-py` for AST-based
  symbol extraction across 20+ languages. Markdown support via `markdown-it-py`.
- **Client SDK** — `AgentBoxClient` with async/sync support, `Sandbox` handle,
  file operations, one-shot `run()`.
- **LangChain integration** — `AgentBoxToolkit` (4 tools), `AgentBoxBackend`
  (Deep Agents `BackendProtocol`).
- **Deep Agents sandbox** — `AgentBoxSandbox` implementing `BaseSandbox`.
- **Docker Compose stack** — Orchestrator + 2 workers + Redis + MinIO.
- **Binary file download** — Extension-based detection for correct binary
  transfer via base64.

## 0.0.1 (2026-01-20)

### Added

- Initial release.
- MemBox and GitBox sandbox types.
- Chromium + Pyodide dual-layer isolation.
- tree-sitter-bash shell parser with 30+ virtual builtins.
- isomorphic-git integration (GitBox).
- S3/MinIO storage backend for git push/pull.
- FastAPI worker and orchestrator services.
