"""
Sandbox lifecycle routes for the orchestrator.

Creates sandboxes on workers, proxies all sandbox operations,
and maintains the sandbox database in Redis.
"""

import re
import time

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from agentbox.orchestrator.state import SandboxRecord
from agentbox.orchestrator.proxy import proxy_to_worker


router = APIRouter()


_S3_SAFE_RE = re.compile(r"^[a-zA-Z0-9._@-]+$")


def _validate_s3_key(value: str, field: str) -> str:
    """Validate a string is safe for S3 key paths. Raises HTTPException if not.

    Allowed: alphanumeric, hyphens, underscores, dots, @.
    Rejected: empty, whitespace, slashes, path traversal, special chars.
    """
    s = value.strip()
    if not s or ".." in s or "/" in s or "\\" in s:
        raise HTTPException(status_code=400, detail=f"Invalid {field}: {value!r}")
    if not _S3_SAFE_RE.match(s):
        raise HTTPException(status_code=400, detail=f"Invalid {field}: {value!r} — only alphanumeric, hyphens, underscores, dots, @ allowed")
    return s


class CreateSandboxRequest(BaseModel):
    box_type: str = "mem"  # mem, git
    repo_id: Optional[str] = None
    timeout: Optional[int] = None
    metadata: Optional[dict] = None


class ExecuteRequest(BaseModel):
    code: str
    language: str = "python"


class ShellRequest(BaseModel):
    command: str


class WriteFileRequest(BaseModel):
    path: str
    content: str


class MkdirRequest(BaseModel):
    path: str


class CopyRequest(BaseModel):
    src: str
    dst: str


# --- Sandbox CRUD ---

@router.post("/sandboxes")
async def create_sandbox(req: CreateSandboxRequest, request: Request):
    """Create a sandbox on the best available worker."""
    state = request.app.state.orchestrator_state
    claims = getattr(request.state, "claims", None)

    # Pick worker with most capacity
    worker = await state.pick_worker()
    if not worker:
        raise HTTPException(status_code=503, detail="No workers available")

    # Scope repo_id to tenant to prevent cross-tenant collisions.
    # "my-project" with tenant "user-123" → "user-123/my-project" in storage.
    # With JWT off (no tenant), repo_id is used as-is.
    tenant = claims.sub if claims and claims.sub else None
    scoped_repo_id = None
    if req.repo_id:
        safe_repo = _validate_s3_key(req.repo_id, "repo_id")
        if tenant:
            safe_tenant = _validate_s3_key(tenant, "tenant")
            scoped_repo_id = f"{safe_tenant}/{safe_repo}"
        else:
            scoped_repo_id = safe_repo

    # Create sandbox on worker
    body = {"box_type": req.box_type}
    if scoped_repo_id:
        body["repo_id"] = scoped_repo_id
    if req.timeout:
        body["timeout"] = req.timeout

    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{worker.endpoint}/internal/sandboxes",
                json=body,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise HTTPException(status_code=502, detail=f"Worker {worker.worker_id} unreachable: {e}")

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text or f"Worker returned {resp.status_code}"
        raise HTTPException(status_code=resp.status_code, detail=detail)

    result = resp.json()
    sandbox_id = result["sandbox_id"]

    # Store route and record
    await state.set_route(sandbox_id, worker.worker_id)
    await state.create_sandbox_record(SandboxRecord(
        id=sandbox_id,
        worker_id=worker.worker_id,
        box_type=req.box_type,
        repo_id=req.repo_id,
        state="running",
        created_at=time.time(),
        last_active=time.time(),
        created_by=claims.sub if claims else None,
        metadata=req.metadata or {},
    ))

    return result


@router.get("/sandboxes")
async def list_sandboxes(
    request: Request,
    state_filter: Optional[str] = None,
    box_type: Optional[str] = None,
):
    """List sandboxes visible to the current tenant."""
    state = request.app.state.orchestrator_state
    claims = getattr(request.state, "claims", None)
    tenant = claims.sub if claims and claims.sub else None

    # Admin sees all, tenants see their own
    from agentbox.api.auth import get_admin_role
    admin_role = get_admin_role(request)
    is_admin = claims and hasattr(claims, 'roles') and admin_role in claims.roles if claims else False
    records = await state.list_sandbox_records(
        state=state_filter,
        tenant=None if is_admin else tenant,
    )

    if box_type:
        records = [r for r in records if r.box_type == box_type]

    return {
        "sandboxes": [
            {
                "id": r.id,
                "worker_id": r.worker_id,
                "box_type": r.box_type,
                "repo_id": r.repo_id,
                "state": r.state,
                "created_at": r.created_at,
                "last_active": r.last_active,
            }
            for r in records
        ],
        "total": len(records),
    }


@router.get("/sandboxes/{sandbox_id}")
async def get_sandbox(sandbox_id: str, request: Request):
    """Get sandbox status (proxied to worker + enriched with DB record)."""
    state = request.app.state.orchestrator_state

    record = await state.get_sandbox_record(sandbox_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id} not found")

    # If still alive, get live status from worker
    if record.state != "destroyed":
        try:
            live = await proxy_to_worker(state, sandbox_id, "GET", "")
            return {**live, "created_by": record.created_by, "metadata": record.metadata}
        except HTTPException:
            pass  # Worker may be gone — return DB record

    return {
        "sandbox_id": record.id,
        "worker_id": record.worker_id,
        "box_type": record.box_type,
        "state": record.state,
        "created_at": record.created_at,
        "last_active": record.last_active,
        "created_by": record.created_by,
        "metadata": record.metadata,
    }


@router.delete("/sandboxes/{sandbox_id}")
async def destroy_sandbox(sandbox_id: str, request: Request):
    """Destroy a sandbox (proxied to worker, clears routing)."""
    state = request.app.state.orchestrator_state

    # Try to destroy on worker
    try:
        result = await proxy_to_worker(state, sandbox_id, "DELETE", "")
    except HTTPException as e:
        if e.status_code != 404:
            raise
        result = {"status": "not_found_on_worker"}

    # Update DB and clear route
    await state.update_sandbox_state(sandbox_id, "destroyed")
    await state.delete_route(sandbox_id)

    return {"status": "destroyed", "sandbox_id": sandbox_id}


# --- Execution (proxied) ---

@router.post("/sandboxes/{sandbox_id}/execute")
async def execute(sandbox_id: str, req: ExecuteRequest, request: Request):
    """Execute code in a sandbox (proxied to worker)."""
    state = request.app.state.orchestrator_state
    return await proxy_to_worker(state, sandbox_id, "POST", "execute", body=req.model_dump())


@router.post("/sandboxes/{sandbox_id}/shell")
async def shell(sandbox_id: str, req: ShellRequest, request: Request):
    """Execute a shell command (proxied to worker)."""
    state = request.app.state.orchestrator_state
    return await proxy_to_worker(state, sandbox_id, "POST", "shell", body=req.model_dump())


# --- File operations (proxied) ---

@router.get("/sandboxes/{sandbox_id}/files")
async def list_files(sandbox_id: str, request: Request, path: str = "/"):
    """List directory contents (proxied to worker)."""
    state = request.app.state.orchestrator_state
    return await proxy_to_worker(state, sandbox_id, "GET", "files", params={"path": path})


@router.get("/sandboxes/{sandbox_id}/files/read")
async def read_file(sandbox_id: str, request: Request, path: str = "/",
                    binary: bool = False):
    """Read a file (proxied to worker)."""
    state = request.app.state.orchestrator_state
    params = {"path": path}
    if binary:
        params["binary"] = "true"
    return await proxy_to_worker(state, sandbox_id, "GET", "files/read", params=params)


@router.post("/sandboxes/{sandbox_id}/files/write")
async def write_file(sandbox_id: str, req: WriteFileRequest, request: Request):
    """Write a file (proxied to worker)."""
    state = request.app.state.orchestrator_state
    return await proxy_to_worker(state, sandbox_id, "POST", "files/write", body=req.model_dump())


@router.post("/sandboxes/{sandbox_id}/files/mkdir")
async def mkdir(sandbox_id: str, req: MkdirRequest, request: Request):
    """Create a directory (proxied to worker)."""
    state = request.app.state.orchestrator_state
    return await proxy_to_worker(state, sandbox_id, "POST", "files/mkdir", body=req.model_dump())


@router.delete("/sandboxes/{sandbox_id}/files")
async def remove_file(sandbox_id: str, request: Request, path: str = "/"):
    """Remove a file (proxied to worker)."""
    state = request.app.state.orchestrator_state
    return await proxy_to_worker(state, sandbox_id, "DELETE", "files", params={"path": path})


@router.post("/sandboxes/{sandbox_id}/files/copy")
async def copy_file(sandbox_id: str, req: CopyRequest, request: Request):
    """Copy a file (proxied to worker)."""
    state = request.app.state.orchestrator_state
    return await proxy_to_worker(state, sandbox_id, "POST", "files/copy", body=req.model_dump())
