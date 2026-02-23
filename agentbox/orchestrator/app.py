"""Orchestrator FastAPI application.

Lightweight API gateway that routes sandbox requests to workers,
maintains the sandbox database, and manages worker lifecycle.
No Playwright, no Chromium — just routing and coordination via Redis.

Redis configuration (env vars):
    AGENTBOX_REDIS_URL       — Connection URL (default: redis://localhost:6379)
                               Use rediss:// for TLS (required for MemoryDB).
    AGENTBOX_REDIS_CLUSTER   — Set to 'true' for Redis Cluster mode (MemoryDB).
    AGENTBOX_REDIS_TLS_SKIP_VERIFY — Set to 'true' to skip TLS cert verification.
    AGENTBOX_REDIS_PREFIX    — Key prefix (default: agentbox:)
    AGENTBOX_REDIS_USERNAME  — ACL username (optional, for MemoryDB ACL auth).
    AGENTBOX_REDIS_PASSWORD  — Password / auth token (optional).
"""

import os
import ssl as _ssl
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agentbox.api.auth import JWTConfig, JWTMiddleware
from agentbox.orchestrator.state import OrchestratorState
from agentbox.orchestrator.routes import workers, sandboxes, admin


REDIS_URL = os.environ.get("AGENTBOX_REDIS_URL", "redis://localhost:6379")
REDIS_CLUSTER = os.environ.get("AGENTBOX_REDIS_CLUSTER", "").lower() == "true"
REDIS_TLS_SKIP_VERIFY = os.environ.get("AGENTBOX_REDIS_TLS_SKIP_VERIFY", "").lower() == "true"
REDIS_USERNAME = os.environ.get("AGENTBOX_REDIS_USERNAME")
REDIS_PASSWORD = os.environ.get("AGENTBOX_REDIS_PASSWORD")
REDIS_PREFIX = os.environ.get("AGENTBOX_REDIS_PREFIX", "agentbox:")


def _build_ssl_context():
    """Build an SSL context for TLS connections (MemoryDB requires TLS)."""
    ctx = _ssl.create_default_context()
    if REDIS_TLS_SKIP_VERIFY:
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
    return ctx


async def _get_redis():
    """Create an async Redis or RedisCluster client.

    Supports:
    - Standalone Redis (default): redis://host:port
    - Redis with TLS: rediss://host:port
    - Redis Cluster / AWS MemoryDB: AGENTBOX_REDIS_CLUSTER=true + rediss://
    """
    import redis.asyncio as aioredis

    uses_tls = REDIS_URL.startswith("rediss://")
    ssl_context = _build_ssl_context() if uses_tls else None

    common_kwargs = {
        "decode_responses": True,
    }
    if REDIS_USERNAME:
        common_kwargs["username"] = REDIS_USERNAME
    if REDIS_PASSWORD:
        common_kwargs["password"] = REDIS_PASSWORD

    if uses_tls:
        common_kwargs["ssl"] = ssl_context

    if REDIS_CLUSTER:
        # AWS MemoryDB / ElastiCache Cluster Mode
        # RedisCluster handles slot-based routing automatically.
        client = aioredis.RedisCluster.from_url(
            REDIS_URL,
            **common_kwargs,
        )
        # RedisCluster.from_url doesn't need await, but we ping to verify
        await client.ping()
        return client
    else:
        # Standalone Redis (local dev, single-node ElastiCache)
        return aioredis.from_url(
            REDIS_URL,
            **common_kwargs,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown for the orchestrator."""
    app.state.redis = await _get_redis()
    app.state.orchestrator_state = OrchestratorState(app.state.redis, prefix=REDIS_PREFIX)
    yield
    await app.state.redis.aclose()


app = FastAPI(
    title="AgentBox Orchestrator",
    description="Sandbox routing, worker management, and admin API",
    version="0.1.0",
    lifespan=lifespan,
)

# JWT middleware (configurable via env vars)
jwt_config = JWTConfig.from_env()
app.state.jwt_config = jwt_config
app.add_middleware(JWTMiddleware, config=jwt_config)

# Include routers
app.include_router(workers.router, tags=["workers"])
app.include_router(sandboxes.router, tags=["sandboxes"])
app.include_router(admin.router, tags=["admin"])


@app.get("/health")
async def health():
    """Orchestrator health check."""
    try:
        await app.state.redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    state = app.state.orchestrator_state
    metrics = await state.aggregate_metrics() if redis_ok else {}

    return {
        "status": "healthy" if redis_ok else "degraded",
        "redis": "connected" if redis_ok else "disconnected",
        **metrics,
    }


@app.get("/metrics")
async def metrics():
    """Aggregate metrics across all workers."""
    state = app.state.orchestrator_state
    return await state.aggregate_metrics()
