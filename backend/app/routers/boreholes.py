"""Depth data, photos and the activity log of a borehole."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .. import audit, details
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
    report = _report_or_404(borehole_id)
    _require_edit(user, report)
    before, after = details.save_details(report["BoreholeID"], payload, user["email"])
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
    report = _report_or_404(payload.borehole_id)
    _require_edit(user, report)
    try:
        meta = details.add_photo(report["BoreholeID"], payload, user["email"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except details.PhotoLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit.record(user["email"], "photo.added", report["BoreholeID"], {"caption": [None, meta["caption"]]})
    return meta


@router.get("/photos/{photo_id}")
def get_photo(photo_id: str, user=Depends(get_current_user)):
    found = details.read_photo(photo_id) if details.find_photo(photo_id) else None
    if found is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    content_type, data = found
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/photos/{photo_id}")
def remove_photo(photo_id: str, user=Depends(get_current_user)):
    found = details.find_photo(photo_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    borehole_id, meta = found
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
        _report_or_404(target)
    return audit.list_events(target=target, limit=limit)
