"""Data checks page (administrators and managers)."""
from fastapi import APIRouter, Depends, HTTPException, Query

from .. import data_checks
from ..auth import get_current_user

router = APIRouter(prefix="/api", tags=["data-checks"])


@router.get("/data-checks")
def checks(days: int = Query(default=7, ge=0, le=365), user=Depends(get_current_user)):
    if user.get("role") not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Your role cannot open this page")
    return data_checks.run(days)
