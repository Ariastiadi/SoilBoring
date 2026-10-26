"""Live views of the operations ERP modules: equipment status board, maintenance due list,
procurement stages, a fixed asset's depreciation schedule as of a date, and the operations overview
for the management dashboard. Records themselves are read and saved through /api/records."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import erp_lab, erp_ops, records
from ..auth import get_current_user
from ..entities import ENTITIES

router = APIRouter(prefix="/api/erp/ops", tags=["erp-ops"])

MANAGEMENT = ("admin", "manager", "finance")


def _role(user: dict) -> str:
    return str(user.get("role", "general"))


def _need(entity: str, user: dict) -> None:
    if not records.can_read(ENTITIES[entity], _role(user)):
        raise HTTPException(status_code=403, detail="Your role cannot open this page")


def _as_of(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="as_of is not a valid date")


@router.get("/overview")
def overview(user=Depends(get_current_user)):
    if _role(user) not in MANAGEMENT:
        raise HTTPException(status_code=403, detail="Your role cannot open this page")
    return erp_ops.overview(_role(user), user["email"])


@router.get("/equipment-status")
def equipment_status(user=Depends(get_current_user)):
    _need("equipment", user)
    return erp_ops.equipment_board()


@router.get("/maintenance-due")
def maintenance_due(user=Depends(get_current_user)):
    _need("equipment", user)
    return erp_ops.maintenance_due()


@router.get("/maintenance-metrics")
def maintenance_metrics(date_from: Optional[str] = Query(default=None, alias="from", max_length=10),
                        date_to: Optional[str] = Query(default=None, alias="to", max_length=10), user=Depends(get_current_user)):
    """Availability, MTBF, MTTR, preventive share and PM compliance (default: the last 12 months)."""
    _need("work_orders", user)
    try:
        return erp_ops.maintenance_metrics(_as_of(date_from), _as_of(date_to))
    except records.RecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/vendor-standing")
def vendor_standing(user=Depends(get_current_user)):
    """Each vendor's status from its latest evaluation (approved vendor list)."""
    _need("vendors", user)
    return erp_ops.vendor_board()


@router.get("/lab/calibration")
def lab_calibration(on: Optional[str] = Query(default=None, max_length=10), user=Depends(get_current_user)):
    """Calibration status of every equipment item with a calibration interval on a date (default today)."""
    _need("lab_tests", user)
    when = _as_of(on) or date.today()
    orders = records.list_records("work_orders")
    return [erp_lab.calibration_on(e, orders, when) for e in sorted(records.list_records("equipment"), key=lambda e: str(e.get("code") or ""))
            if e.get("calibration_months") and e.get("status") != "disposed"]


@router.get("/procurement-status")
def procurement_status(user=Depends(get_current_user)):
    _need("procurements", user)
    role = _role(user)
    entity = ENTITIES["procurements"]
    prs = [p for p in records.list_records("procurements") if records.can_see(entity, role, p, user["email"])]
    # Purchase orders feed the stage even for requesters who cannot open them; amounts stay hidden.
    pos = records.list_records("purchase_orders")
    out = [erp_ops.procurement_status(p, pos) for p in prs]
    if not records.can_read(ENTITIES["purchase_orders"], role):
        for row in out:
            for key in ("ordered", "invoiced", "paid"):
                row[key] = None
            row["orders"] = [{"id": o["id"], "number": o["number"], "progress": o["progress"], "total": None} for o in row["orders"]]
    out.sort(key=lambda r: str(r.get("number") or ""), reverse=True)
    return out


@router.get("/assets/{record_id}/schedule")
def asset_schedule(record_id: str, as_of: Optional[str] = Query(default=None, max_length=10), user=Depends(get_current_user)):
    _need("fixed_assets", user)
    try:
        record = records.get_record("fixed_assets", record_id)
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    return erp_ops.asset_schedule_result(record, _as_of(as_of))


@router.get("/asset-groups")
def asset_groups(user=Depends(get_current_user)):
    """Tax groups (useful life and rates) and the suggested group per asset category, for the form."""
    return {
        "groups": {k: {"life_years": v[0], "straight_line_pct": v[1], "declining_pct": v[2]} for k, v in erp_ops.TAX_TABLE.items()},
        "suggested": erp_ops.SUGGESTED_GROUP,
    }
