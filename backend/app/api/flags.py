"""Background findings (contradictions detected automatically on upload)."""
from __future__ import annotations
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_uid
from app.api.workspaces import require_owned_workspace
from app.services import storage

router = APIRouter(prefix="/workspaces/{workspace_id}/flags", tags=["flags"])


class FlagStatusRequest(BaseModel):
    status: Literal["new", "seen", "dismissed"]


@router.get("")
def list_flags(workspace_id: str, include_dismissed: bool = False, uid: str = Depends(get_current_uid)):
    require_owned_workspace(workspace_id, uid)
    flags = storage.list_flags(workspace_id, include_dismissed=include_dismissed)
    return {"flags": flags, "new_count": sum(1 for f in flags if f["status"] == "new")}


@router.post("/{flag_id}/status")
def set_flag_status(workspace_id: str, flag_id: str, req: FlagStatusRequest,
                    uid: str = Depends(get_current_uid)):
    require_owned_workspace(workspace_id, uid)
    if not any(f["flag_id"] == flag_id for f in storage.list_flags(workspace_id, include_dismissed=True)):
        raise HTTPException(404, "Flag not found")
    storage.update_flag_status(workspace_id, flag_id, req.status)
    return {"flag_id": flag_id, "status": req.status}
