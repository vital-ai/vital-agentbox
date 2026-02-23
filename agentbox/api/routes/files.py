"""File operation endpoints for sandbox MemFS."""

import base64

from fastapi import APIRouter, Depends, HTTPException, Query

from agentbox.api.deps import get_manager
from agentbox.api.models import (
    WriteFileRequest,
    MkdirRequest,
    CopyRequest,
    FileContentResponse,
)
from agentbox.manager.box_manager import BoxManager

router = APIRouter(prefix="/sandboxes/{sandbox_id}/files", tags=["files"])


def _get_box(sandbox_id: str, mgr: BoxManager):
    """Resolve sandbox_id to a started Box, or raise 404."""
    info = mgr._sandboxes.get(sandbox_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id!r} not found.")
    return info.box


@router.get("")
async def list_dir(sandbox_id: str,
                   path: str = Query("/", description="Directory path"),
                   recursive: bool = Query(False),
                   info: bool = Query(False),
                   mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    result = await box.memfs.list_dir(path, recursive=recursive, info=info)
    return {"path": path, "entries": result}


@router.get("/read", response_model=FileContentResponse)
async def read_file(sandbox_id: str,
                    path: str = Query(..., description="File path to read"),
                    binary: bool = Query(False, description="Read as binary (base64)"),
                    mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    if binary:
        data = await box.memfs.read_file_binary(path)
        if data is None:
            return FileContentResponse(path=path, content=None, exists=False)
        return FileContentResponse(
            path=path,
            content=base64.b64encode(data).decode("ascii"),
            exists=True,
        )
    content = await box.memfs.read_file(path)
    if content is None:
        return FileContentResponse(path=path, content=None, exists=False)
    return FileContentResponse(path=path, content=content, exists=True)


@router.post("/write", status_code=201)
async def write_file(sandbox_id: str, req: WriteFileRequest,
                     mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    ok = await box.memfs.write_file(req.path, req.content)
    if not ok:
        raise HTTPException(status_code=500, detail="Write failed.")
    return {"path": req.path, "written": True}


@router.post("/mkdir", status_code=201)
async def mkdir(sandbox_id: str, req: MkdirRequest,
                mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    ok = await box.memfs.mkdir_p(req.path)
    if not ok:
        raise HTTPException(status_code=500, detail="mkdir failed.")
    return {"path": req.path, "created": True}


@router.delete("")
async def remove_file(sandbox_id: str,
                      path: str = Query(..., description="File path to remove"),
                      mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    ok = await box.memfs.remove_file(path)
    if not ok:
        raise HTTPException(status_code=404, detail=f"File {path!r} not found or remove failed.")
    return {"path": path, "removed": True}


@router.delete("/dir")
async def remove_dir(sandbox_id: str,
                     path: str = Query(..., description="Directory path to remove"),
                     mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    ok = await box.memfs.rmdir(path)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Directory {path!r} not found or remove failed.")
    return {"path": path, "removed": True}


@router.post("/copy")
async def copy(sandbox_id: str, req: CopyRequest,
               mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    ok = await box.memfs.copy(req.src, req.dst)
    if not ok:
        raise HTTPException(status_code=500, detail="Copy failed.")
    return {"src": req.src, "dst": req.dst, "copied": True}
