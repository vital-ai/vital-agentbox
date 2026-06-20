"""FastAPI worker application with BoxManager lifespan.

Exposes two sets of routes:
- Public: /health, /sandboxes/*, /metrics (for Mode 1: single worker)
- Internal: /internal/* (for Mode 3: orchestrator proxying)

When AGENTBOX_ORCHESTRATOR_URL is set, the worker self-registers with
the orchestrator on startup and deregisters on shutdown.

WORKER_MODE controls which capabilities are active:
- "code"    → Code sandboxes only (Pyodide)
- "browser" → Browser sessions only (Playwright)
- "both"    → Both capabilities in one process
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

# Worker mode: code, browser, or both
WORKER_MODE = os.environ.get("WORKER_MODE", "code")


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


async def _register_with_orchestrator(manager=None, browser_pool=None):
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
                "type": WORKER_MODE,
                "max_sandboxes": MAX_SANDBOXES if manager else 0,
                "active_sandboxes": len(manager._sandboxes) if manager else 0,
                "max_sessions": browser_pool.max_sessions if browser_pool else 0,
                "active_sessions": browser_pool.active_count if browser_pool else 0,
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
                        "type": WORKER_MODE,
                        "active_sandboxes": len(manager._sandboxes) if manager else 0,
                        "active_sessions": browser_pool.active_count if browser_pool else 0,
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
    """Start BoxManager and/or SessionPool on startup, stop on shutdown."""
    manager = None
    browser_pool = None

    # Start code sandbox manager
    if WORKER_MODE in ("code", "both"):
        manager = BoxManager()
        await manager.start()
        set_manager(manager)

    # Start browser session pool
    if WORKER_MODE in ("browser", "both"):
        from agentbox.browser.pool import SessionPool
        from agentbox.browser.routes import set_pool
        browser_pool = SessionPool()
        await browser_pool.start()
        set_pool(browser_pool)

    # Self-register with orchestrator (if configured)
    heartbeat_task = await _register_with_orchestrator(manager, browser_pool)

    yield

    # Deregister and stop heartbeat
    if heartbeat_task:
        heartbeat_task.cancel()
    await _deregister_from_orchestrator()

    if manager:
        await manager.stop()
        clear_manager()
    if browser_pool:
        await browser_pool.stop()


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

# Code sandbox routes (only when WORKER_MODE includes code)
if WORKER_MODE in ("code", "both"):
    app.include_router(sandbox.router)
    app.include_router(execute.router)
    app.include_router(files.router)
    # Internal code routes (Mode 3: orchestrator proxying)
    app.include_router(internal_router)

# Browser routes (only when WORKER_MODE includes browser)
if WORKER_MODE in ("browser", "both"):
    from agentbox.browser.routes import router as browser_router
    app.include_router(browser_router)

# Mount local Pyodide bundle if it exists
if WORKER_MODE in ("code", "both") and Path(PYODIDE_BUNDLE_PATH).is_dir():
    app.mount("/static/pyodide", StaticFiles(directory=PYODIDE_BUNDLE_PATH), name="pyodide")
