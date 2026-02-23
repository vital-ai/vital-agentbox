# Configuration Reference

All AgentBox configuration is via environment variables. No config files needed.

## Worker

### Sandbox management

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_MAX_SANDBOXES` | `50` | Maximum concurrent sandboxes per worker |
| `AGENTBOX_IDLE_TIMEOUT` | `300` | Seconds before idle sandbox is reaped |
| `AGENTBOX_MAX_LIFETIME` | `3600` | Maximum sandbox lifetime in seconds |
| `AGENTBOX_EXEC_TIMEOUT` | `30` | Per-execution timeout in seconds |
| `AGENTBOX_REAPER_INTERVAL` | `30` | How often the reaper checks for idle sandboxes (seconds) |

### Pyodide

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_PYODIDE_URL` | CDN URL (`cdn.jsdelivr.net/pyodide/v0.29.3/...`) | Pyodide JS URL. Override for local bundling. |
| `AGENTBOX_PYODIDE_BUNDLE` | `<project_root>/pyodide-bundle` | Local Pyodide bundle path (Docker: `/app/pyodide-bundle`) |

### Worker identity and registration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_WORKER_ID` | Auto-generated (`worker-<uuid>`) | Unique worker identifier |
| `AGENTBOX_WORKER_HOST` | Auto-detected hostname | Hostname reachable by orchestrator |
| `AGENTBOX_WORKER_PORT` | `8000` | Port the worker listens on |
| `AGENTBOX_ORCHESTRATOR_URL` | — | Orchestrator URL for self-registration. If unset, worker runs standalone. |
| `AGENTBOX_HEARTBEAT_INTERVAL` | `15` | Heartbeat interval in seconds |

### Git / isomorphic-git

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_ISOMORPHIC_GIT_URL` | `https://unpkg.com/isomorphic-git@1.27.1/index.umd.min.js` | isomorphic-git JS URL |

## Orchestrator

### Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_REDIS_URL` | `redis://localhost:6379` | Redis connection URL. Use `rediss://` for TLS. |
| `AGENTBOX_REDIS_CLUSTER` | `false` | Set `true` for Redis Cluster / AWS MemoryDB |
| `AGENTBOX_REDIS_USERNAME` | — | ACL username (for MemoryDB) |
| `AGENTBOX_REDIS_PASSWORD` | — | Auth token / password |
| `AGENTBOX_REDIS_TLS_SKIP_VERIFY` | `false` | Skip TLS certificate verification |
| `AGENTBOX_REDIS_PREFIX` | `agentbox:` | Key prefix for all Redis keys |

### JWT authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_JWT_ENABLED` | `false` | Enable JWT auth on all endpoints (except `/health`, `/internal/*`) |
| `AGENTBOX_JWT_JWKS_URI` | — | JWKS endpoint URL (e.g. Keycloak). Auto-fetches and caches public keys. |
| `AGENTBOX_JWT_PUBLIC_KEY` | — | Static RS256/ES256 public key (alternative to JWKS) |
| `AGENTBOX_JWT_SECRET` | — | Shared secret for HS256 (alternative to JWKS) |
| `AGENTBOX_JWT_ALGORITHM` | `RS256` | JWT signing algorithm |
| `AGENTBOX_JWT_ISSUER` | — | Expected token issuer (validated if set) |
| `AGENTBOX_JWT_AUDIENCE` | — | Expected token audience (validated if set) |
| `AGENTBOX_JWT_CLIENT_ID` | — | Keycloak client ID |
| `AGENTBOX_JWT_ROLES_CLAIM` | `realm_access.roles` | JSON path to roles in the token |
| `AGENTBOX_JWT_SCOPE_CLAIM` | `scope` | JSON path to scopes in the token |
| `AGENTBOX_JWT_TENANT_CLAIM` | `sub` | JSON path to tenant ID (used for repo scoping) |
| `AGENTBOX_JWT_ADMIN_ROLE` | `admin` | Role name that grants admin access |

## Storage (GitBox)

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_GIT_STORE` | `local` | Storage backend: `s3` or `local` |
| `AGENTBOX_GIT_STORE_PATH` | `/tmp/agentbox-repos` | Local storage directory (when `local`) |
| `AGENTBOX_GIT_S3_BUCKET` | — | S3 bucket name (required when `s3`) |
| `AGENTBOX_GIT_S3_PREFIX` | `repos/` | S3 key prefix |
| `AGENTBOX_GIT_S3_ENDPOINT` | — | Custom S3 endpoint URL (for MinIO) |
| `AGENTBOX_GIT_S3_REGION` | — | S3 region |
| `AWS_ACCESS_KEY_ID` | — | AWS/MinIO access key |
| `AWS_SECRET_ACCESS_KEY` | — | AWS/MinIO secret key |
| `AWS_DEFAULT_REGION` | `us-east-1` | AWS default region |

## Keycloak example

```bash
AGENTBOX_JWT_ENABLED=true
AGENTBOX_JWT_JWKS_URI=https://keycloak.example.com/realms/myrealm/protocol/openid-connect/certs
AGENTBOX_JWT_ISSUER=https://keycloak.example.com/realms/myrealm
AGENTBOX_JWT_AUDIENCE=agentbox
AGENTBOX_JWT_CLIENT_ID=agentbox
```

## AWS MemoryDB example

```bash
AGENTBOX_REDIS_URL=rediss://clustercfg.my-cluster.xxxxx.memorydb.us-east-1.amazonaws.com:6379
AGENTBOX_REDIS_CLUSTER=true
AGENTBOX_REDIS_USERNAME=my-acl-user
AGENTBOX_REDIS_PASSWORD=my-auth-token
```

## MinIO example

```bash
AGENTBOX_GIT_STORE=s3
AGENTBOX_GIT_S3_BUCKET=agentbox-repos
AGENTBOX_GIT_S3_ENDPOINT=http://minio:9000
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
```

## See also

- [Docker](../operations/docker.md) — image configuration
- [Scaling](../operations/scaling.md) — orchestrator + worker setup
- [Storage](../operations/storage.md) — S3/MinIO/local backends
