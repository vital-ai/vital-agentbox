# Documentation Update Plan

Incremental updates to bring `docs/` in sync with the current implementation.
Each item is a self-contained PR-sized change.

---

## Phase 1: New pages (features with no docs coverage)

### 1.1 AgentCore engine (`docs/sandbox/agentcore.md`)

- New page documenting the AgentCore (AWS Bedrock Code Interpreter) engine
- Real Python, real bash, real filesystem (MicroVM — not WASM)
- How to use: `engine="agentcore"` in `create_sandbox`
- Comparison table: PyodideEngine vs AgentCoreEngine (WASM vs MicroVM, capabilities)
- Host-intercepted commands: `edit`, `apply_patch`, `git push/pull`
- Requires `[agentcore]` extra and AWS credentials
- Add link in `docs/index.md` under Sandbox section

### 1.2 Browser sessions (`docs/sandbox/browser.md`)

- New page documenting browser session support (Playwright sessions via orchestrator)
- SessionPool, session lifecycle (create → command → close)
- WebSocket protocol for real-time browser control
- Browser bridge (worker-to-orchestrator communication)
- Worker mode: `WORKER_MODE=browser|code|both`
- Add link in `docs/index.md`

### 1.3 S3 data access modes (`docs/operations/data-access.md`)

- New page documenting the three access modes:
  - Mode 1 (tenant): default, S3 path = `{sub}/{repo_id}`, worker IAM
  - Mode 2 (path): caller provides `data_path`, worker IAM
  - Mode 3 (path_credentials): caller provides `data_path` + STS creds
- `AGENTBOX_DATA_ACCESS_MODE` env var
- Credential refresh flow (webhook, PATCH endpoint, graceful shutdown)
- Add link in `docs/index.md` under Operations

### 1.4 AWS ECS deployment (`docs/getting-started/aws-deployment.md`)

- New page for ECS Fargate deployment (content from `deploy/README.md`)
- Prerequisites (ECR, MemoryDB, S3, Secrets Manager, IAM, CloudWatch, VPC)
- Task definitions overview
- Build/push/register/update workflow
- Worker auto-registration and shared memory for Chromium
- Link from `docs/getting-started/deployment.md`

---

## Phase 2: Update existing pages

### 2.1 `docs/index.md`

- Add AgentCoreBox to the "Box types" table
- Update architecture diagram to show AgentCore path
- Add Browser sessions to feature list
- Add links to new pages in the Documentation section

### 2.2 `docs/sandbox/overview.md`

- Add AgentCoreBox section (alongside MemBox, GitBox, FileSystemBox)
- Mention `engine` parameter in create_sandbox
- Note that AgentCore supports real pip install, real bash, real git

### 2.3 `docs/reference/config.md`

- Add `AGENTBOX_DATA_ACCESS_MODE` (tenant/path/path_credentials)
- Add `AGENTBOX_HEARTBEAT_UNHEALTHY_THRESHOLD` (default 5)
- Add `AGENTBOX_AGENTCORE_REGION` (default us-east-1)
- Add `AGENTBOX_AGENTCORE_SESSION_TIMEOUT` (default 1800)
- Add `AGENTBOX_AGENTCORE_INTERPRETER_ID` (optional)
- Add `WORKER_MODE` (code/browser/both)
- Add `AGENTBOX_CREDENTIAL_CHECK_INTERVAL`, `AGENTBOX_CREDENTIAL_LEAD_TIME`,
  `AGENTBOX_CREDENTIAL_GRACE_PERIOD`
- Add credential webhook config vars

### 2.4 `docs/api/orchestrator-api.md`

- Add `PATCH /sandboxes/{id}/credentials` endpoint
- Add browser session endpoints (`POST /browsers`, `DELETE /browsers/{id}`,
  `WebSocket /browsers/{id}/ws`)
- Add `/internal/*` prefix note (no auth)
- Document `data_path` and `s3_credentials` fields in create sandbox

### 2.5 `docs/api/worker-api.md`

- Add `PATCH /internal/sandboxes/{id}/credentials` endpoint
- Note engine parameter in create sandbox
- Document internal health endpoint behavior (503 on orchestrator unreachable)

### 2.6 `docs/getting-started/deployment.md`

- Add Mode 3 (orchestrator + workers on ECS Fargate) section
- Reference the new AWS deployment page
- Update Mode 2 to mention JWT auth is available

### 2.7 `docs/operations/scaling.md`

- Document worker health / heartbeat unhealthy threshold
- Worker auto-re-registration on orchestrator restart
- ECS task replacement on unhealthy

### 2.8 `docs/operations/storage.md`

- Document Mode 2/3 data access (caller-provided paths)
- Credential refresh lifecycle
- engine_sync.py (AgentCore ↔ S3 via base64 shell bridge)

### 2.9 `docs/integrations/deepagents.md`

- Update for Deep Agents 0.6.10 upgrade
- Document `AgentBoxSandbox(BaseSandbox)` replacing `AgentBoxBackend`
- Note deprecation warning on old backend

---

## Phase 3: Changelog and version

### 3.1 `docs/changelog.md`

Add entries for 0.1.1, 0.1.2, 0.1.3:

**0.1.3** (2026-06-20):
- AgentCore engine fully implemented (AWS Bedrock Code Interpreter)
- Browser session support (SessionPool, WebSocket, bridge)
- S3 data access modes (tenant/path/path_credentials)
- Credential refresh with webhook + graceful shutdown
- Worker heartbeat with health-based ECS replacement
- JWT middleware fix (HTTPException → JSONResponse in middleware)
- ECS task definitions + deployment docs
- Deep Agents 0.6.10 upgrade (AgentBoxSandbox)
- Browser bridge uses /internal prefix (bypasses JWT)

**0.1.2**:
- Docker-compose integration tests (35/35 E2E passing)
- Redis ssl=None fix for redis-py 7.x
- Pyodide loading fix in Docker (origin-based script loading)
- Proxy error handling improvements

**0.1.1**:
- Orchestrator Redis state backend
- Worker self-registration and heartbeat
- JWT auth with JWKS/Keycloak support

---

## Execution order

1. Start with **2.3** (config.md) — quick win, high reference value
2. Then **3.1** (changelog) — records what shipped
3. Then **1.1** (agentcore.md) — major new feature
4. Then **1.3** (data-access.md) — complex feature needing docs
5. Then **2.1** + **2.2** (index + overview) — update top-level navigation
6. Then **1.4** (aws-deployment.md) — ops guide
7. Then **2.4** + **2.5** (API docs) — detailed reference
8. Remaining items in any order

---

## Notes

- Keep pages concise. Prefer tables and code blocks over prose.
- All new pages need a link added to `docs/index.md`.
- Maintain existing style: H1 title, description paragraph, then sections.
- Code examples should be copy-pasteable.
- Config tables follow: Variable | Default | Description format.
