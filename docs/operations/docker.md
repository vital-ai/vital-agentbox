# Docker

AgentBox ships two Docker images: a **worker** (heavy, runs Chromium +
Pyodide sandboxes) and an **orchestrator** (thin, routes requests to workers).

## Images

### Worker (`Dockerfile.worker`)

~1.5–2 GB. Includes Chromium, Pyodide, Playwright, and all sandbox deps.

```
python:3.11-slim
├── System deps (Chromium libs, pandoc, LaTeX)
├── Playwright + Chromium
├── Pyodide bundle (0.29.3)
├── Python deps (vital-agentbox[worker])
└── Application source
```

**Layer strategy**: Heavy deps (Chromium, Pyodide) are installed early so
they're cached across builds. Application source is the last layer for
fast iteration.

Key environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_PYODIDE_URL` | `http://localhost:8000/static/pyodide/pyodide.js` | Pyodide JS URL |
| `AGENTBOX_PYODIDE_BUNDLE` | `/app/pyodide-bundle` | Local Pyodide bundle path |
| `AGENTBOX_ORCHESTRATOR_URL` | — | Orchestrator URL for self-registration |
| `AGENTBOX_WORKER_ID` | — | Unique worker identifier |
| `AGENTBOX_WORKER_HOST` | — | Hostname reachable by orchestrator |
| `AGENTBOX_MAX_SANDBOXES` | `50` | Max concurrent sandboxes |

### Orchestrator (`Dockerfile.orchestrator`)

~200 MB. No Chromium. Just FastAPI + Redis + boto3.

```
python:3.11-slim
├── Python deps (vital-agentbox[orchestrator])
└── Application source
```

Key environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `AGENTBOX_JWT_ENABLED` | `false` | Enable JWT authentication |

## Building

```bash
# Build both images
docker compose build

# Build individually
docker build -f Dockerfile.worker -t agentbox-worker .
docker build -f Dockerfile.orchestrator -t agentbox-orchestrator .
```

## Docker Compose

The included `docker-compose.yml` starts the full stack for local testing:

```bash
docker compose up
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| **orchestrator** | 8090 | API gateway, routes to workers |
| **worker-1** | 8091 | Sandbox worker |
| **worker-2** | 8092 | Sandbox worker |
| **minio** | 9100 (API), 9101 (console) | S3-compatible storage |
| **minio-init** | — | Creates default bucket on startup |

Redis must be running separately on the host (port 6381):

```bash
docker run -d -p 6381:6379 redis:7-alpine
```

### Shared memory

Workers need `shm_size: 2g` for Chromium:

```yaml
worker-1:
  shm_size: 2g
```

Without this, Chromium will crash with out-of-memory errors.

## Deployment modes

### Mode 1: Single worker (dev)

No orchestrator, no Redis. Client talks directly to the worker:

```bash
docker run -p 8090:8000 --shm-size=2g agentbox-worker
```

### Mode 2: Workers behind load balancer

Multiple workers behind an ALB/nginx. No orchestrator — the load balancer
handles routing. Sandboxes are pinned to workers via sticky sessions.

### Mode 3: Orchestrator + workers (production)

Full stack with intelligent routing. The orchestrator tracks which worker
hosts each sandbox and proxies requests accordingly.

```
Client → Orchestrator → Worker-1 (sandbox A, B)
                      → Worker-2 (sandbox C, D)
```

See [Scaling](scaling.md) for details.

## Health checks

```bash
# Worker health
curl http://localhost:8091/health

# Orchestrator health
curl http://localhost:8090/health

# Metrics (sandbox counts, etc.)
curl http://localhost:8090/metrics
```

## See also

- [Installation](../getting-started/install.md) — pip install options
- [Scaling](scaling.md) — multi-worker deployment
- [Storage](storage.md) — S3/MinIO configuration
- [Configuration](../reference/config.md) — all environment variables
