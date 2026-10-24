from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from .. import audit, details
from ..auth import get_current_user
from ..models import Report, ReportUpdate
from ..storage import DuplicateReportError, delete_report, load_reports, save_report, update_report


router = APIRouter(prefix="/api/reports", tags=["reports"])


def can_modify(user: dict, report: dict) -> bool:
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


def _owner_check(user: dict, action: str):
    def authorize(row: Dict[str, Any]) -> None:
        if not can_modify(user, row):
            raise HTTPException(status_code=403, detail=f"You can only {action} logs you submitted")

    return authorize


def _check_dates(row: Dict[str, Any]) -> None:
    start = _parse_day(row.get("StartDate"))
    end = _parse_day(row.get("EndDate"))
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="StartDate must not be after EndDate")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_report(report: Report, user=Depends(get_current_user)):
    try:
        save_report(report.model_dump(), submitted_by=user["email"])
    except DuplicateReportError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A borehole with ID '{report.BoreholeID}' already exists",
        ) from exc
    audit.record(user["email"], "log.created", report.BoreholeID)
    return {"status": "ok"}


@router.get("")
def list_reports(user=Depends(get_current_user)):
    return load_reports()


# ":path" so that legacy IDs containing "/" can still be edited and deleted.
@router.delete("/{borehole_id:path}")
def remove_report(borehole_id: str, user=Depends(get_current_user)):
    removed = delete_report(borehole_id, authorize=_owner_check(user, "delete"))
    if not removed:
        raise HTTPException(status_code=404, detail="Report not found")
    details.delete_details(removed["BoreholeID"])
    audit.record(user["email"], "log.deleted", removed["BoreholeID"])
    return {"status": "deleted"}


@router.put("/{borehole_id:path}")
def edit_report(
    borehole_id: str,
    changes: ReportUpdate,
    user=Depends(get_current_user),
):
    updates = changes.model_dump(exclude_unset=True)
    result = update_report(borehole_id, updates, authorize=_owner_check(user, "edit"), validate=_check_dates)
    if result is None:
        raise HTTPException(status_code=404, detail="Report not found")
    before, after = result
    changed = audit.diff(before, after)
    if changed:
        audit.record(user["email"], "log.updated", after["BoreholeID"], changed)
    return {"status": "updated"}
