"""
Admin routes for the orchestrator.

Provides sandbox management across all workers: list all, inspect,
browse files, force-destroy, bulk operations. Requires admin scope.
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from agentbox.orchestrator.proxy import proxy_to_worker
from agentbox.api.auth import require_scope


router = APIRouter(prefix="/admin")


class BulkDestroyRequest(BaseModel):
    state: Optional[str] = None
    tenant: Optional[str] = None
    sandbox_ids: Optional[list[str]] = None


@router.get("/sandboxes")
async def admin_list_sandboxes(
    request: Request,
    state: Optional[str] = None,
    tenant: Optional[str] = None,
    box_type: Optional[str] = None,
    offset: int = 0,
    limit: int = 100,
):
    """List ALL sandboxes across all workers (admin only)."""
    require_scope(request, "admin")
    orch_state = request.app.state.orchestrator_state

    records = await orch_state.list_sandbox_records(
        state=state, tenant=tenant, offset=offset, limit=limit,
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
                "created_by": r.created_by,
                "metadata": r.metadata,
            }
            for r in records
        ],
        "total": len(records),
        "offset": offset,
        "limit": limit,
    }


@router.get("/sandboxes/{sandbox_id}")
async def admin_get_sandbox(sandbox_id: str, request: Request):
    """Full sandbox detail including worker location (admin only)."""
    require_scope(request, "admin")
    orch_state = request.app.state.orchestrator_state

    record = await orch_state.get_sandbox_record(sandbox_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id} not found")

    worker = await orch_state.get_worker(record.worker_id)

    result = {
        "id": record.id,
        "worker_id": record.worker_id,
        "worker_endpoint": worker.endpoint if worker else None,
        "worker_state": worker.state if worker else "unknown",
        "box_type": record.box_type,
        "repo_id": record.repo_id,
        "state": record.state,
        "created_at": record.created_at,
        "last_active": record.last_active,
        "created_by": record.created_by,
        "metadata": record.metadata,
    }

    # Get live status from worker if sandbox is alive
    if record.state != "destroyed" and worker:
        try:
            live = await proxy_to_worker(orch_state, sandbox_id, "GET", "")
            result["live_status"] = live
        except HTTPException:
            result["live_status"] = None

    return result


@router.get("/sandboxes/{sandbox_id}/files")
async def admin_browse_files(sandbox_id: str, request: Request, path: str = "/"):
    """Browse sandbox file tree (proxied to worker, admin only)."""
    require_scope(request, "admin")
    orch_state = request.app.state.orchestrator_state
    return await proxy_to_worker(orch_state, sandbox_id, "GET", "files", params={"path": path})


@router.get("/sandboxes/{sandbox_id}/files/read")
async def admin_read_file(sandbox_id: str, request: Request, path: str = "/"):
    """Read a file from any sandbox (proxied to worker, admin only)."""
    require_scope(request, "admin")
    orch_state = request.app.state.orchestrator_state
    return await proxy_to_worker(orch_state, sandbox_id, "GET", "files/read", params={"path": path})


@router.delete("/sandboxes/{sandbox_id}")
async def admin_destroy_sandbox(sandbox_id: str, request: Request):
    """Force-destroy a sandbox on any worker (admin only)."""
    require_scope(request, "admin")
    orch_state = request.app.state.orchestrator_state

    try:
        await proxy_to_worker(orch_state, sandbox_id, "DELETE", "")
    except HTTPException as e:
        if e.status_code != 404:
            raise

    await orch_state.update_sandbox_state(sandbox_id, "destroyed")
    await orch_state.delete_route(sandbox_id)
    return {"status": "destroyed", "sandbox_id": sandbox_id}


@router.post("/sandboxes/bulk-destroy")
async def admin_bulk_destroy(req: BulkDestroyRequest, request: Request):
    """Destroy multiple sandboxes by filter or ID list (admin only)."""
    require_scope(request, "admin")
    orch_state = request.app.state.orchestrator_state

    if req.sandbox_ids:
        targets = req.sandbox_ids
    else:
        records = await orch_state.list_sandbox_records(
            state=req.state, tenant=req.tenant,
        )
        targets = [r.id for r in records if r.state != "destroyed"]

    destroyed = []
    errors = []
    for sid in targets:
        try:
            await proxy_to_worker(orch_state, sid, "DELETE", "")
        except HTTPException:
            pass  # Worker may be gone
        await orch_state.update_sandbox_state(sid, "destroyed")
        await orch_state.delete_route(sid)
        destroyed.append(sid)

    return {"destroyed": destroyed, "count": len(destroyed), "errors": errors}


@router.get("/tenants")
async def admin_tenant_summary(request: Request):
    """Sandbox counts per tenant (admin only)."""
    require_scope(request, "admin")
    orch_state = request.app.state.orchestrator_state

    # Get all sandbox records
    records = await orch_state.list_sandbox_records(limit=10000)
    tenant_counts = {}
    for r in records:
        tenant = r.created_by or "(none)"
        if tenant not in tenant_counts:
            tenant_counts[tenant] = {"running": 0, "destroyed": 0, "total": 0}
        tenant_counts[tenant]["total"] += 1
        if r.state == "destroyed":
            tenant_counts[tenant]["destroyed"] += 1
        else:
            tenant_counts[tenant]["running"] += 1

    return {"tenants": tenant_counts}
