# Deployment

This guide covers deploying AgentBox from local development to production.

## Deployment modes

### Mode 1: Single worker (development)

Simplest setup. No orchestrator, no Redis. Client talks directly to one worker.

```bash
# Local (no Docker)
uvicorn agentbox.api.app:app --port 8090

# Docker
docker run -p 8090:8000 --shm-size=2g agentbox-worker
```

Client connects to `http://localhost:8090`.

**Pros**: Simple, fast to iterate
**Cons**: No scaling, no auth, single point of failure

### Mode 2: Workers behind load balancer

Multiple workers behind an ALB/nginx. No orchestrator.

```
Client → ALB → Worker-1
              → Worker-2
              → Worker-3
```

Requires sticky sessions (session affinity) so that requests for a sandbox
always reach the same worker. Configure the ALB health check on `/health`.

**Pros**: Simple horizontal scaling
**Cons**: No intelligent routing, sticky sessions required

### Mode 3: Orchestrator + workers (production)

Full stack with intelligent routing, auth, and auto-scaling.

```
Client → ALB → Orchestrator(s) → Worker-1
                                → Worker-2
                                → Worker-N
```

The orchestrator tracks which worker hosts each sandbox (via Redis) and
proxies all requests to the correct worker.

## Docker Compose (local Mode 3)

```bash
# Prerequisites: Redis running on host
docker run -d -p 6381:6379 redis:7-alpine

# Start full stack
docker compose up --build

# Verify
curl http://localhost:8090/health
```

### Services started

| Service | URL | Description |
|---------|-----|-------------|
| Orchestrator | `http://localhost:8090` | API gateway |
| Worker-1 | `http://localhost:8091` | Sandbox worker |
| Worker-2 | `http://localhost:8092` | Sandbox worker |
| MinIO API | `http://localhost:9100` | S3-compatible storage |
| MinIO Console | `http://localhost:9101` | Storage web UI (minioadmin/minioadmin) |

### Test it

```bash
# Create a sandbox
curl -s -X POST http://localhost:8090/sandboxes \
  -H "Content-Type: application/json" \
  -d '{"box_type": "mem"}' | python3 -m json.tool

# Execute code (replace SANDBOX_ID)
curl -s -X POST http://localhost:8090/sandboxes/SANDBOX_ID/execute \
  -H "Content-Type: application/json" \
  -d '{"code": "print(2+2)", "language": "python"}' | python3 -m json.tool
```

## AWS ECS production setup

### Architecture

```
                  ┌──────────────┐
                  │  ALB          │
                  └──────┬───────┘
                         │
              ┌──────────▼──────────┐
              │  ECS Service:       │
              │  Orchestrator (2+)  │
              │  CPU: 0.5 vCPU      │
              │  Memory: 1 GB       │
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │  Redis / MemoryDB   │
              └─────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
   ┌─────▼─────┐  ┌─────▼─────┐  ┌─────▼─────┐
   │  Worker-1  │  │  Worker-2  │  │  Worker-N  │
   │  4 vCPU    │  │  4 vCPU    │  │  4 vCPU    │
   │  8 GB RAM  │  │  8 GB RAM  │  │  8 GB RAM  │
   │  50 sandboxes │            │  │            │
   └────────────┘  └────────────┘  └────────────┘
```

### ECS task definitions

**Orchestrator task**:
- Image: `agentbox-orchestrator`
- CPU: 512 (0.5 vCPU)
- Memory: 1024 MB
- No shm_size needed
- Health check: `curl http://localhost:8000/health`

**Worker task**:
- Image: `agentbox-worker`
- CPU: 4096 (4 vCPU)
- Memory: 8192 MB
- shm_size: 2 GB (required for Chromium)
- Health check: `curl http://localhost:8000/health`

### Required environment variables

**Orchestrator**:
```bash
AGENTBOX_REDIS_URL=rediss://clustercfg.xxx.memorydb.us-east-1.amazonaws.com:6379
AGENTBOX_REDIS_CLUSTER=true
AGENTBOX_REDIS_USERNAME=agentbox
AGENTBOX_REDIS_PASSWORD=<auth-token>
AGENTBOX_JWT_ENABLED=true
AGENTBOX_JWT_JWKS_URI=https://keycloak.example.com/realms/myrealm/protocol/openid-connect/certs
AGENTBOX_JWT_ISSUER=https://keycloak.example.com/realms/myrealm
```

**Worker**:
```bash
AGENTBOX_ORCHESTRATOR_URL=http://orchestrator.internal:8000
AGENTBOX_WORKER_HOST=<ecs-task-ip>
AGENTBOX_MAX_SANDBOXES=50
AGENTBOX_GIT_STORE=s3
AGENTBOX_GIT_S3_BUCKET=agentbox-repos
AWS_DEFAULT_REGION=us-east-1
```

### Auto-scaling

Workers scale based on sandbox utilization:

| Metric | Threshold | Action |
|--------|-----------|--------|
| Sandbox capacity > 80% | Scale up | Orchestrator launches new worker task |
| CPU > 70% | Scale up | ECS auto-scaling adds tasks |
| Sandbox capacity < 20% | Scale down | ECS auto-scaling removes tasks |

Both orchestrator-driven and ECS auto-scaling work simultaneously because
workers self-register via Redis (idempotent registration).

## Health checks

```bash
# Worker
curl http://worker:8000/health
# {"status": "ok", "sandboxes": 12, "max_sandboxes": 50}

# Orchestrator
curl http://orchestrator:8000/health
# {"status": "ok", "workers": 3, "total_sandboxes": 42}
```

## Security checklist

- [ ] JWT auth enabled (`AGENTBOX_JWT_ENABLED=true`)
- [ ] JWKS URI configured (auto-rotating keys)
- [ ] Workers on private subnet (no public IPs)
- [ ] Orchestrator behind ALB with HTTPS
- [ ] Redis/MemoryDB with TLS and ACL auth
- [ ] S3 bucket with server-side encryption
- [ ] Docker images scanned for vulnerabilities
- [ ] `shm_size` set for worker containers

## See also

- [Docker](../operations/docker.md) — image details
- [Scaling](../operations/scaling.md) — routing and auto-scaling
- [Storage](../operations/storage.md) — S3/MinIO configuration
- [Configuration](../reference/config.md) — all environment variables
