"""
HTTP proxy: forward requests from orchestrator to the owning worker.

Looks up sandbox_id → worker endpoint in Redis, then forwards the
request using httpx.
"""

import httpx
from fastapi import HTTPException

from agentbox.orchestrator.state import OrchestratorState


async def proxy_to_worker(
    state: OrchestratorState,
    sandbox_id: str,
    method: str,
    path: str,
    body: dict | None = None,
    params: dict | None = None,
    timeout: float = 60.0,
) -> dict:
    """Proxy a request to the worker that owns the given sandbox.

    Args:
        state: OrchestratorState instance (Redis-backed).
        sandbox_id: Sandbox to route to.
        method: HTTP method (GET, POST, DELETE).
        path: Path suffix after /internal/sandboxes/{id}/, e.g. "execute".
        body: JSON body for POST requests.
        params: Query parameters for GET requests.
        timeout: Request timeout in seconds.

    Returns:
        JSON response from the worker.
    """
    # Look up route
    worker_id = await state.get_route(sandbox_id)
    if not worker_id:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id} not found")

    # Look up worker endpoint
    worker = await state.get_worker(worker_id)
    if not worker:
        raise HTTPException(
            status_code=502,
            detail=f"Worker {worker_id} not available (sandbox {sandbox_id})",
        )

    url = f"{worker.endpoint}/internal/sandboxes/{sandbox_id}"
    if path:
        url += f"/{path}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if method == "GET":
                resp = await client.get(url, params=params)
            elif method == "POST":
                resp = await client.post(url, json=body)
            elif method == "DELETE":
                resp = await client.delete(url, params=params)
            else:
                raise HTTPException(status_code=405, detail=f"Method {method} not supported")
        except httpx.ConnectError:
            raise HTTPException(
                status_code=502,
                detail=f"Cannot connect to worker {worker_id} at {worker.endpoint}",
            )
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=504,
                detail=f"Worker {worker_id} timed out",
            )

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text or f"Worker returned {resp.status_code}"
        raise HTTPException(status_code=resp.status_code, detail=detail)

    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}
