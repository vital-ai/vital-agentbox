# Scaling

AgentBox uses a separate orchestrator and worker architecture for
horizontal scaling. The orchestrator is stateless (backed by Redis) and
workers are independently scalable.

## Architecture

```
                    ┌─────────────────────┐
                    │  Load Balancer (ALB) │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Orchestrator(s)     │
                    │  (stateless, N+1)   │
                    │  ┌────────────────┐ │
                    │  │  Redis state   │ │
                    │  └────────────────┘ │
                    └──┬───────────────┬──┘
                       │               │
              ┌────────▼──┐    ┌───────▼───┐
              │  Worker-1  │    │  Worker-2  │
              │  50 sandboxes   │  50 sandboxes
              └────────────┘    └───────────┘
```

## How routing works

1. Client sends `POST /sandboxes` to the orchestrator
2. Orchestrator picks a worker with capacity
3. Orchestrator stores `sandbox_id → worker_id` in Redis
4. All subsequent requests for that sandbox are proxied to the correct worker
5. On `DELETE /sandboxes/{id}`, the routing entry is removed

## Redis state

The orchestrator stores all state in Redis:

| Key pattern | Value | TTL |
|-------------|-------|-----|
| `agentbox:route:{sandbox_id}` | `worker_id` | Sandbox lifetime |
| `agentbox:worker:{worker_id}` | `{endpoint, capacity, state}` | Heartbeat-based |

### Redis configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `AGENTBOX_REDIS_CLUSTER` | `false` | Set `true` for Redis Cluster / MemoryDB |
| `AGENTBOX_REDIS_USERNAME` | — | ACL username |
| `AGENTBOX_REDIS_PASSWORD` | — | Auth token |
| `AGENTBOX_REDIS_TLS_SKIP_VERIFY` | `false` | Skip TLS certificate verification |

For **AWS MemoryDB**:

```
AGENTBOX_REDIS_URL=rediss://clustercfg.my-cluster.xxxxx.memorydb.us-east-1.amazonaws.com:6379
AGENTBOX_REDIS_CLUSTER=true
AGENTBOX_REDIS_USERNAME=my-acl-user
AGENTBOX_REDIS_PASSWORD=my-auth-token
```

## Worker registration

Workers self-register with the orchestrator on startup:

1. Worker starts and calls `POST /internal/workers/register` with its
   endpoint, capacity, and worker ID
2. Worker sends periodic heartbeats (`POST /internal/workers/heartbeat`)
3. On shutdown (SIGTERM), worker calls `POST /internal/workers/deregister`
4. If heartbeats stop, the orchestrator marks the worker as unhealthy

### Worker configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_ORCHESTRATOR_URL` | — | Orchestrator URL to register with |
| `AGENTBOX_WORKER_ID` | auto-generated | Unique worker identifier |
| `AGENTBOX_WORKER_HOST` | hostname | Hostname reachable by orchestrator |
| `AGENTBOX_MAX_SANDBOXES` | `50` | Maximum concurrent sandboxes |

## Scaling strategies

### Dual scaling

AgentBox supports two scaling mechanisms simultaneously:

1. **Orchestrator-driven** (application-level): The orchestrator calls
   `ecs:RunTask` to launch new workers when existing ones are near capacity.

2. **ECS auto-scaling** (infrastructure-level): CloudWatch metrics trigger
   ECS to scale worker tasks based on CPU/memory utilization.

Both are safe to run simultaneously because workers self-register via
Redis, making registration idempotent.

### Scaling triggers

| Trigger | Action |
|---------|--------|
| All workers > 80% sandbox capacity | Orchestrator launches new worker |
| CPU > 70% across workers | ECS auto-scaling adds worker tasks |
| Worker heartbeat missing | Orchestrator marks unhealthy, redistributes |

## Multi-orchestrator

The orchestrator is stateless — run multiple instances behind a load
balancer for high availability. Redis distributed locks coordinate
scale-up decisions to prevent thundering herd.

```yaml
# ECS: 2+ orchestrator tasks behind ALB
orchestrator:
  desired_count: 2
  health_check: /health
```

## JWT authentication

Enable authentication to scope sandboxes by tenant:

| Variable | Description |
|----------|-------------|
| `AGENTBOX_JWT_ENABLED` | Set `true` to enforce JWT auth |
| `AGENTBOX_JWT_JWKS_URI` | JWKS endpoint (e.g. Keycloak) |
| `AGENTBOX_JWT_ISSUER` | Expected token issuer |
| `AGENTBOX_JWT_AUDIENCE` | Expected token audience |
| `AGENTBOX_JWT_ALGORITHM` | `RS256` (default) |
| `AGENTBOX_JWT_ROLES_CLAIM` | Claim path for roles (e.g. `realm_access.roles`) |
| `AGENTBOX_JWT_TENANT_CLAIM` | Claim path for tenant ID (e.g. `sub`) |
| `AGENTBOX_JWT_ADMIN_ROLE` | Role name for admin access |

Tenant scoping: the orchestrator prefixes `repo_id` with the tenant's
`sub` claim → `{tenant}/{repo_id}` in S3. This prevents cross-tenant
data access.

## See also

- [Docker](docker.md) — images, docker-compose
- [Storage](storage.md) — S3/MinIO configuration
- [Configuration](../reference/config.md) — all environment variables
