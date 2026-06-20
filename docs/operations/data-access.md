# S3 Data Access Modes

AgentBox supports three modes for S3 data scoping, configured via
`AGENTBOX_DATA_ACCESS_MODE` on the orchestrator.

## Mode overview

| Mode | Env value | S3 path | Credentials | Use case |
|------|-----------|---------|-------------|----------|
| **Tenant** | `tenant` | `{jwt_sub}/{repo_id}` | Worker IAM role | Multi-tenant SaaS (default) |
| **Path** | `path` | Caller-provided `data_path` | Worker IAM role | Shared infrastructure, caller controls paths |
| **Path + Credentials** | `path_credentials` | Caller-provided `data_path` | Caller-provided STS creds | Zero-trust, caller owns bucket access |

## Mode 1: Tenant (default)

The orchestrator derives the S3 path from the JWT `sub` claim and the
`repo_id`. The worker's IAM role has read/write access to the bucket.

```
S3 path = s3://{bucket}/{prefix}/{sub}/{repo_id}/
```

**Create sandbox:**
```json
POST /sandboxes
{
  "box_type": "git",
  "repo_id": "my-project"
}
```

JWT `sub` = `tenant-123` → S3 path: `repos/tenant-123/my-project/`

## Mode 2: Path

Caller provides an explicit `data_path`. JWT is used for authentication
only (not path scoping). Worker IAM role must have access to the path.

```json
POST /sandboxes
{
  "box_type": "git",
  "data_path": "clients/acme/project-alpha"
}
```

S3 path: `repos/clients/acme/project-alpha/`

## Mode 3: Path + Credentials

Caller provides both `data_path` and temporary STS credentials. The worker
uses these credentials (not its IAM role) for S3 operations. Supports
credential refresh via webhook.

```json
POST /sandboxes
{
  "box_type": "git",
  "data_path": "clients/acme/project-alpha",
  "s3_credentials": {
    "access_key_id": "ASIA...",
    "secret_access_key": "...",
    "session_token": "...",
    "region": "us-east-1",
    "expires_at": "2026-06-20T12:00:00Z"
  },
  "credential_webhook_url": "https://myapp.com/hooks/agentbox",
  "webhook_secret": "my-hmac-secret"
}
```

## Credential refresh (Mode 3)

STS credentials expire. AgentBox handles this automatically:

```
Timeline:
────────────────────────────────────────────────────────►
                    │              │         │
            lead_time (5min)  grace (1min)  expires_at
                    │              │         │
              fire webhook    shutdown if   destroy
                              no PATCH      sandbox
```

### Webhook payload

When credentials are within `AGENTBOX_CREDENTIAL_EXPIRY_LEAD_TIME` of expiry,
the orchestrator POSTs to `credential_webhook_url`:

```json
{
  "event": "credentials_expiring",
  "sandbox_id": "sb-abc123",
  "data_path": "clients/acme/project-alpha",
  "expires_at": "2026-06-20T12:00:00Z",
  "expires_in_seconds": 280
}
```

Headers include `X-AgentBox-Signature: sha256={hmac}` if `webhook_secret` is set.

### Refreshing credentials

Caller PATCHes fresh credentials before expiry:

```json
PATCH /sandboxes/{id}/credentials
{
  "s3_credentials": {
    "access_key_id": "ASIA...(new)",
    "secret_access_key": "...(new)",
    "session_token": "...(new)",
    "expires_at": "2026-06-20T13:00:00Z"
  }
}
```

This resets the expiry timer. The orchestrator proxies the update to the
worker, which hot-swaps credentials without interrupting the sandbox.

### Graceful shutdown

If no PATCH is received within the grace period (default 1 minute before
expiry), the orchestrator initiates graceful shutdown:

1. Sandbox state → `draining`
2. Active operations complete
3. Files synced to S3
4. Sandbox destroyed

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_DATA_ACCESS_MODE` | `tenant` | Mode selection |
| `AGENTBOX_CREDENTIAL_CHECK_INTERVAL` | `30` | Scan interval (seconds) |
| `AGENTBOX_CREDENTIAL_EXPIRY_LEAD_TIME` | `300` | Webhook fire time before expiry |
| `AGENTBOX_CREDENTIAL_GRACE_PERIOD` | `60` | Shutdown if no refresh within this time of expiry |

## See also

- [Storage backends](storage.md) — S3/MinIO/local configuration
- [Configuration](../reference/config.md) — full env var reference
- [Orchestrator API](../api/orchestrator-api.md) — PATCH credentials endpoint
