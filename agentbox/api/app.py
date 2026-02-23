"""FastAPI worker application with BoxManager lifespan.

Exposes two sets of routes:
- Public: /health, /sandboxes/*, /metrics (for Mode 1: single worker)
- Internal: /internal/* (for Mode 3: orchestrator proxying)

When AGENTBOX_ORCHESTRATOR_URL is set, the worker self-registers with
the orchestrator on startup and deregisters on shutdown.
"""

import os
import uuid
import asyncio
import socket
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from agentbox.api.deps import set_manager, clear_manager
from agentbox.api.routes import health, sandbox, execute, files
from agentbox.api.routes.internal import router as internal_router
from agentbox.api.auth import JWTConfig, JWTMiddleware
from agentbox.manager.box_manager import BoxManager


# Local Pyodide bundle path (set via env var or default relative to project root)
PYODIDE_BUNDLE_PATH = os.environ.get(
    "AGENTBOX_PYODIDE_BUNDLE",
    str(Path(__file__).resolve().parent.parent.parent / "pyodide-bundle"),
)

# Worker identity and orchestrator registration
WORKER_ID = os.environ.get("AGENTBOX_WORKER_ID", f"worker-{uuid.uuid4().hex[:8]}")
WORKER_PORT = int(os.environ.get("AGENTBOX_WORKER_PORT", "8000"))
ORCHESTRATOR_URL = os.environ.get("AGENTBOX_ORCHESTRATOR_URL")
HEARTBEAT_INTERVAL = int(os.environ.get("AGENTBOX_HEARTBEAT_INTERVAL", "15"))
MAX_SANDBOXES = int(os.environ.get("AGENTBOX_MAX_SANDBOXES", "50"))


def _get_worker_endpoint() -> str:
    """Determine this worker's reachable endpoint."""
    host = os.environ.get("AGENTBOX_WORKER_HOST")
    if not host:
        # Try to get the container's IP
        try:
            host = socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            host = "127.0.0.1"
    return f"http://{host}:{WORKER_PORT}"


async def _register_with_orchestrator(manager: BoxManager):
    """Self-register with orchestrator and start heartbeat loop."""
    if not ORCHESTRATOR_URL:
        return None

    import httpx

    endpoint = _get_worker_endpoint()
    reg_url = f"{ORCHESTRATOR_URL}/internal/workers/register"
    hb_url = f"{ORCHESTRATOR_URL}/internal/workers/heartbeat"

    # Register
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(reg_url, json={
                "worker_id": WORKER_ID,
                "endpoint": endpoint,
                "max_sandboxes": MAX_SANDBOXES,
                "active_sandboxes": len(manager._sandboxes),
            })
    except Exception as e:
        print(f"[worker] Failed to register with orchestrator: {e}")

    # Start heartbeat loop
    async def heartbeat_loop():
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(hb_url, json={
                        "worker_id": WORKER_ID,
                        "active_sandboxes": len(manager._sandboxes),
                        "state": "active",
                    })
            except Exception:
                pass  # Will retry next interval

    task = asyncio.create_task(heartbeat_loop())
    return task


async def _deregister_from_orchestrator():
    """Deregister from orchestrator on shutdown."""
    if not ORCHESTRATOR_URL:
        return
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{ORCHESTRATOR_URL}/internal/workers/deregister", json={
                "worker_id": WORKER_ID,
            })
    except Exception:
        pass  # Best-effort on shutdown


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start BoxManager on startup, stop on shutdown."""
    manager = BoxManager()
    await manager.start()
    set_manager(manager)

    # Self-register with orchestrator (if configured)
    heartbeat_task = await _register_with_orchestrator(manager)

    yield

    # Deregister and stop heartbeat
    if heartbeat_task:
        heartbeat_task.cancel()
    await _deregister_from_orchestrator()
    await manager.stop()
    clear_manager()


app = FastAPI(
    title="AgentBox Worker",
    description="Secure sandboxed code execution for AI agents",
    version="0.0.3",
    lifespan=lifespan,
)

# JWT middleware (configurable via env vars)
jwt_config = JWTConfig.from_env()
app.add_middleware(JWTMiddleware, config=jwt_config)

# Public routes (Mode 1: single worker, direct access)
app.include_router(health.router)
app.include_router(sandbox.router)
app.include_router(execute.router)
app.include_router(files.router)

# Internal routes (Mode 3: orchestrator proxying)
app.include_router(internal_router)

# Mount local Pyodide bundle if it exists
if Path(PYODIDE_BUNDLE_PATH).is_dir():
    app.mount("/static/pyodide", StaticFiles(directory=PYODIDE_BUNDLE_PATH), name="pyodide")
