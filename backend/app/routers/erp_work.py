"""Live views of work coordination: my tasks, standard phase tasks of a project, task status by the
assignee, the field submission inbox and its steps, a user's field records of one day, the crew
roster with man-days, the laboratory work order board and the menu counters.
Records themselves are read and saved through /api/records."""
import re
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import audit, erp_work, records
from ..auth import get_current_user
from ..entities import ENTITIES

router = APIRouter(prefix="/api/erp/work", tags=["erp-work"])

_ID = re.compile(r"^[a-f0-9]{16,24}$")


def _role(user: dict) -> str:
    return str(user.get("role", "general"))


def _need(entity: str, user: dict) -> None:
    if not records.can_read(ENTITIES[entity], _role(user)):
        raise HTTPException(status_code=403, detail="Your role cannot open this page")


def _id(value: str) -> str:
    if not _ID.match(value or ""):
        raise HTTPException(status_code=404, detail="Not Found")
    return value


@router.get("/summary")
def summary(user=Depends(get_current_user)):
    """Counters for the menu: my open and overdue tasks, packages waiting, overdue lab work orders."""
    return erp_work.summary(_role(user), user["email"])


@router.get("/overview")
def overview(user=Depends(get_current_user)):
    if _role(user) not in ("admin", "manager", "finance"):
        raise HTTPException(status_code=403, detail="Your role cannot open this page")
    return erp_work.overview(_role(user), user["email"])


# --------------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------------- #

@router.get("/my-tasks")
def my_tasks(user=Depends(get_current_user)):
    _need("tasks", user)
    return erp_work.my_tasks(user["email"])


@router.get("/tasks")
def tasks(project_id: Optional[str] = Query(default=None, max_length=40), user=Depends(get_current_user)):
    """Tasks with their live overdue flag, optionally of one project (the task board)."""
    _need("tasks", user)
    today = date.today()
    projects = {p["id"]: p for p in records.list_records("projects")}
    rows = [erp_work.task_view(t, today, projects) for t in records.list_records("tasks")
            if not project_id or t.get("project_id") == project_id]
    entity = ENTITIES["tasks"]
    me = user["email"].lower()
    for r in rows:
        r["_can_edit"] = records.can_write(entity, _role(user), r, user["email"])
        r["_can_status"] = r["_can_edit"] or str(r.get("assignee") or "").lower() == me
    rows.sort(key=erp_work._task_order)
    return rows


class StatusChange(BaseModel):
    status: str = Field(min_length=2, max_length=20)
    note: str = Field(default="", max_length=300)
    checklist: Optional[List[bool]] = Field(default=None, max_length=40)


@router.post("/tasks/{record_id}/status")
def task_status(record_id: str, payload: StatusChange, user=Depends(get_current_user)):
    _need("tasks", user)
    try:
        record = erp_work.set_task_status(_id(record_id), payload.status, payload.note, payload.checklist, _role(user), user["email"])
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except records.RecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    audit.record(user["email"], "tasks.status", str(record.get("title") or record_id), {"status": payload.status})
    return record


@router.get("/projects/{project_id}/standard-tasks")
def standard_tasks_preview(project_id: str, user=Depends(get_current_user)):
    """The phase tasks a project would get, and which it has already."""
    _need("tasks", user)
    try:
        project = records.get_record("projects", _id(project_id))
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    have = {str(t.get("template_key") or "") for t in records.list_records("tasks") if t.get("project_id") == project_id}
    plan = erp_work.standard_task_plan(project)
    return [{**p, "exists": p["template_key"] in have} for p in plan]


@router.post("/projects/{project_id}/standard-tasks")
def standard_tasks(project_id: str, user=Depends(get_current_user)):
    if _role(user) not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Your role cannot change this record")
    try:
        project = records.get_record("projects", _id(project_id))
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        out = erp_work.create_standard_tasks(project, user["email"])
    except records.RecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    audit.record(user["email"], "tasks.standard", str(project.get("code") or project_id), out)
    return out


# --------------------------------------------------------------------------- #
# Field submissions
# --------------------------------------------------------------------------- #

@router.get("/submissions/inbox")
def submission_inbox(user=Depends(get_current_user)):
    return erp_work.submission_inbox(_role(user), user["email"])


@router.get("/submissions/{record_id}/actions")
def submission_actions(record_id: str, user=Depends(get_current_user)):
    _need("field_submissions", user)
    try:
        record = records.get_record("field_submissions", _id(record_id))
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    if not records.can_see(ENTITIES["field_submissions"], _role(user), record, user["email"]):
        raise HTTPException(status_code=404, detail="Not Found")
    return {"actions": erp_work.submission_allowed(record, _role(user), user["email"])}


class Step(BaseModel):
    action: str = Field(min_length=3, max_length=12)
    note: str = Field(default="", max_length=1000)


@router.post("/submissions/{record_id}/act")
def submission_act(record_id: str, payload: Step, user=Depends(get_current_user)):
    _need("field_submissions", user)
    try:
        record = erp_work.submission_act(_id(record_id), payload.action, payload.note, _role(user), user["email"])
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    except erp_work.FlowError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    audit.record(user["email"], f"field_submissions.{payload.action}", str(record.get("number") or record_id),
                 {"note": payload.note} if payload.note else None)
    return {**record, "_actions": erp_work.submission_allowed(record, _role(user), user["email"]),
            "_can_edit": records.locked_by_workflow(ENTITIES["field_submissions"], record, _role(user)) is None
            and records.can_write(ENTITIES["field_submissions"], _role(user), record, user["email"])}


@router.get("/day-records")
def day_records(day: str = Query(alias="date", min_length=10, max_length=10), project_id: str = Query(default="", max_length=40),
                user=Depends(get_current_user)):
    """The user's daily reports, worksheets, CPT tests and borehole logs of one day, to put in a package."""
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=422, detail="date is not a valid date")
    return erp_work.day_records(day, project_id, _role(user), user["email"])


# --------------------------------------------------------------------------- #
# Crew roster
# --------------------------------------------------------------------------- #

@router.get("/roster")
def roster(project_id: str = Query(default="", max_length=40), user=Depends(get_current_user)):
    _need("crew_deployments", user)
    return erp_work.roster(_role(user), user["email"], project_id)


# --------------------------------------------------------------------------- #
# Laboratory work orders
# --------------------------------------------------------------------------- #

@router.get("/lab/board")
def lab_board(user=Depends(get_current_user)):
    _need("lab_work_orders", user)
    return erp_work.lab_board(_role(user), user["email"])


class FromTests(BaseModel):
    test_ids: List[str] = Field(min_length=1, max_length=300)
    priority: str = Field(default="normal", max_length=10)
    technician: str = Field(default="", max_length=254)
    agreed_due: str = Field(default="", max_length=10)


@router.post("/lab/orders/from-tests", status_code=201)
def lab_order_from_tests(payload: FromTests, user=Depends(get_current_user)):
    entity = ENTITIES["lab_work_orders"]
    if not records.can_write(entity, _role(user), None, user["email"]):
        raise HTTPException(status_code=403, detail="Your role cannot change this record")
    try:
        record = erp_work.create_order_from_tests([_id(t) for t in payload.test_ids], payload.model_dump(), user["email"])
    except records.RecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except records.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    audit.record(user["email"], "lab_work_orders.created", str(record.get("number") or ""), {"tests": len(payload.test_ids)})
    return record
