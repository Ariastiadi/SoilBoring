"""Approval steps and the approvals inbox."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit, records, workflow
from ..auth import get_current_user
from ..entities import ENTITIES

router = APIRouter(prefix="/api", tags=["workflow"])


class Step(BaseModel):
    action: str = Field(min_length=3, max_length=12)
    note: str = Field(default="", max_length=1000)


@router.post("/records/{entity_name}/{record_id}/workflow")
def step(entity_name: str, record_id: str, payload: Step, user=Depends(get_current_user)):
    entity = ENTITIES.get(entity_name)
    if entity is None or not records.can_read(entity, user.get("role", "general")):
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        record = workflow.act(entity_name, record_id, payload.action, payload.note, user.get("role", "general"), user["email"])
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    except workflow.WorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit.record(user["email"], f"{entity_name}.{payload.action}", str(record.get(entity.title) or record_id),
                 {"note": payload.note} if payload.note else None)
    role = user.get("role", "general")
    return {**records.for_viewer(entity, record, role),
            "_can_edit": records.locked_by_workflow(entity, record, role) is None and records.can_write(entity, role, record, user["email"]),
            "_actions": workflow.allowed(entity, record, role, user["email"])}


@router.get("/records/{entity_name}/{record_id}/workflow")
def actions(entity_name: str, record_id: str, user=Depends(get_current_user)):
    entity = ENTITIES.get(entity_name)
    if entity is None or not records.can_read(entity, user.get("role", "general")):
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        record = records.get_record(entity_name, record_id)
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    if not records.can_see(entity, user.get("role", "general"), record, user["email"]):
        raise HTTPException(status_code=404, detail="Not Found")
    return {"actions": workflow.allowed(entity, record, user.get("role", "general"), user["email"])}


@router.get("/approvals")
def approvals(user=Depends(get_current_user)):
    return workflow.inbox(user.get("role", "general"), user["email"])
