from fastapi import APIRouter, Depends

from ..analytics import build_dashboard_report
from ..auth import get_current_user
from ..storage import load_reports


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("")
def dashboard():
    return build_dashboard_report(load_reports())
