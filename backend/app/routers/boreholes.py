"""Depth data, photos and the activity log of a borehole."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .. import audit, details, docstore, storage
from ..auth import get_current_user
from ..storage import get_report
from .reports import can_modify

router = APIRouter(prefix="/api", tags=["boreholes"])


def _report_or_404(borehole_id: str) -> dict:
    report = get_report(borehole_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


def _require_edit(user: dict, report: dict) -> None:
    if not can_modify(user, report):
        raise HTTPException(status_code=403, detail="You can only edit logs you submitted")


@router.get("/details/{borehole_id:path}")
def read_details(borehole_id: str, user=Depends(get_current_user)):
    report = _report_or_404(borehole_id)
    return {"borehole_id": report["BoreholeID"], **details.get_details(report["BoreholeID"])}


@router.put("/details/{borehole_id:path}")
def write_details(borehole_id: str, payload: details.DetailsIn, user=Depends(get_current_user)):
    # Under the reports lock (always reports -> details), so a log deleted at the same
    # moment cannot leave its depth data behind for a later log with the same ID.
    with docstore.lock(storage.DOC):
        report = _report_or_404(borehole_id)
        _require_edit(user, report)
        try:
            before, after = details.save_details(report["BoreholeID"], payload, user["email"])
        except details.ConflictError as exc:
            conflict = str(exc)
        else:
            conflict = ""
    if conflict:
        raise HTTPException(status_code=409, detail=conflict)
    counts = {
        key: [len(before[key]), len(after[key])]
        for key in ("layers", "spt", "samples", "core")
        if before[key] != after[key]
    }
    if counts:
        audit.record(user["email"], "depth_data.updated", report["BoreholeID"], counts)
    return {"borehole_id": report["BoreholeID"], **after}


class PhotoUpload(details.PhotoIn):
    borehole_id: str = Field(min_length=1, max_length=64)


@router.post("/photos", status_code=201)
def upload_photo(payload: PhotoUpload, user=Depends(get_current_user)):
    try:
        payload.decoded()  # size and type checks before any lock is taken
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with docstore.lock(storage.DOC):
        report = _report_or_404(payload.borehole_id)
        _require_edit(user, report)
        try:
            meta = details.add_photo(report["BoreholeID"], payload, user["email"])
        except details.PhotoLimitError as exc:
            limit_error = str(exc)
        else:
            limit_error = ""
    if limit_error:
        raise HTTPException(status_code=409, detail=limit_error)
    audit.record(user["email"], "photo.added", report["BoreholeID"], {"caption": [None, meta["caption"]]})
    return meta


@router.get("/photos/{photo_id}")
def get_photo(photo_id: str, user=Depends(get_current_user)):
    found = details.read_photo(photo_id) if details.find_photo(photo_id) else None
    if found is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    content_type, data = found
    # Not kept in the browser cache: field tablets are often shared.
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "no-store"})


@router.delete("/photos/{photo_id}")
def remove_photo(photo_id: str, user=Depends(get_current_user)):
    found = details.find_photo(photo_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    borehole_id, meta = found
    with docstore.lock(storage.DOC):
        _require_edit(user, _report_or_404(borehole_id))
        details.delete_photo(photo_id)
    audit.record(user["email"], "photo.deleted", borehole_id, {"caption": [meta.get("caption"), None]})
    return {"status": "deleted"}


@router.get("/audit")
def activity(
    target: Optional[str] = Query(default=None, max_length=254),
    limit: int = Query(default=200, ge=1, le=1000),
    user=Depends(get_current_user),
):
    """Admins see everything; other users see the history of one borehole (target)."""
    if user.get("role") != "admin":
        if not target:
            raise HTTPException(status_code=403, detail="Admin privileges are required to see all activity")
        report = _report_or_404(target)
        # Only the history of that log; account events stay admin-only even when a
        # BoreholeID happens to look like an email address.
        return audit.list_events(target=report["BoreholeID"], limit=limit, logs_only=True)
    return audit.list_events(target=target, limit=limit)
