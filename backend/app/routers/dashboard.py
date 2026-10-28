from fastapi import APIRouter, Depends, Query

from .. import dashboard_charts, details
from ..analytics import build_dashboard_report
from ..auth import get_current_user
from ..storage import load_reports


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("")
def dashboard(lang: str = Query("en", pattern="^(en|id)$")):
    rows = load_reports()
    out = build_dashboard_report(rows, lang)
    out.update(dashboard_charts.distributions(rows, details.all_details()))
    return out
