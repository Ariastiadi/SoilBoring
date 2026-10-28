"""AGS4 import: check a file (preview) and store it (import). See ags_import.py."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import ags_import
from ..auth import get_current_user

router = APIRouter(prefix="/api/import", tags=["import"])

IMPORT_ROLES = ("admin", "manager", "general")


class AGSFile(BaseModel):
    filename: str = Field(default="", max_length=200)
    content: str = Field(min_length=1, max_length=ags_import.MAX_CHARS)
    project_name: str = Field(default="", max_length=200)
    on_duplicate: Literal["skip", "overwrite"] = "skip"
    include_lab: bool = True


def _allowed(user: dict) -> None:
    if user.get("role") not in IMPORT_ROLES:
        raise HTTPException(status_code=403, detail="Your role cannot import borehole logs")


def _plan(payload: AGSFile, user: dict) -> dict:
    try:
        return ags_import.run(payload.content, project_name=payload.project_name, include_lab=payload.include_lab,
                              on_duplicate=payload.on_duplicate, user=user)
    except ags_import.AGSImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/ags/preview")
def preview(payload: AGSFile, user=Depends(get_current_user)):
    """What the file holds and what an import would create, update or skip. Nothing is stored."""
    _allowed(user)
    return ags_import.public_plan(_plan(payload, user))


@router.post("/ags")
def import_ags(payload: AGSFile, user=Depends(get_current_user)):
    """Store the boreholes, depth data and laboratory results of the file."""
    _allowed(user)
    plan = _plan(payload, user)
    if not plan["can_import"]:
        raise HTTPException(status_code=409, detail="Nothing to import: every borehole is skipped or has errors")
    result = ags_import.apply(plan, user, payload.filename)
    return {**result, "preview": ags_import.public_plan(plan)}
