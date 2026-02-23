# Documentation Plan

**Status**: P0–P3 complete · Future: AWS deployment docs
**Date**: 2026-02-23
**Target**: `/docs/` directory (20 Markdown files + 2 OpenAPI JSON + auto-gen script)

---

## 1. Documentation Structure (current)

```
docs/
├── index.md                          # Overview, quickstart, architecture, nav
├── changelog.md                      # Version history (0.0.1–0.0.3)
├── getting-started/
│   ├── install.md                    # All pip extras, system reqs, conda, Docker
│   ├── quickstart.md                 # End-to-end walkthrough
│   └── deployment.md                 # Mode 1/2/3, Docker Compose, AWS ECS, security
├── sandbox/
│   ├── overview.md                   # MemBox vs GitBox vs FileSystemBox, security
│   ├── shell.md                      # Shell execution, tier system, bash features
│   ├── builtins.md                   # 30+ builtins with examples
│   ├── git.md                        # Git ops, merge conflicts, push/pull, storage
│   ├── python.md                     # Pyodide execution, micropip, limitations
│   └── files.md                      # MemFS, file transfer, binary handling
├── api/
│   ├── client-sdk.md                 # Full SDK reference
│   ├── worker-api.md                 # Auto-generated (21 endpoints)
│   ├── orchestrator-api.md           # Auto-generated (21 endpoints)
│   └── openapi/                      # Raw JSON schemas
│       ├── worker.json
│       └── orchestrator.json
├── integrations/
│   ├── deepagents.md                 # BaseSandbox backend
│   └── langchain.md                  # Toolkit, tools, AgentBoxBackend
├── operations/
│   ├── docker.md                     # Images, layers, compose, deployment modes
│   ├── scaling.md                    # Orchestrator + workers, Redis, dual scaling
│   └── storage.md                    # S3/MinIO/local, auto-restore, tenant scoping
└── reference/
    └── config.md                     # All AGENTBOX_* env vars with defaults
```

---

## 2. Completion Status

### P0 — Essential ✅

1. ~~`index.md`~~ — Overview, quickstart, architecture, nav
2. ~~`getting-started/install.md`~~ — All pip extras, system reqs, conda, Docker
3. ~~`getting-started/quickstart.md`~~ — End-to-end walkthrough
4. ~~`sandbox/overview.md`~~ — MemBox vs GitBox, security model
5. ~~`api/client-sdk.md`~~ — Full SDK reference
6. ~~`api/worker-api.md` + `orchestrator-api.md`~~ — Auto-generated from OpenAPI
7. ~~`changelog.md`~~ — Version history

### P1 — Important ✅

8. ~~`sandbox/shell.md`~~ — Shell execution model, tier system
9. ~~`sandbox/builtins.md`~~ — 30+ builtins with examples
10. ~~`sandbox/git.md`~~ — Git operations, merge conflicts, push/pull
11. ~~`integrations/deepagents.md`~~ — Deep Agents sandbox backend
12. ~~`integrations/langchain.md`~~ — Toolkit, tools, AgentBoxBackend

### P2 — Operations ✅

13. ~~`operations/docker.md`~~ — Images, layers, compose, deployment modes
14. ~~`operations/scaling.md`~~ — Orchestrator + workers, Redis, JWT
15. ~~`operations/storage.md`~~ — S3/MinIO/local, auto-restore, tenant scoping

### P3 — Deep dives ✅

16. ~~`reference/config.md`~~ — All AGENTBOX_* env vars with defaults
17. ~~`sandbox/python.md`~~ — Pyodide execution, micropip, limitations
18. ~~`sandbox/files.md`~~ — MemFS, file transfer, binary handling
19. ~~`getting-started/deployment.md`~~ — Mode 1/2/3, Docker Compose, AWS ECS

### Future — AWS deployment docs (planned)

20. **`aws/overview.md`** — AWS architecture overview (ECS, ALB, MemoryDB, S3)
21. **`aws/ecs.md`** — ECS task definitions, service config, Fargate vs EC2
22. **`aws/networking.md`** — VPC, subnets, security groups, ALB setup
23. **`aws/memorydb.md`** — MemoryDB cluster setup, ACL auth, TLS config
24. **`aws/s3.md`** — Bucket setup, IAM policies, encryption, lifecycle rules
25. **`aws/iam.md`** — IAM roles, task execution roles, least-privilege policies
26. **`aws/monitoring.md`** — CloudWatch metrics, alarms, log groups
27. **`aws/cdk-terraform.md`** — IaC examples (CDK or Terraform)

---

## 3. Content Sources

| Doc | Primary source |
|-----|---------------|
| Architecture | `planning/operational-plan.md`, README.md |
| Shell/builtins | `agentbox/box/shell/builtins.py`, builtin_exec/*.py |
| Git | `agentbox/box/git/builtin_git.py`, test/test_gitbox.py |
| Client SDK | `agentbox/client/`, test/test_client.py |
| REST API | `agentbox/api/routes/`, `agentbox/orchestrator/routes/` |
| Deep Agents | `agentbox/deepagents/sandbox.py` |
| LangChain | `agentbox/langchain/`, test/test_langchain.py |
| Docker/ops | Dockerfiles, docker-compose.yml, env vars |
| Patch/edit | `agentbox/box/patch/`, test/test_patch.py |
| Storage | `agentbox/ops/`, host_commands/ |

---

## 4. Format & Tooling

- **Format**: Plain Markdown (`.md`) — exactly what GitHub renders natively
- **Hosting**: GitHub main repo `/docs/` directory. No Pages, no MkDocs, no Sphinx.
  GitHub renders Markdown from any directory with full relative link support.
- **Code examples**: Tested snippets from actual test files where possible
- **Versioning**: Docs track latest. Changelog notes per version in `docs/changelog.md`.
- **API reference**: Auto-generated from FastAPI OpenAPI JSON (see below)

### API doc auto-generation

Both FastAPI apps expose OpenAPI schemas at import time:

- **Worker API**: 21 endpoints (`/health`, `/sandboxes`, `/sandboxes/{id}/execute`, etc.)
- **Orchestrator API**: 21 endpoints (`/internal/workers/*`, `/sandboxes/*`, etc.)

**Approach**: A `scripts/generate_api_docs.py` script that:
1. Imports the FastAPI apps
2. Calls `app.openapi()` to get the schema dict
3. Converts to Markdown (endpoint tables, request/response schemas)
4. Writes `docs/api/worker-api.md` and `docs/api/orchestrator-api.md`

This is ~100 lines of Python — simpler and more controllable than external
tools like `openapi-to-md` or `openapi-generator`. We control the Markdown
format exactly and can include our own annotations.

Alternatively, `openapi-to-md` (PyPI) is a CLI that converts OpenAPI JSON/YAML
to a single Markdown file:
```bash
pip install openapi-to-markdown
api2md --input_file openapi.json --output_file docs/api/worker-api.md
```

**Decision**: Write our own script for full control over output format.
Run it as `make docs` or `python scripts/generate_api_docs.py`.

### Makefile target

```makefile
docs:  ## Regenerate API reference docs from OpenAPI schemas
	$(PYTHON) scripts/generate_api_docs.py
```
