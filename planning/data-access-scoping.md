# Data Access Scoping — S3 Path Authorization via JWT

## Problem Statement

The current implementation scopes S3 paths using `claims.sub` (user ID) from the
inbound JWT. This assumes data ownership maps 1:1 to a user login:

```
s3://{bucket}/{user_sub}/{repo_id}/...
```

However, many real use cases have data associated with **shared contexts** (e.g. a
Slack channel, a team workspace, a case) rather than individual users. Multiple users
in the same organization need access to the same S3 paths:

```
s3://{bucket}/{org_id}/{channel_id}/...
s3://{bucket}/{org_id}/cases/{case_id}/...
```

The scoping key should be the **account/org**, not the individual user.

---

## JWT and Org Identifiers — What's Standard?

Standard JWT (RFC 7519) defines only a handful of registered claims:
- `sub` — subject (typically user ID)
- `iss` — issuer
- `aud` — audience
- `exp`, `iat`, `nbf` — timing

**There is no standard claim for org/account/tenant.** This is always a custom claim
added by the identity provider. Common patterns in the wild:

| Provider | Org Claim | Format |
|----------|-----------|--------|
| Auth0 | `org_id` | Custom claim in token |
| Keycloak | `organization` or group attributes | Realm/group mapper |
| Okta | `org` or custom | Token inline hook |
| Azure AD | `tid` (tenant ID) | Standard in Microsoft tokens |
| Google Workspace | `hd` (hosted domain) | Domain-level only |
| AWS Cognito | Custom attribute (`custom:org_id`) | User pool attribute |
| Slack (OIDC) | `https://slack.com/team_id` | Namespaced custom claim |

**Takeaway:** You must configure the IdP to include org/account info in the token.
It will not be there by default (except Azure AD's `tid`).

---

## Current Implementation

```python
# agentbox/orchestrator/routes/sandboxes.py
tenant = claims.sub if claims and claims.sub else None
if tenant:
    scoped_repo_id = f"{safe_tenant}/{safe_repo}"
```

- Uses `sub` as the scoping key
- Single-level: no org → channel hierarchy
- Worker trusts whatever `repo_id` the orchestrator sends (no independent validation)

---

## Access Modes

Three modes of S3 data access, configured at the **service level** (env var /
config). The deployment chooses one mode and all requests follow that mode's
rules. All modes require a valid JWT for authentication. The mode determines
**how the S3 path is resolved** and **what credentials are used** to access S3.

**Configuration:**
```
AGENTBOX_DATA_ACCESS_MODE=tenant | path | path_credentials
```

### Mode 1: Tenant-Scoped (current behavior)

The simplest mode. All S3 paths are prefixed with the tenant identifier from
the JWT. The worker uses its own IAM credentials to access S3.

**JWT claims used:** `sub` (or configurable tenant claim)

**S3 path resolution:**
```
base_path = s3://{bucket}/{prefix}
scoped_path = {base_path}/{tenant}/{repo_id}/...
```

**Example:**
```
JWT: { "sub": "user-123" }
Request: repo_id = "my-project"
S3 path: s3://agentbox-data/repos/user-123/my-project/...
```

**Access:** Worker's IAM role has broad access to the bucket. Isolation is
enforced by the orchestrator always prepending the tenant prefix.

**Use case:** Single-user workspaces, personal sandboxes, dev/test.

---

### Mode 2: Path-Scoped (caller specifies path)

The caller passes a `data_path` that is appended to the base S3 path. The JWT
is used **only for authentication** (is this caller allowed to call the API at
all?). The `data_path` is a request parameter — it is not derived from or
validated against JWT claims. The calling application is responsible for
determining the correct path before making the request.

The worker uses its own IAM credentials to access S3.

**JWT role:** Authentication only (signature, expiry, issuer). Not used for
S3 path authorization.

**Request parameters:**
```json
{
  "box_type": "git",
  "data_path": "acme-corp/channels/C12345"
}
```

**S3 path resolution:**
```
base_path = s3://{bucket}/{prefix}
scoped_path = {base_path}/{data_path}/...
```

**Example:**
```
JWT: { "sub": "user-123" }   ← authentication only
Request: data_path = "acme-corp/channels/C12345"
S3 path: s3://agentbox-data/repos/acme-corp/channels/C12345/...
```

**Trust model:** AgentBox trusts the caller to pass a `data_path` that the
user is authorized to access. Authorization is the **caller's responsibility**
(the calling application verified this before making the request).

**Path validation (security):**
- `data_path` is validated against `_validate_s3_key()` per segment
- `..`, absolute paths, and traversal patterns are rejected
- The scoped path can never escape the base bucket prefix

**Use case:** Slack channel data, shared case files, team workspaces — where
the calling application knows which path the user should access.

---

### Mode 3: Path-Scoped with Credentials (BYOC — Bring Your Own Credentials)

Same as Mode 2, but the caller also provides **S3 credentials** for accessing
the specified path. The worker uses these credentials instead of its own IAM
role. The JWT is used **only for authentication** — both `data_path` and
`s3_credentials` are request parameters, independent of JWT claims.

This is the most secure mode: the worker never has broad S3 access. Each
session gets temporary credentials that can only reach the authorized path.

**Request parameters:**
```json
{
  "box_type": "git",
  "data_path": "acme-corp/channels/C12345",
  "s3_credentials": {
    "access_key_id": "ASIA...",
    "secret_access_key": "...",
    "session_token": "...",
    "expiration": "2026-06-19T22:00:00Z",
    "region": "us-east-1",
    "endpoint_url": null
  },
  "credential_webhook_url": "https://myapp.example.com/hooks/agentbox/credentials"
}
```

**Who mints the credentials?**

The **calling application** (not AgentBox) obtains scoped credentials before
making the sandbox request. Typical flow:

```
1. Caller authenticates user (JWT)
2. Caller determines data_path for this session
3. Caller calls STS AssumeRole with inline policy:
     { "Effect": "Allow",
       "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
       "Resource": [
         "arn:aws:s3:::agentbox-data/repos/acme-corp/channels/C12345/*",
         "arn:aws:s3:::agentbox-data"
       ],
       "Condition": { "StringLike": { "s3:prefix": "repos/acme-corp/channels/C12345/*" } }
     }
4. Caller passes temporary credentials + data_path to AgentBox API
5. Worker uses provided credentials for all S3 operations in this session
```

**Credential lifecycle:**
- Credentials are **per-session** — stored in `SandboxRecord.metadata`
- Passed to the `S3StorageBackend` instance for that sandbox
- `expiration` is tracked by the orchestrator
- Never logged, never persisted beyond the session lifetime

**Credential refresh (webhook pattern):**

The caller provides a `credential_webhook_url` at sandbox creation. When
credentials are nearing expiry, the orchestrator calls the webhook. The caller
processes the webhook and calls the orchestrator back with fresh credentials.

```
┌────────┐          ┌──────────────┐          ┌────────┐
│ Caller │          │ Orchestrator │          │ Worker │
└───┬────┘          └──────┬───────┘          └───┬────┘
    │  create sandbox       │                      │
    │  + s3_credentials     │                      │
    │  + webhook_url        │                      │
    │─────────────────────>│──── proxy create ────>│
    │                       │                      │
    │     (time passes, credentials nearing expiry) │
    │                       │                      │
    │  POST webhook_url     │                      │
    │  { sandbox_id,        │                      │
    │    expires_at,        │                      │
    │    data_path }        │                      │
    │<─────────────────────│                      │
    │                       │                      │
    │  (caller mints fresh STS creds)              │
    │                       │                      │
    │  PATCH /sandboxes/{id}/credentials           │
    │  { s3_credentials }   │                      │
    │─────────────────────>│── proxy cred update ─>│
    │                       │                      │
    │                       │  (worker swaps boto3  │
    │                       │   client credentials) │
```

**Webhook request (orchestrator → caller):**
```json
POST {credential_webhook_url}
{
  "event": "credentials_expiring",
  "sandbox_id": "sb-abc123",
  "data_path": "acme-corp/channels/C12345",
  "expires_at": "2026-06-19T22:00:00Z",
  "expires_in_seconds": 300
}
```

**Credential update (caller → orchestrator):**
```
PATCH /sandboxes/{sandbox_id}/credentials
{
  "s3_credentials": {
    "access_key_id": "ASIA...(new)",
    "secret_access_key": "...(new)",
    "session_token": "...(new)",
    "expiration": "2026-06-19T23:00:00Z"
  }
}
```

**Orchestrator behavior:**
- Tracks `credential_expires_at` per sandbox
- Fires webhook `AGENTBOX_CREDENTIAL_EXPIRY_LEAD_TIME` seconds before expiry
  (default: 300s / 5 minutes)
- If no webhook URL is configured, expiry is the caller's responsibility
  (poll `GET /sandboxes/{id}` which includes `credential_expires_at`)
- If webhook fails or caller doesn't respond, S3 operations fail with
  `S3_CREDENTIALS_EXPIRED` error code

**Use case:** Multi-tenant SaaS where the platform (not AgentBox) controls S3
access policies. Zero-trust model — AgentBox workers have no standing S3
permissions.

---

## Mode Comparison

| | Mode 1: Tenant | Mode 2: Path | Mode 3: Path + Creds |
|---|---|---|---|
| **S3 path** | `{tenant}/{repo_id}` | `{data_path}` | `{data_path}` |
| **S3 credentials** | Worker IAM role | Worker IAM role | Caller-provided (STS) |
| **Authz source** | JWT `sub` (implicit) | Caller (external to AgentBox) | Credential scope (S3 policy) |
| **Trust model** | Trust orchestrator scoping | Trust caller to pass correct path | Trust nothing — creds are scoped |
| **Blast radius** | Worker can access all tenant paths | Worker can access all bucket paths | Worker can only access session path |
| **Complexity** | Low | Medium | Higher (caller must mint creds) |
| **Multi-user shared data** | No | Yes | Yes |

---

## Implementation Plan

### Phase 1: Mode infrastructure + Mode 2/3 support ✅ COMPLETE

- [x] Add `AGENTBOX_DATA_ACCESS_MODE` env var (`tenant` | `path` | `path_credentials`)
- [x] Add `DataAccessMode` enum + `data_access_mode` field to `JWTConfig` (read at startup)
- [x] Add `data_path` field to `CreateSandboxRequest` (orchestrator)
  - Mode `tenant`: `data_path` rejected if provided
  - Mode `path` / `path_credentials`: `data_path` **required**
- [x] Add `s3_credentials` field to `CreateSandboxRequest` (orchestrator)
  - Mode `path_credentials`: **required** (rejected if missing)
  - Mode `tenant` / `path`: rejected if provided
- [x] Add `credential_webhook_url` + `webhook_secret` optional fields
- [x] Path validation: `_validate_data_path()` rejects `..`, absolute paths, empty
  segments, non-S3-safe characters
- [x] Orchestrator rejects requests that don't match the configured mode
- [x] In `path` / `path_credentials` mode, JWT is authentication only (no path authz)
- [x] Add `data_path` + `credential_expires_at` fields to `SandboxRecord`
- [x] Redis round-trip serialization for new fields (backward compatible)
- [x] Store webhook config in `SandboxRecord.metadata` (never credentials)
- [x] Expose `data_path` + `credential_expires_at` in `GET /sandboxes/{id}` response
- [x] Pass `s3_credentials` through full chain:
  orchestrator → worker internal API → `BoxManager` → `GitBox` → `_get_storage()`
- [x] `S3StorageBackend` accepts `session_token` for STS temporary credentials
- [x] `S3StorageBackend.update_credentials()` method for credential refresh
- [x] `GitBox` stores credentials in shell env (`AGENTBOX_S3_CREDENTIALS`)
- [x] Host-delegated git push/pull/fetch use caller-provided credentials via
  `_get_s3_credentials()` from shell environment
- [x] 46 tests passing (`test/test_data_access_modes.py`)

**Files modified:**
- `agentbox/api/auth.py` — `DataAccessMode` enum, `JWTConfig.data_access_mode`
- `agentbox/orchestrator/routes/sandboxes.py` — `S3Credentials`, validation, mode routing
- `agentbox/orchestrator/state.py` — `SandboxRecord` new fields + serialization
- `agentbox/api/models.py` — worker-side `CreateSandboxRequest.s3_credentials`
- `agentbox/api/routes/internal.py` — pass `s3_credentials` to `BoxManager`
- `agentbox/manager/box_manager.py` — thread `s3_credentials` to `GitBox`
- `agentbox/box/git_box.py` — `_get_storage(s3_credentials=...)`, env injection
- `agentbox/box/git/storage.py` — `session_token` param, `update_credentials()`
- `agentbox/box/shell/host_commands/git_sync.py` — `_get_s3_credentials()`, credential passthrough

### Phase 2: Credential refresh (webhook + PATCH + graceful shutdown) ✅ COMPLETE

- [x] `PATCH /sandboxes/{id}/credentials` endpoint on orchestrator
  - Validates mode is `path_credentials`, checks sandbox exists and not destroyed
  - Proxies to worker via `proxy_to_worker` (PATCH support added to proxy)
  - Updates `credential_expires_at` in Redis after successful worker update
- [x] Worker-side `PATCH /internal/sandboxes/{id}/credentials` endpoint
  - `BoxManager.update_credentials()` swaps `_s3_credentials` on `GitBox`
  - Updates shell env `AGENTBOX_S3_CREDENTIALS` for host-delegated git push/pull
  - Next git push/pull creates fresh `S3StorageBackend` with new creds
- [x] `OrchestratorState.update_credential_expiry()` — atomic Redis HSET
- [x] Background `credential_check_loop` (asyncio task in orchestrator lifespan)
  - Starts only in `path_credentials` mode
  - Configurable: `AGENTBOX_CREDENTIAL_EXPIRY_LEAD_TIME` (default 300s),
    `AGENTBOX_CREDENTIAL_GRACE_PERIOD` (default 60s),
    `AGENTBOX_CREDENTIAL_CHECK_INTERVAL` (default 30s)
- [x] `_check_credentials()` single-pass logic:
  - Expired → destroy sandbox + clear route
  - Within grace period → graceful shutdown (best-effort destroy via proxy)
  - Within lead time → fire webhook (once per sandbox, retry once on failure)
  - Far from expiry → no action
- [x] Webhook firing with HMAC-SHA256 signing:
  - Payload: `{ event, sandbox_id, data_path, expires_at, expires_in_seconds }`
  - `X-AgentBox-Signature: sha256={hmac}` header (using `webhook_secret`)
  - Retry once on failure, then log warning
- [x] `UpdateCredentialsRequest` Pydantic model with required `S3Credentials`
- [x] 62 tests passing (`test/test_data_access_modes.py`)

**New files:**
- `agentbox/orchestrator/credential_checker.py` — background task + webhook logic

**Files modified:**
- `agentbox/orchestrator/proxy.py` — PATCH method support
- `agentbox/orchestrator/routes/sandboxes.py` — `UpdateCredentialsRequest`, PATCH endpoint
- `agentbox/orchestrator/state.py` — `update_credential_expiry()`
- `agentbox/orchestrator/app.py` — lifespan starts/stops credential checker task
- `agentbox/api/routes/internal.py` — worker-side PATCH credentials endpoint
- `agentbox/manager/box_manager.py` — `update_credentials()` method

### Phase 3: Enhanced authorization

- [ ] Support `allowed_paths` JWT claim (list of glob patterns)
- [ ] Optional external authz endpoint (call before granting access)
- [ ] Worker-side path enforcement (defense in depth — validate all S3 ops)
- [ ] Audit trail: log `(sub, org_id, data_path, action)` for every S3 access

---

## Keycloak Configuration (for reference)

To include `org_id` in tokens from Keycloak:

1. **User attribute**: Add `org_id` attribute to users
2. **Protocol mapper**: Create "User Attribute" mapper on the client:
   - Name: `org_id`
   - Mapper Type: User Attribute
   - User Attribute: `org_id`
   - Token Claim Name: `org_id`
   - Add to ID token: Yes
   - Add to access token: Yes

For `allowed_paths`, use a **Script Mapper** or **Hardcoded Claim** mapper, or
have the calling application mint a downstream JWT with path claims after
checking its own authorization logic.

---

## Decisions

1. **Default mode** — Mode 1 (`tenant`). Backward compatible.

2. **Credential transport security** — TLS is sufficient. No additional
   encryption layer on the credentials field.

3. **Credential rotation** — Supported via webhook pattern (see Mode 3).
   Orchestrator fires webhook before expiry, caller PATCHes fresh credentials.

4. **Credential expiry** — Caller passes `expiration` in `s3_credentials`.
   Orchestrator tracks it and fires webhook proactively (Option A).

5. **MinIO compatibility** — `endpoint_url` field in `s3_credentials` handles
   non-AWS S3-compatible stores.

## Open Questions

1. ~~**Migration**~~ — **DECIDED.** A given S3 bucket operates in one mode
   only. No mixed layouts within a bucket. Switching from Mode 1 to Mode 2/3
   requires migrating existing data from `{sub}/{repo_id}/...` to the new
   path structure, or using a separate bucket for the new mode. No
   compatibility layer needed — the mode is a clean cutover per bucket.

2. ~~**Sandbox reuse**~~ — **DECIDED.** Not an issue. Credentials are provided
   per sandbox creation. Each new sandbox with the same `data_path` gets its
   own fresh credentials in the create request. No implicit credential
   carryover between sandboxes.

3. ~~**Webhook authentication**~~ — **DECIDED.** HMAC shared secret. The
   caller provides a `webhook_secret` at sandbox creation. The orchestrator
   signs each webhook payload with `HMAC-SHA256(secret, body)` and includes
   the signature in the `X-AgentBox-Signature` header. The caller verifies
   the signature before processing.

4. ~~**Webhook failure**~~ — **DECIDED.** If the caller doesn't PATCH new
   credentials after the webhook, the orchestrator initiates a **graceful
   shutdown** of the sandbox before the credentials actually expire. This
   gives the sandbox a window to flush/write any pending changes to S3
   while the credentials are still valid, rather than letting operations
   fail unpredictably after expiry.

   Timeline:
   - `expires_at - lead_time` (e.g. 5 min before): fire webhook
   - `expires_at - grace_period` (e.g. 1 min before): if no PATCH received,
     begin graceful shutdown (sandbox writes pending changes)
   - `expires_at`: credentials expire, sandbox destroyed

---

## Industry Comparison — How Other Platforms Handle This

### The Emerging Pattern: Harness ↔ Compute Split

The industry consensus (OpenAI Agents SDK, AWS, E2B, Daytona) separates:
- **Harness (control plane):** orchestration, auth, billing, model calls, audit —
  runs in trusted infrastructure
- **Compute (execution plane):** file I/O, commands, code execution, mounted
  storage — runs in an isolated sandbox

Credentials and storage mounts are injected by the **harness** into the
**compute boundary** at session creation time. The sandbox never reaches out
to discover what it can access — it's told.

### Platform-by-Platform

| Platform | How storage/data is passed to sandbox | Auth model |
|----------|--------------------------------------|------------|
| **OpenAI Agents SDK** | `Manifest` with `S3Mount`, `GCSMount`, `R2Mount`, `AzureBlobMount` entries. Credentials passed via provider-specific mount options at run time, NOT in prompts/instructions. Harness injects. | Harness authenticates user. Sandbox gets scoped mount creds only. |
| **E2B** | Caller writes S3/GCS creds to a file inside sandbox at runtime (`sandbox.files.write('/root/.passwd-s3fs', creds)`), then runs FUSE mount command. All done by the calling application, not by the agent. | API key authenticates caller to E2B. Storage creds are BYOC — caller passes them per-session. |
| **Daytona** | Workspace creation accepts volume mounts with credentials. Secrets fetched from Vault at creation time, injected as env vars. | Platform authenticates caller. Sandbox gets only per-session secrets. |
| **AWS Bedrock AgentCore** | Code Interpreter gets an execution IAM role. For scoped access, `AssumeRole` with inline session policy restricts S3 to specific paths. Caller (or platform) mints scoped STS credentials. | IAM role = permission ceiling. Session policy = per-invocation scope. |
| **Firecracker/self-hosted** | Orchestrator fetches secrets from Vault per-tenant at creation, injects as env vars. "Never bake API keys into sandbox templates." | Orchestrator authenticates user. Sandbox gets injected credentials. |

### Key Principles (from AWS Security Blog + OWASP Agentic Top 10)

1. **Assume all granted permissions will be used.** Design based on acceptable
   blast radius, not intended functionality. An agent with broad S3 access WILL
   eventually access something unintended (hallucination, prompt injection, logic error).

2. **Use session policies / scoped credentials for per-operation access.**
   The execution role is a ceiling; scope down per invocation with STS
   `AssumeRole` + inline policy that restricts to specific S3 prefixes.

3. **The harness injects credentials, the sandbox consumes them.** Secrets
   don't cross the boundary via prompts, instructions, or agent reasoning.
   They're runtime configuration injected at creation.

4. **Credential lifetime = session lifetime.** Credentials expire with the
   session. No persistence beyond the sandbox's life.

### How Our Modes Map to Industry Best Practice

| Our Mode | Industry Equivalent | Assessment |
|----------|-------------------|------------|
| **Mode 1: Tenant** | Legacy pattern (broad IAM role, path isolation by convention). Acceptable for single-tenant dev/test. | ⚠️ Not recommended for production multi-tenant. Blast radius = entire bucket. |
| **Mode 2: Path** | E2B pattern (caller specifies path, platform trusts caller). Worker has broad IAM, path is convention. | ✅ Matches E2B/Daytona. Simple. Relies on caller doing authz. |
| **Mode 3: Path + Creds** | AWS best practice (scoped STS credentials per session). Matches AgentCore pattern. | ✅ Gold standard. Zero-trust. Worker can't exceed session scope. |

### What Our Plan Gets Right

- **Mode 3 aligns with AWS/OWASP best practice** — scoped, short-lived,
  per-session credentials that limit blast radius to one path.
- **Service-level mode** — deployment decides the trust model once, not per-request.
  This matches how E2B/Daytona configure at the platform level.
- **JWT for authn only (Mode 2/3)** — matches OpenAI/E2B pattern where the
  harness authenticates the caller, then passes data/creds as runtime config
  independent of the token.
- **Caller is responsible for authz (Mode 2/3)** — matches the harness/compute
  split. The calling application (harness) determines what the agent should
  access, then tells the compute boundary.

### What We Could Add (from industry patterns)

1. **Mount abstraction** — OpenAI's `S3Mount` / `GCSMount` manifest entries are
   a clean API. We could expose a similar `mounts` field rather than raw
   `data_path` + `s3_credentials` for better DX.

2. **Secrets store integration** — Daytona/Firecracker patterns fetch from Vault
   at creation time. We could optionally support `secret_ref` (a Vault/SSM path)
   instead of raw credentials, so the orchestrator resolves credentials at
   creation time without the caller handling raw keys.

3. **Session policy template** — AWS pattern of `AssumeRole` with an inline
   policy scoped to the session's path. The orchestrator could mint credentials
   itself (instead of requiring the caller to do it) given a base role ARN +
   path. This is a hybrid of Mode 2 and Mode 3: caller passes path, orchestrator
   mints scoped creds.

4. **Audit differentiation** — AWS principle 3: tag agent-initiated actions
   differently from human actions. We could attach session tags to STS
   credentials identifying the sandbox_id and user sub.
