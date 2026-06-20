# AgentBox Security Model

## Overview

AgentBox executes **caller-supplied code** in sandboxed environments. The security
model must protect:

1. The orchestrator and workers from malicious sandbox code
2. Cross-tenant data isolation
3. Service-to-service communication integrity
4. Credentials and secrets from leaking into execution contexts

---

## Trust Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│  External Callers (JWT-authenticated)                           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Bearer token (RS256 via JWKS / Keycloak)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Orchestrator                                                   │
│  - Validates caller JWT (JWKS/RS256)                            │
│  - Validates service JWT (HS256 via AGENTBOX_SERVICE_SECRET)    │
│  - Routes requests, manages state (Redis)                       │
│  - Never executes user code                                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Service JWT (HS256, 60s TTL, minted per-call)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Worker Process                                                 │
│  - Validates service JWT from orchestrator                      │
│  - Manages sandbox lifecycle (BoxManager)                       │
│  - Holds AGENTBOX_SERVICE_SECRET (process-level only)           │
│  - Mints sandbox-scoped tokens for AgentCore MicroVMs           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Sandbox isolation boundary
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Sandbox (caller-supplied code runs here)                       │
│                                                                 │
│  Pyodide (WASM):                                                │
│    - Chromium renderer process sandbox                          │
│    - No network access (all I/O via sendMessage bridge)         │
│    - No filesystem access to host                               │
│                                                                 │
│  AgentCore (MicroVM):                                           │
│    - AWS Bedrock-managed Firecracker MicroVM                    │
│    - Isolated kernel, filesystem, network namespace             │
│    - Has: AGENTBOX_AUTH_TOKEN (sandbox-scoped, auto-refreshed)  │
│    - Has: AGENTBOX_ORCHESTRATOR_URL                             │
│    - Does NOT have: AGENTBOX_SERVICE_SECRET, AWS creds, Redis   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Authentication Layers

### 1. External Caller → Orchestrator

| Property | Value |
|----------|-------|
| Mechanism | JWT Bearer token |
| Algorithms | RS256 (JWKS), ES256, or HS256 |
| Key source | `AGENTBOX_JWT_JWKS_URI` (Keycloak), `AGENTBOX_JWT_PUBLIC_KEY`, or `AGENTBOX_JWT_SECRET` |
| Validation | Signature, expiry, issuer, audience |
| Tenant isolation | `sub` claim → tenant scoping in S3 paths |
| Exempt paths | `/health`, `/internal/health`, `/docs`, `/openapi.json`, `/redoc` |

### 2. Worker ↔ Orchestrator (Service-to-Service)

| Property | Value |
|----------|-------|
| Mechanism | Self-minted HS256 JWT |
| Secret | `AGENTBOX_SERVICE_SECRET` (shared, stored in Secrets Manager) |
| TTL | 60 seconds (minted fresh per outbound call) |
| Payload | `{"type": "service", "sub": "<worker-id|orchestrator>", "exp": ...}` |
| Validation | Middleware tries HS256 service decode first, falls back to user JWT |
| Direction | Bidirectional — workers mint for registration/heartbeat, orchestrator mints for proxy calls |

### 3. Sandbox → Orchestrator (AgentCore browser client)

| Property | Value |
|----------|-------|
| Mechanism | Sandbox-scoped service JWT |
| Minted by | Worker process at sandbox creation |
| Subject | `sandbox:<session_id>` |
| TTL | `AGENTBOX_AGENTCORE_SESSION_TIMEOUT` (default 1800s) |
| Refresh | Background task at 50% TTL re-mints and re-injects into MicroVM |
| Scope | Can only call `/browsers` endpoints (same JWT validation) |

### 4. Sandbox → Orchestrator (Pyodide browser client)

| Property | Value |
|----------|-------|
| Mechanism | sendMessage bridge → worker process → fresh service JWT |
| Secret exposure | None — Pyodide sandbox never sees any token |
| Worker mints | Fresh 60s service JWT for each proxied browser request |

---

## Secret Isolation Matrix

| Secret | Orchestrator | Worker Process | Pyodide Sandbox | AgentCore MicroVM |
|--------|:---:|:---:|:---:|:---:|
| `AGENTBOX_SERVICE_SECRET` | ✅ | ✅ | ❌ | ❌ |
| `AGENTBOX_JWT_JWKS_URI` / keys | ✅ | ✅ | ❌ | ❌ |
| `AGENTBOX_REDIS_URL` / password | ✅ | ❌ | ❌ | ❌ |
| AWS IAM task role credentials | ✅ | ✅ | ❌ | ❌ |
| `AGENTBOX_AUTH_TOKEN` (sandbox-scoped) | — | — | ❌ | ✅ (derived, short-lived) |
| Caller's JWT | ✅ (validated) | — | ❌ | ❌ |
| S3 credentials (Mode 3) | ✅ (proxied) | ✅ (in sandbox env) | ✅ (injected) | ✅ (injected) |

---

## Sandbox Isolation

### Pyodide (WASM) — Defense in Depth

1. **Chromium renderer sandbox** — seccomp-bpf, namespaces, no direct syscalls
2. **WASM memory isolation** — Pyodide runs in WebAssembly linear memory
3. **No network access** — all I/O is mediated by the `sendMessage` bridge
4. **No host filesystem** — MemFS is in-browser only
5. **No environment variables** — worker process env is not exposed
6. **Message bridge filtering** — only whitelisted message types are handled

### AgentCore (MicroVM) — AWS-Managed Isolation

1. **Firecracker MicroVM** — hardware-virtualized, separate kernel
2. **Network isolation** — VPC-scoped, no access to worker's network
3. **Filesystem isolation** — ephemeral, destroyed on session end
4. **Credential scoping** — only a derived sandbox-scoped JWT is injected
5. **Session timeout** — hard idle timeout destroys the VM
6. **No access to**: service secret, Redis, worker IAM role, other sandboxes

---

## Threat Model

### Threats and Mitigations

| Threat | Impact | Mitigation |
|--------|--------|------------|
| Malicious code escapes sandbox | Full system compromise | Chromium sandbox (Pyodide) / Firecracker (AgentCore) |
| Sandbox code steals service secret | Can impersonate any service | Secret never enters sandbox; only derived tokens |
| Sandbox code steals other tenant's data | Data breach | Tenant scoping via JWT `sub` claim; S3 path prefixing |
| Sandbox token used after session ends | Unauthorized access | Token TTL = session timeout; session end = token invalid |
| Replay of expired service JWT | Unauthorized calls | 60s TTL; `exp` claim enforced |
| Worker impersonation | Rogue worker joins pool | Service secret required for registration |
| Man-in-the-middle (worker ↔ orchestrator) | Data interception | VPC-internal only; TLS for Redis; service JWT integrity |
| Credential webhook spoofing | False credential refresh | HMAC-SHA256 signature (`X-AgentBox-Signature`) |
| AgentCore MicroVM calls other sandboxes | Cross-sandbox interference | Token subject is `sandbox:<id>`; no cross-sandbox API exposed |

### Accepted Risks

| Risk | Rationale |
|------|-----------|
| Sandbox-scoped token grants access to `/browsers` (any session) | Browser sessions are ephemeral; future: scope token to specific session |
| `AGENTBOX_SERVICE_SECRET` is symmetric (HS256) | Simpler than PKI for internal service auth; rotated via Secrets Manager |
| Worker and orchestrator share same secret | Required for bidirectional minting; could be split into two secrets |

---

## Data Access Modes and Credential Flow

### Mode 1: Tenant (default)
- S3 path = `{sub}/{repo_id}` — enforced server-side
- Worker uses IAM task role for S3 access
- Caller cannot specify paths

### Mode 2: Path
- Caller provides `data_path`
- JWT is authentication only (no S3 scoping)
- Worker uses IAM task role for S3 access

### Mode 3: Path + Credentials
- Caller provides `data_path` + `s3_credentials` (STS)
- Worker injects caller's STS creds into sandbox
- Background expiry checker fires webhook before expiry
- Caller PATCHes fresh creds → proxied to worker
- Grace period → graceful shutdown if no refresh
- **Risk**: Caller's S3 credentials are inside the sandbox (by design — caller trusts their own code)

---

## Network Architecture (Production)

```
Internet
    │
    ▼ (ALB, TLS termination)
┌────────────────┐
│  Orchestrator  │◄──── Keycloak JWKS endpoint (external)
│  (Fargate)     │
└───────┬────────┘
        │ Private subnet (VPC)
        ▼
┌────────────────┐     ┌────────────────┐
│   Worker 1     │     │   Worker 2     │
│   (Fargate)    │     │   (Fargate)    │
└───────┬────────┘     └────────────────┘
        │
        ▼ AWS API (SigV4, HTTPS)
┌────────────────┐
│  AgentCore     │
│  (Bedrock)     │
└────────────────┘
```

- Workers are **not** publicly accessible — only orchestrator is exposed
- Worker ↔ Orchestrator: private VPC + service JWT
- Worker → AgentCore: AWS IAM SigV4 (task role)
- Redis (MemoryDB): VPC-internal, TLS, password-authenticated

---

## Key Environment Variables

| Variable | Where | Purpose |
|----------|-------|---------|
| `AGENTBOX_JWT_ENABLED` | Orchestrator, Worker | Enable JWT enforcement |
| `AGENTBOX_JWT_JWKS_URI` | Orchestrator, Worker | Keycloak/OIDC key endpoint |
| `AGENTBOX_SERVICE_SECRET` | Orchestrator, Worker | HS256 service JWT signing |
| `AGENTBOX_AUTH_TOKEN` | AgentCore MicroVM (injected) | Sandbox-scoped JWT for browser calls |
| `AGENTBOX_ORCHESTRATOR_URL` | Worker, AgentCore MicroVM | Orchestrator endpoint |
| `AGENTBOX_AGENTCORE_SESSION_TIMEOUT` | Worker | Session/token TTL (default 1800s) |

---

## Rotation and Revocation

### Secret Rotation
- `AGENTBOX_SERVICE_SECRET`: Rotate in Secrets Manager → redeploy tasks
- JWKS keys: Handled by Keycloak (automatic key rotation)
- Worker IAM credentials: Auto-rotated by ECS task role metadata service

### Token Revocation
- Service JWTs: 60s TTL — effectively self-revoking
- Sandbox tokens: Killed when sandbox stops (task cancelled)
- Caller JWTs: Managed by identity provider (Keycloak)

### Incident Response
- Compromised service secret: Rotate in Secrets Manager, redeploy all tasks
- Compromised sandbox: Session destroyed on stop; MicroVM is ephemeral
- Rogue worker: Rotate service secret; deregister via admin API

---

## Future Improvements

1. **Scoped sandbox tokens** — restrict to specific browser session ID, not all `/browsers` endpoints
2. **Split service secrets** — separate worker→orchestrator and orchestrator→worker secrets
3. **Audit logging** — log all service JWT mints with subject and TTL
4. **Rate limiting** — per-tenant request limits at orchestrator level
5. **mTLS** — for worker↔orchestrator as additional layer (defense in depth)
6. **Sandbox network policies** — restrict AgentCore MicroVM egress to orchestrator only
7. **Token binding** — bind sandbox token to source IP of the MicroVM
