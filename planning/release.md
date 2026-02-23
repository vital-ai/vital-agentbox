# Release Plan

**Status**: Planning
**Date**: 2026-02-23
**Target**: Push to GitHub (public) + publish to PyPI as `vital-agentbox`

---

## 1. Pre-release audit

### 1.1 Secrets scan — CRITICAL

- `.env` contains **real OpenAI and Anthropic API keys**
  - Currently gitignored and never committed (verified: no git history)
  - **Action**: Rotate both keys after release as a precaution
  - **Action**: Add `.env` to `.dockerignore` if not already there
  - **Action**: Consider adding a pre-commit hook (e.g. `detect-secrets`)

- `docker-compose.yml` has `minioadmin/minioadmin` — OK, these are
  documented local-dev defaults, not real credentials

- `planning/operational-plan.md` has `task-12345` strings — OK, example
  placeholders, not real keys

- **Run before push**:
  ```bash
  # Scan for high-entropy strings that look like keys
  grep -rn "sk-" --include="*.py" --include="*.md" --include="*.yml" .
  grep -rn "AKIA" --include="*.py" --include="*.yml" .
  grep -rn "password" --include="*.py" | grep -v "test_\|#\|AGENTBOX_\|environ"
  ```

### 1.2 Dependencies cleanup — core `dependencies`

The current core `dependencies` list is too heavy for most users. Several
packages are internal or feature-specific:

| Dependency | Used by | Issue |
|------------|---------|-------|
| `vital-ai-vitalsigns>=0.1.27` | **Not imported anywhere in agentbox/** | Remove from core |
| `vital-ai-domain>=0.1.4` | **Not imported anywhere in agentbox/** | Remove from core |
| `kgraphservice>=0.0.6` | **Not imported anywhere in agentbox/** | Remove from core |
| `playwright` | Worker sandbox only | Move to `[worker]` or `[server]` |
| `black` | Code formatting in sandbox? | Audit usage, consider moving to `[server]` |
| `matplotlib`, `numpy` | Pyodide examples / reportgen | Move to `[worker]` or make optional |
| `pypandoc`, `panflute` | Report generation (Tier 3) | Move to `[worker]` or `[reportgen]` |
| `PyGithub` | GitHub integration | Move to optional extra |
| `python-magic` | File type detection | Move to `[worker]` |

**Target core deps** (what `pip install vital-agentbox` should install):
```toml
dependencies = []   # No core deps — everything via extras
```

Or a minimal set if we want `[server]` to work as a single-worker setup:
```toml
dependencies = [
    "tree-sitter>=0.22",
    "tree-sitter-bash>=0.21",
    "ast-grep-py>=0.41.0",
]
```

**Recommended extras restructure**:
```toml
[project.optional-dependencies]
# Lightweight client (no sandbox deps)
client = ["httpx>=0.25"]

# Worker: runs sandboxes (Chromium + Pyodide)
worker = [
    "playwright",
    "tree-sitter>=0.22",
    "tree-sitter-bash>=0.21",
    "ast-grep-py>=0.41.0",
    "python-magic>=0.4.27",
    "black",
    "fastapi>=0.104",
    "uvicorn[standard]>=0.24",
    "boto3>=1.28",
]

# Orchestrator (no Chromium)
orchestrator = [
    "fastapi>=0.104",
    "uvicorn[standard]>=0.24",
    "redis>=5.0",
    "boto3>=1.28",
    "PyJWT>=2.8",
    "httpx>=0.25",
]

# Report generation (PDF via pandoc/LaTeX)
reportgen = [
    "pypandoc>=1.5",
    "panflute>=2.3.1",
    "matplotlib",
    "numpy",
]

# LangChain / LangGraph integration
langchain = ["httpx>=0.25", "langchain-core>=0.2"]

# All sandbox deps (worker + reportgen + markdown)
server = [
    "vital-agentbox[worker]",
    "vital-agentbox[reportgen]",
    "markdown-it-py>=3.0",
    "mdit-py-plugins>=0.4",
]

# Development / testing
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "httpx>=0.25",
    "asgi-lifespan>=2.0",
]
```

### 1.3 Package metadata

- [ ] Bump version: decide on `0.1.0` (first public release) vs `0.0.4`
- [ ] Verify `license = {text = "Apache-2.0"}` — LICENSE file exists ✓
- [ ] Update README.md for PyPI landing page (it's the long_description)
- [ ] Add `py.typed` marker file for type checking consumers
- [ ] Verify `[tool.setuptools.packages.find]` excludes are correct:
  - Currently excludes: `test*`, `test_data*`, `planning*`
  - Should also exclude: `examples*`, `daytona*`, `docs*`, `scripts*`

### 1.4 Makefile cleanup

- Hardcoded conda path: `/opt/homebrew/anaconda3/envs/vital-agentbox/bin/python`
- **Action**: Change to `python` / `pip` (use virtualenv or system Python)
- Add `make release` target for build + upload

---

## 2. Gitignore / dockerignore review

### .gitignore additions needed

```
# Already present and correct:
.env               ✓
pyodide-bundle/    ✓
daytona            ✓  (third-party reference code)
logs/              ✓

# Consider adding:
*.pem
*.key
.env.*
```

### .dockerignore additions needed

```
# Already excludes test/, planning/, etc.
# Add:
.env
.env.*
docs/
examples/
daytona/
logs/
```

---

## 3. Git cleanup before push

### Current state

- **5 existing commits** on `main` (synced with `origin/main`)
- **Large amount of untracked files**: entire `agentbox/api/`, `agentbox/box/git/`,
  `agentbox/box/shell/`, `agentbox/client/`, `agentbox/deepagents/`,
  `agentbox/langchain/`, `agentbox/orchestrator/`, `docs/`, `planning/`,
  `scripts/`, `examples/`, 15+ test files, Docker files, etc.
- Some modified tracked files and a few deleted files (`setup.py`, old memfs files)

### Commit strategy

Option A — **Single commit** (simple):
```bash
git add -A
git commit -m "v0.1.0: Full sandbox platform with docs, orchestrator, integrations"
```

Option B — **Logical commits** (cleaner history):
```
1. "refactor: Migrate to pyproject.toml, remove setup.py"
2. "feat: Shell executor with tree-sitter-bash and 30+ builtins"
3. "feat: GitBox with isomorphic-git, merge, push/pull"
4. "feat: FastAPI worker + orchestrator APIs"
5. "feat: Client SDK with sync/async wrappers"
6. "feat: LangChain toolkit and Deep Agents backend"
7. "feat: Docker images and docker-compose"
8. "docs: Full documentation (20 files)"
9. "chore: Release prep — deps cleanup, version bump"
```

**Recommendation**: Option A is fine for a first public release from a
private repo. The existing 5 commits are just "sync" messages anyway.

---

## 4. Pre-push verification

```bash
# 1. Verify no secrets in staged files
git diff --cached --name-only | xargs grep -l "sk-\|AKIA\|password=" 2>/dev/null

# 2. Build the package
python -m build

# 3. Check the dist contents
tar tzf dist/vital_agentbox-*.tar.gz | head -50

# 4. Verify package installs clean (in a fresh venv)
python -m venv /tmp/test-install
/tmp/test-install/bin/pip install dist/vital_agentbox-*.whl
/tmp/test-install/bin/python -c "from agentbox.client import AgentBoxClient; print('OK')"

# 5. Run tests
make test-all

# 6. Check what will be pushed
git log origin/main..HEAD --oneline
```

---

## 5. PyPI release

### First-time setup

```bash
pip install build twine

# Create ~/.pypirc or use token auth
# Get API token from https://pypi.org/manage/account/token/
```

### Release steps

```bash
# 1. Clean old builds
rm -rf dist/ build/ *.egg-info

# 2. Build sdist + wheel
python -m build

# 3. Check distribution
twine check dist/*

# 4. Upload to TestPyPI first
twine upload --repository testpypi dist/*

# 5. Test install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ vital-agentbox[client]

# 6. Upload to real PyPI
twine upload dist/*

# 7. Verify
pip install vital-agentbox[client]==0.1.0
```

### Makefile target (add)

```makefile
release: clean  ## Build and upload to PyPI
	python -m build
	twine check dist/*
	twine upload dist/*

release-test: clean  ## Build and upload to TestPyPI
	python -m build
	twine check dist/*
	twine upload --repository testpypi dist/*
```

---

## 6. GitHub release

After PyPI upload:

1. Create a GitHub release tag:
   ```bash
   git tag -a v0.1.0 -m "v0.1.0: First public release"
   git push origin v0.1.0
   ```
2. Create GitHub Release from the tag with changelog notes
3. Link to PyPI package in release description

---

## 7. Post-release

- [ ] Rotate OpenAI and Anthropic API keys (precaution)
- [ ] Verify `pip install vital-agentbox[client]` works from PyPI
- [ ] Verify `pip install vital-agentbox[worker]` works from PyPI
- [ ] Update `docs/changelog.md` with release date
- [ ] Announce release

---

## 8. Task checklist

### Phase 1: Cleanup
- [ ] Remove `vital-ai-vitalsigns`, `vital-ai-domain`, `kgraphservice` from core deps
- [ ] Restructure extras (`[worker]`, `[server]`, `[orchestrator]`, `[reportgen]`)
- [ ] Clean up Makefile (remove hardcoded conda paths)
- [ ] Add `py.typed` marker
- [ ] Update `[tool.setuptools.packages.find]` excludes
- [ ] Update `.dockerignore` (add `.env`, `docs/`, `examples/`, `daytona/`)
- [ ] Review and update README.md for PyPI

### Phase 2: Verify
- [ ] Run full test suite (`make test-all`)
- [ ] Scan for secrets (`grep` for keys, tokens, passwords)
- [ ] Build package and inspect contents
- [ ] Test install in fresh venv (all extras)

### Phase 3: Push
- [ ] Commit all changes
- [ ] Push to GitHub
- [ ] Verify GitHub renders docs correctly

### Phase 4: Release
- [ ] Decide version: `0.1.0` or `0.0.4`
- [ ] Upload to TestPyPI, verify install
- [ ] Upload to PyPI
- [ ] Create GitHub release tag
- [ ] Post-release verification
