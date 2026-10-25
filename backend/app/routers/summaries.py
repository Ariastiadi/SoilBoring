from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Query as Q

from ..auth import get_current_user
from ..storage import load_reports
from ..analytics import build_summary_report


router = APIRouter(prefix="/api/summaries", tags=["summaries"], dependencies=[Depends(get_current_user)])


def _parse_date(value: Optional[str], label: str) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}; use YYYY-MM-DD") from exc


@router.get("")
def summaries(
    period: Literal["weekly", "monthly"] = Q(pattern=r"^(weekly|monthly)$"),
    start_date: Optional[str] = Q(None, description="Start date (YYYY-MM-DD) for weekly summaries"),
    end_date: Optional[str] = Q(None, description="End date (YYYY-MM-DD) for weekly summaries"),
    month: Optional[int] = Q(None, ge=1, le=12, description="Month number for monthly summaries"),
    year: Optional[int] = Q(None, ge=2000, le=2100, description="Year for monthly summaries"),
    lang: str = Q("en", pattern="^(en|id)$", description="Language of the summary text"),
):
    reports = load_reports()
    start_dt = _parse_date(start_date, "start_date")
    end_dt = _parse_date(end_date, "end_date")

    if period == "weekly":
        if (start_date and not end_date) or (end_date and not start_date):
            raise HTTPException(status_code=400, detail="Provide both start_date and end_date for weekly summaries")
        if start_dt and end_dt and start_dt > end_dt:
            raise HTTPException(status_code=400, detail="start_date must be before end_date")
    else:
        if (month is None) != (year is None):
            raise HTTPException(status_code=400, detail="Provide both month and year for monthly summaries")

    return build_summary_report(
        reports,
        period,
        start_date=start_dt,
        end_date=end_dt,
        month=month,
        year=year,
        lang=lang,
    )

