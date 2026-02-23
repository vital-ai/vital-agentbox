# Changelog

All notable changes to AgentBox are documented here.

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
