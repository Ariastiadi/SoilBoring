from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import get_current_user
from ..models import Report, ReportUpdate
from ..storage import (
    DuplicateReportError,
    SchemaMismatchError,
    delete_report,
    get_report,
    load_reports,
    save_report,
    update_report,
)


router = APIRouter(prefix="/api/reports", tags=["reports"])


def _can_modify(user: dict, report: dict) -> bool:
    """Admins may change any log; other users only the logs they submitted."""
    if user.get("role") == "admin":
        return True
    owner = str(report.get("SubmittedBy") or "").strip().lower()
    return bool(owner) and owner == str(user.get("email") or "").strip().lower()


def _parse_day(value) -> Optional[datetime]:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except ValueError:
        return None


def _load_or_409():
    try:
        return load_reports()
    except SchemaMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("", status_code=status.HTTP_201_CREATED)
def create_report(report: Report, user=Depends(get_current_user)):
    try:
        save_report(report.model_dump(), submitted_by=user["email"])
    except DuplicateReportError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A borehole with ID '{report.BoreholeID}' already exists",
        )
    except SchemaMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"status": "ok"}


@router.get("")
def list_reports(user=Depends(get_current_user)):
    return _load_or_409()


@router.delete("/{borehole_id}")
def remove_report(borehole_id: str, user=Depends(get_current_user)):
    existing = get_report(borehole_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if not _can_modify(user, existing):
        raise HTTPException(status_code=403, detail="You can only delete logs you submitted")
    if not delete_report(borehole_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"status": "deleted"}


@router.put("/{borehole_id}")
def edit_report(
    borehole_id: str,
    changes: ReportUpdate,
    user=Depends(get_current_user),
):
    existing = get_report(borehole_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if not _can_modify(user, existing):
        raise HTTPException(status_code=403, detail="You can only edit logs you submitted")
    updates = changes.model_dump(exclude_unset=True)
    start = _parse_day(updates.get("StartDate") or existing.get("StartDate"))
    end = _parse_day(updates.get("EndDate") or existing.get("EndDate"))
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="StartDate must not be after EndDate")
    if not update_report(borehole_id, updates):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"status": "updated"}
