"""Calculations of the operations ERP modules (see entities_ops.py).

Each ``compute_*`` function is a COMPUTE_HOOK: it runs on every save inside the entity lock, fills
the readonly fields and refuses input that cannot be stored (RecordError). Values that depend on
other records changing later (the effective equipment status, maintenance due dates, procurement
stage) are also worked out live by the functions at the end, used by routers/erp_ops.py.

Warnings are stored as ``warnings`` = [{"text": English template, "vars": {...}, "money": [var names]}]
so the interface can translate the template and format the values; ``warning_count`` is their number.
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .calcbase import result, table

# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _error(message: str) -> Exception:
    from . import records

    return records.RecordError(message)


def _conflict(message: str) -> Exception:
    from . import records

    return records.ConflictError(message)


def _list(entity: str) -> List[Dict[str, Any]]:
    from . import records

    return records.list_records(entity)


def _d(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _n(value: Any) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _opt(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(value: float) -> float:
    return float(round(value))


def add_months(d: date, months: int) -> date:
    """Same day so many months later; the 31st becomes the last day of a shorter month."""
    index = d.year * 12 + d.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _warn(out: List[Dict[str, Any]], text: str, money: Iterable[str] = (), **values: Any) -> None:
    out.append({"text": text, "vars": values, "money": list(money)})


def _set_warnings(record: Dict[str, Any], warnings: List[Dict[str, Any]]) -> None:
    record["warnings"] = warnings
    record["warning_count"] = float(len(warnings))


def _unique(entity: str, record: Dict[str, Any], key: str, label: str) -> None:
    wanted = str(record.get(key) or "").strip().lower()
    if not wanted:
        return
    for other in _list(entity):
        if other.get("id") != record.get("id") and str(other.get(key) or "").strip().lower() == wanted:
            raise _conflict(f"{label} '{record[key]}' is already used")


DEFAULT_SETTINGS: Dict[str, float] = {
    "two_quotes_from": 10_000_000, "three_quotes_from": 50_000_000, "wo_approval_limit": 25_000_000,
    "due_soon_days": 30, "due_soon_hours": 50,
    # Vendor evaluation (ISO 9001:2015 8.4.1 asks for criteria; the weights and limits are the company's own).
    "weight_quality": 30, "weight_delivery": 25, "weight_price": 20, "weight_hse": 15, "weight_responsiveness": 10,
    "vendor_approved_from": 75, "vendor_conditional_from": 60, "vendor_reevaluate_months": 12,
}


def settings() -> Dict[str, float]:
    from . import records

    saved = records.get_singleton("ops_settings") or {}
    out = dict(DEFAULT_SETTINGS)
    for key in out:
        value = _opt(saved.get(key))
        if value is not None:
            out[key] = value
    return out


def lab_authorisation_mode() -> str:
    """"require": a lab test cannot be marked done without authorised results; "warn" (default): it is flagged."""
    from . import records

    saved = records.get_singleton("ops_settings") or {}
    return "require" if saved.get("lab_authorisation") == "require" else "warn"


def role_of(email: str) -> str:
    """Role of a user account ("" when unknown)."""
    from . import auth

    me = (email or "").lower()
    return next((str(u.get("role") or "") for u in auth.list_users() if str(u.get("email") or "").lower() == me), "")


def separation_on() -> bool:
    """Different people for each control step unless company settings turn it off (see workflow.py)."""
    from . import records

    company = records.get_singleton("settings") or {}
    return company.get("approval_separation") is not False


# --------------------------------------------------------------------------- #
# Vendors
# --------------------------------------------------------------------------- #

def compute_vendor(record: Dict[str, Any]) -> None:
    _unique("vendors", record, "name", "Name")


# --------------------------------------------------------------------------- #
# Vendor evaluation (ISO 9001:2015 8.4.1: criteria for the evaluation, selection, monitoring of
# performance and re-evaluation of external providers, with records of the evaluations)
# --------------------------------------------------------------------------- #

VENDOR_CRITERIA: List[Tuple[str, str]] = [
    ("quality", "Quality of goods or work"), ("delivery", "Delivery on time and complete"), ("price", "Price and terms"),
    ("hse", "HSE, legal and document compliance"), ("responsiveness", "Responsiveness and service"),
]


def vendor_score(scores: Dict[str, Any], cfg: Dict[str, float]) -> Optional[float]:
    """Weighted score in %: each criterion's score 1–5 as a share of 5, weighted by the settings.
    None until every criterion with a weight has a score."""
    total_w = 0.0
    acc = 0.0
    for key, _ in VENDOR_CRITERIA:
        w = cfg.get(f"weight_{key}", 0.0)
        if w <= 0:
            continue
        s = _opt(scores.get(key))
        if s is None:
            return None
        total_w += w
        acc += w * s / 5 * 100
    return round(acc / total_w, 2) if total_w else None


def vendor_outcome(score: Optional[float], critical: bool, cfg: Dict[str, float]) -> str:
    if critical:
        return "blocked"
    if score is None:
        return ""
    if score >= cfg["vendor_approved_from"]:
        return "approved"
    if score >= cfg["vendor_conditional_from"]:
        return "conditional"
    return "blocked"


def compute_vendor_evaluation(record: Dict[str, Any]) -> None:
    cfg = settings()
    pf, pt = _d(record.get("period_from")), _d(record.get("period_to"))
    if pf and pt and pt < pf:
        raise _error("Period to is before period from")
    critical = bool(record.get("critical_issue"))
    if critical and not str(record.get("critical_note") or "").strip():
        raise _error("Describe the serious breach that blocks the vendor")
    scores = {key: record.get(f"score_{key}") for key, _ in VENDOR_CRITERIA}
    score = vendor_score(scores, cfg)
    record["score_pct"] = score
    record["outcome"] = vendor_outcome(score, critical, cfg)
    when = _d(record.get("date"))
    months = int(cfg["vendor_reevaluate_months"])
    record["next_evaluation"] = add_months(when, months).isoformat() if (when and months) else None
    record["weights"] = {key: cfg.get(f"weight_{key}", 0.0) for key, _ in VENDOR_CRITERIA}
    warnings: List[Dict[str, Any]] = []
    if score is None and not critical:
        _warn(warnings, "Score every criterion")
    if record["outcome"] in ("conditional", "blocked") and not str(record.get("actions") or "").strip():
        _warn(warnings, "Write the improvement actions agreed with the vendor")
    _set_warnings(record, warnings)


def vendor_standing(vendor_id: str, evaluations: List[Dict[str, Any]], today: date) -> Dict[str, Any]:
    """The vendor's status from its latest evaluation (by date): approved, conditional, blocked,
    or not evaluated; and whether its re-evaluation is overdue."""
    mine = [e for e in evaluations if e.get("vendor_id") == vendor_id and e.get("outcome")]
    if not mine:
        return {"status": "not_evaluated", "score": None, "date": None, "next_due": None, "reevaluation_overdue": False,
                "evaluation_id": None}
    last = max(mine, key=lambda e: (str(e.get("date") or ""), str(e.get("created_at") or "")))
    due = _d(last.get("next_evaluation"))
    return {"status": str(last.get("outcome")), "score": _opt(last.get("score_pct")), "date": last.get("date"),
            "next_due": last.get("next_evaluation"), "reevaluation_overdue": bool(due and due < today),
            "evaluation_id": last.get("id")}


def vendor_board(today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Every vendor with its evaluation standing (live), for the approved vendor list."""
    today = today or date.today()
    evaluations = _list("vendor_evaluations")
    out = []
    for v in sorted(_list("vendors"), key=lambda x: str(x.get("name") or "").lower()):
        row = {"id": v["id"], "name": v.get("name"), "category": v.get("category"), "active": v.get("active") is not False}
        row.update(vendor_standing(v["id"], evaluations, today))
        out.append(row)
    return out


# --------------------------------------------------------------------------- #
# Equipment: calibration and service due dates, effective status
# --------------------------------------------------------------------------- #

ACTIVE_MOB = ("in_transit", "on_site", "demobilising")
BOOKED_MOB = ("planned",) + ACTIVE_MOB
OPEN_WO = ("open", "scheduled", "in_progress", "waiting_parts")


def _last_done(orders: List[Dict[str, Any]], equipment_id: str, types: Tuple[str, ...]) -> Tuple[Optional[date], Optional[float]]:
    """Latest completed work order of these types: its completion date and hour meter."""
    best: Optional[date] = None
    hours: Optional[float] = None
    for wo in orders:
        if wo.get("equipment_id") != equipment_id or wo.get("status") != "completed" or wo.get("type") not in types:
            continue
        done = _d(wo.get("completed_date"))
        if done and (best is None or done > best):
            best = done
        h = _opt(wo.get("hour_meter"))
        if h is not None and (hours is None or h > hours):
            hours = h
    return best, hours


def _latest(*dates: Optional[date]) -> Optional[date]:
    found = [d for d in dates if d]
    return max(found) if found else None


def _highest(*values: Optional[float]) -> Optional[float]:
    found = [v for v in values if v is not None]
    return max(found) if found else None


def _date_status(due: Optional[date], today: date, soon_days: float) -> str:
    if due is None:
        return "ok"
    if due < today:
        return "overdue"
    if (due - today).days <= soon_days:
        return "due_soon"
    return "ok"


_RANK = {"ok": 0, "due_soon": 1, "missing": 2, "overdue": 3}


def equipment_due(eq: Dict[str, Any], orders: List[Dict[str, Any]], today: date, cfg: Dict[str, float]) -> Dict[str, Any]:
    """Next calibration and service of one equipment item, from its own fields and the completed
    work orders (the later of the two wins)."""
    eid = str(eq.get("id") or "")
    cal_months = int(_n(eq.get("calibration_months")))
    cal_done, _ = _last_done(orders, eid, ("calibration",))
    last_cal = _latest(_d(eq.get("last_calibration")), cal_done)
    next_cal = add_months(last_cal, cal_months) if (cal_months and last_cal) else None
    if not cal_months:
        cal_status = ""
    elif last_cal is None:
        cal_status = "missing"
    else:
        cal_status = _date_status(next_cal, today, cfg["due_soon_days"])

    svc_days = int(_n(eq.get("service_days")))
    svc_hours = _n(eq.get("service_hours"))
    svc_done, svc_done_hours = _last_done(orders, eid, ("preventive",))
    _, any_hours = _last_done(orders, eid, ("preventive", "corrective", "calibration", "inspection"))
    last_svc = _latest(_d(eq.get("last_service_date")), svc_done)
    base = last_svc or _d(eq.get("in_service_date"))
    last_svc_hours = _highest(_opt(eq.get("last_service_hours")), svc_done_hours)
    hours_now = _highest(_opt(eq.get("hour_meter")), any_hours)
    next_svc = date.fromordinal(base.toordinal() + svc_days) if (svc_days and base) else None
    next_hours = ((last_svc_hours or 0.0) + svc_hours) if svc_hours else None
    if not svc_days and not svc_hours:
        svc_status = ""
    elif svc_days and base is None and not svc_hours:
        svc_status = "missing"
    else:
        svc_status = _date_status(next_svc, today, cfg["due_soon_days"])
        if next_hours is not None and hours_now is not None:
            if hours_now >= next_hours:
                svc_status = "overdue"
            elif next_hours - hours_now <= cfg["due_soon_hours"] and _RANK[svc_status] < _RANK["due_soon"]:
                svc_status = "due_soon"
    return {
        "last_calibration": last_cal.isoformat() if last_cal else None,
        "next_calibration_due": next_cal.isoformat() if next_cal else None,
        "calibration_days_left": (next_cal - today).days if next_cal else None,
        "calibration_status": cal_status,
        "last_service": last_svc.isoformat() if last_svc else None,
        "next_service_due": next_svc.isoformat() if next_svc else None,
        "service_days_left": (next_svc - today).days if next_svc else None,
        "next_service_hours": next_hours,
        "hours_now": hours_now,
        "service_status": svc_status,
    }


def compute_equipment(record: Dict[str, Any]) -> None:
    _unique("equipment", record, "code", "Equipment code")
    due = equipment_due(record, _list("work_orders"), date.today(), settings())
    record["next_calibration_due"] = due["next_calibration_due"]
    record["next_service_due"] = due["next_service_due"]
    record["next_service_hours"] = due["next_service_hours"]


def _mob_period(mob: Dict[str, Any]) -> Tuple[Optional[date], Optional[date]]:
    start = _d(mob.get("actual_mob_date")) or _d(mob.get("planned_mob_date"))
    end = _d(mob.get("actual_demob_date")) or _d(mob.get("planned_demob_date"))
    return start, end


def equipment_state(eq: Dict[str, Any], mobs: List[Dict[str, Any]], orders: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Effective status. The manual status decides for disposed, broken and in maintenance (and a
    work order in progress means in maintenance); otherwise an active mobilisation (in transit, on
    site, demobilising) that lists the equipment shows it as mobilised at that project's site.
    The manual status is never overwritten; a mismatch is reported as a note."""
    eid = str(eq.get("id") or "")
    manual = str(eq.get("status") or "available")
    active = [m for m in mobs if m.get("status") in ACTIVE_MOB and any(r.get("equipment_id") == eid for r in m.get("equipment") or [])]
    active.sort(key=lambda m: str(m.get("actual_mob_date") or m.get("planned_mob_date") or ""), reverse=True)
    working = [w for w in orders if w.get("equipment_id") == eid and w.get("status") == "in_progress"]
    open_orders = [w for w in orders if w.get("equipment_id") == eid and w.get("status") in OPEN_WO]
    mob = active[0] if active else None
    note = ""
    if manual in ("disposed", "broken", "maintenance"):
        status = manual
        if mob:
            note = "Listed on an active mobilisation"
    elif working:
        status = "maintenance"
    elif mob:
        status = "mobilised"
    else:
        status = manual
        if manual == "mobilised":
            note = "No active mobilisation lists this equipment"
    return {
        "status": status, "manual_status": manual, "note": note,
        "location": (mob.get("to_location") if mob else None) or eq.get("location") or "",
        "project_id": (mob.get("project_id") if mob else None) or eq.get("project_id") or "",
        "mobilisation": {"id": mob["id"], "number": mob.get("number")} if mob else None,
        "open_work_orders": len(open_orders),
    }


def equipment_board(today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Every equipment item with its effective status and due dates (live)."""
    today = today or date.today()
    cfg = settings()
    mobs = _list("mobilisations")
    orders = _list("work_orders")
    out = []
    for eq in sorted(_list("equipment"), key=lambda e: str(e.get("code") or "")):
        row = {"id": eq["id"], "code": eq.get("code"), "name": eq.get("name"), "category": eq.get("category")}
        row.update(equipment_state(eq, mobs, orders))
        row.update(equipment_due(eq, orders, today, cfg))
        out.append(row)
    return out


def maintenance_due(today: Optional[date] = None) -> Dict[str, Any]:
    """Preventive schedule: calibrations and services overdue or due soon, as a result for ResultView,
    plus the raw rows under "items"."""
    today = today or date.today()
    board = [b for b in equipment_board(today) if b["status"] != "disposed"]
    items: List[Dict[str, Any]] = []
    for b in board:
        if b["calibration_status"] in ("overdue", "due_soon", "missing"):
            items.append({"equipment_id": b["id"], "code": b["code"], "name": b["name"], "kind": "calibration",
                          "status": b["calibration_status"], "due": b["next_calibration_due"], "days_left": b["calibration_days_left"],
                          "due_hours": None, "hours_now": None})
        if b["service_status"] in ("overdue", "due_soon", "missing"):
            items.append({"equipment_id": b["id"], "code": b["code"], "name": b["name"], "kind": "service",
                          "status": b["service_status"], "due": b["next_service_due"], "days_left": b["service_days_left"],
                          "due_hours": b["next_service_hours"], "hours_now": b["hours_now"]})
    items.sort(key=lambda i: (-_RANK[i["status"]], i["due"] or "0000"))
    kind_label = {"calibration": "Calibration", "service": "Servicing"}
    status_label = {"overdue": "Overdue", "due_soon": "Due soon", "missing": "No record yet"}
    rows = [[i["code"], i["name"], kind_label[i["kind"]], status_label[i["status"]], i["due"] or "–",
             i["days_left"] if i["days_left"] is not None else None, i["due_hours"], i["hours_now"]] for i in items]
    overdue = sum(1 for i in items if i["status"] in ("overdue", "missing"))
    soon = sum(1 for i in items if i["status"] == "due_soon")
    out = result(
        summary=[("Overdue", overdue, ""), ("Due soon", soon, "")],
        tables=[table("Maintenance and calibration due", ["Code", "Equipment", "Work", "Status", "Due date", "Days left",
                                                          "Due at (h)", "Hour meter (h)"], rows,
                      key=["Code", "Work", "Status", "Due date"])] if rows else [],
        notes=["Due dates come from the interval and the later of the last date on the equipment card and the last completed work order of that type.",
               "A service is also due when the hour meter reaches the last service reading plus the hour interval.",
               "Calibration with no date recorded yet counts as overdue."],
    )
    out["items"] = items
    return out


# --------------------------------------------------------------------------- #
# Maintenance performance: availability, MTBF, MTTR, preventive share, PM compliance
# --------------------------------------------------------------------------- #

SCHEDULED_TYPES = ("preventive", "calibration", "inspection")

MAINTENANCE_NOTES = [
    "Availability (time based, EN 13306): the share of the required time the equipment was able to perform = up time ÷ (up time + down time). Required time = calendar days in the period since the equipment came into service; down time = the downtime of the work orders completed in the period.",
    "MTBF, mean operating time between failures (IEC 60050-192:2015, 192-05-13; EN 13306): up time in the period ÷ number of failures (repair work orders reported in the period). Operating hours are not logged, so up time is counted in calendar days.",
    "MTTR, mean time to restoration (IEC 60050-192:2015, 192-07-23; EN 13306): the average time from the failure (taken as the day the repair was reported, 192-07-06 note 1) until the equipment was restored, over the repairs completed in the period, unless the downtime was entered by hand.",
    "Preventive share: preventive, calibration and inspection work orders (maintenance carried out to a schedule, IEC 60050-192 192-06-05 and 192-06-12) as a share of all work orders completed in the period. SMRP measures planned work in labour hours (metric 5.3.1); labour hours are not recorded here, so work orders are counted.",
    "PM compliance (after SMRP metric 5.4.14 as quoted on the SMRP member forum): a scheduled work order is on time when completed by its planned date plus 20% of the service or calibration interval, at most 28 days; work orders past that window and still open count as late; those still inside it are not counted yet.",
    "Same-day work counts as 0 days of downtime unless the downtime is entered.",
]


def _pm_window_days(eq: Dict[str, Any], wo_type: str) -> float:
    """Tolerance after the planned date: 20% of the interval, at most 28 days (0 when no interval)."""
    if wo_type == "calibration":
        freq = _n(eq.get("calibration_months")) * 365.0 / 12.0
    else:
        freq = _n(eq.get("service_days"))
    return min(0.2 * freq, 28.0) if freq > 0 else 0.0


def equipment_metrics(eq: Dict[str, Any], orders: List[Dict[str, Any]], start: date, end: date, today: date) -> Optional[Dict[str, Any]]:
    """Maintenance performance of one equipment item over [start, end] (both days counted); None
    when it was not in service in the period."""
    since = _d(eq.get("in_service_date"))
    begin = max(start, since) if since else start
    if begin > end:
        return None
    required = float((end - begin).days + 1)
    mine = [w for w in orders if w.get("equipment_id") == eq.get("id") and w.get("status") != "cancelled"]

    def inside(d: Optional[date]) -> bool:
        return bool(d and begin <= d <= end)

    done = [w for w in mine if w.get("status") == "completed" and inside(_d(w.get("completed_date")))]
    downtime = min(required, sum(_n(w.get("downtime")) for w in done))
    up = required - downtime
    failures = [w for w in mine if w.get("type") == "corrective" and inside(_d(w.get("date")))]
    ttr = [_n(w.get("downtime")) for w in done if w.get("type") == "corrective" and _opt(w.get("downtime")) is not None]
    scheduled_done = sum(1 for w in done if w.get("type") in SCHEDULED_TYPES)
    corrective_done = sum(1 for w in done if w.get("type") == "corrective")
    on_time = late = pending = 0
    for w in mine:
        if w.get("type") not in SCHEDULED_TYPES:
            continue
        required_on = _d(w.get("planned_date")) or _d(w.get("date"))
        if not inside(required_on) or required_on is None:
            continue
        deadline = date.fromordinal(required_on.toordinal() + int(_pm_window_days(eq, str(w.get("type")))))
        completed = _d(w.get("completed_date")) if w.get("status") == "completed" else None
        if completed is not None:
            if completed <= deadline:
                on_time += 1
            else:
                late += 1
        elif today > deadline:
            late += 1
        else:
            pending += 1
    return {
        "id": eq.get("id"), "code": eq.get("code"), "name": eq.get("name"),
        "required_days": required, "downtime_days": round(downtime, 2), "up_days": round(up, 2),
        "availability_pct": round(up / required * 100, 1) if required else None,
        "failures": len(failures),
        "mtbf_days": round(up / len(failures), 1) if failures else None,
        "repairs_completed": len(ttr),
        "mttr_days": round(sum(ttr) / len(ttr), 2) if ttr else None,
        "scheduled_done": scheduled_done, "corrective_done": corrective_done,
        "preventive_pct": round(scheduled_done / (scheduled_done + corrective_done) * 100, 1) if (scheduled_done + corrective_done) else None,
        "pm_on_time": on_time, "pm_late": late, "pm_pending": pending,
        "pm_compliance_pct": round(on_time / (on_time + late) * 100, 1) if (on_time + late) else None,
        "_ttr": ttr,
    }


def maintenance_metrics(start: Optional[date] = None, end: Optional[date] = None, today: Optional[date] = None) -> Dict[str, Any]:
    """Availability, MTBF, MTTR, preventive share and PM compliance per equipment item and for the
    whole fleet (equipment not disposed) over a period, default the last 12 months to today."""
    today = today or date.today()
    end = end or today
    start = start or date.fromordinal(add_months(end, -12).toordinal() + 1)
    if start > end:
        raise _error("The period starts after it ends")
    orders = _list("work_orders")
    rows = []
    for eq in sorted(_list("equipment"), key=lambda e: str(e.get("code") or "")):
        if eq.get("status") == "disposed":
            continue
        m = equipment_metrics(eq, orders, start, end, today)
        if m is not None:
            rows.append(m)
    req = sum(r["required_days"] for r in rows)
    up = sum(r["up_days"] for r in rows)
    fails = sum(r["failures"] for r in rows)
    ttr = [x for r in rows for x in r["_ttr"]]
    sched = sum(r["scheduled_done"] for r in rows)
    corr = sum(r["corrective_done"] for r in rows)
    on_time = sum(r["pm_on_time"] for r in rows)
    late = sum(r["pm_late"] for r in rows)
    fleet = {
        "equipment": len(rows), "required_days": req, "up_days": round(up, 2), "downtime_days": round(req - up, 2),
        "availability_pct": round(up / req * 100, 1) if req else None,
        "failures": fails, "mtbf_days": round(up / fails, 1) if fails else None,
        "repairs_completed": len(ttr), "mttr_days": round(sum(ttr) / len(ttr), 2) if ttr else None,
        "scheduled_done": sched, "corrective_done": corr,
        "preventive_pct": round(sched / (sched + corr) * 100, 1) if (sched + corr) else None,
        "pm_on_time": on_time, "pm_late": late, "pm_compliance_pct": round(on_time / (on_time + late) * 100, 1) if (on_time + late) else None,
    }
    for r in rows:
        r.pop("_ttr", None)
    table_rows = [[r["code"], r["name"], r["availability_pct"], r["failures"], r["mtbf_days"], r["mttr_days"], r["preventive_pct"],
                   r["pm_compliance_pct"], r["downtime_days"]] for r in rows]
    out = result(
        summary=[("Availability", fleet["availability_pct"], "%"), ("MTBF", fleet["mtbf_days"], "days"), ("MTTR", fleet["mttr_days"], "days")],
        values=[("Availability", fleet["availability_pct"], "%"), ("MTBF", fleet["mtbf_days"], "days"), ("MTTR", fleet["mttr_days"], "days"),
                ("Failures (repairs reported)", float(fails), ""), ("Preventive share of completed work orders", fleet["preventive_pct"], "%"),
                ("PM compliance", fleet["pm_compliance_pct"], "%"), ("Down time", fleet["downtime_days"], "days")],
        tables=[table("Maintenance performance per equipment", ["Code", "Equipment", "Availability (%)", "Failures", "MTBF (days)",
                                                                 "MTTR (days)", "Preventive share (%)", "PM compliance (%)", "Down time (days)"],
                      table_rows, key=["Code", "Availability (%)", "MTBF (days)", "MTTR (days)"])] if table_rows else [],
        notes=MAINTENANCE_NOTES, method="EN 13306; IEC 60050-192:2015; SMRP Best Practices metrics")
    out["period"] = {"from": start.isoformat(), "to": end.isoformat()}
    out["fleet"] = fleet
    out["equipment"] = rows
    return out


# --------------------------------------------------------------------------- #
# Mobilisation & demobilisation
# --------------------------------------------------------------------------- #

def compute_mobilisation(record: Dict[str, Any]) -> None:
    warnings: List[Dict[str, Any]] = []
    pm, pd = _d(record.get("planned_mob_date")), _d(record.get("planned_demob_date"))
    am, ad = _d(record.get("actual_mob_date")), _d(record.get("actual_demob_date"))
    if pm and pd and pd < pm:
        raise _error("Planned demobilisation is before the planned mobilisation")
    if am and ad and ad < am:
        raise _error("Back at base is before arrived on site")
    status = record.get("status")
    if status in ("on_site", "demobilising", "returned") and not am:
        _warn(warnings, "Enter the date of arrival on site")
    if status == "returned" and not ad:
        _warn(warnings, "Enter the date back at base")
    record["total_cost"] = _money(_n(record.get("mob_cost")) + _n(record.get("demob_cost")) + _n(record.get("other_cost")))
    rows = record.get("equipment") or []
    record["equipment_count"] = float(len(rows))
    record["planned_days"] = float((pd - pm).days + 1) if (pm and pd) else None
    end = ad or (date.today() if am and status in ACTIVE_MOB else None)
    record["actual_days"] = float((end - am).days + 1) if (am and end and end >= am) else None

    equipment = {e["id"]: e for e in _list("equipment")}
    seen: set = set()
    start, finish = _mob_period(record)
    others = [m for m in _list("mobilisations") if m.get("id") != record.get("id") and m.get("status") in BOOKED_MOB]
    for row in rows:
        eid = row.get("equipment_id")
        eq = equipment.get(eid or "")
        if eq is None:
            continue
        label = f"{eq.get('code')} {eq.get('name')}"
        if eid in seen:
            _warn(warnings, "{equipment} is listed twice", equipment=label)
            continue
        seen.add(eid)
        if status in BOOKED_MOB and eq.get("status") == "disposed":
            raise _error("Disposed equipment cannot be mobilised")
        if status in BOOKED_MOB and eq.get("status") in ("broken", "maintenance"):
            _warn(warnings, "{equipment} is marked broken or in maintenance", equipment=label)
        if status not in BOOKED_MOB:
            continue
        for other in others:
            if not any(r.get("equipment_id") == eid for r in other.get("equipment") or []):
                continue
            o_start, o_end = _mob_period(other)
            # Open-ended periods overlap everything after their start.
            overlap = (start is None or o_end is None or start <= o_end) and (o_start is None or finish is None or o_start <= finish)
            if overlap:
                _warn(warnings, "{equipment} is also on mobilisation {number} in the same period", equipment=label,
                      number=other.get("number") or "")
    _set_warnings(record, warnings)


# --------------------------------------------------------------------------- #
# Maintenance work orders
# --------------------------------------------------------------------------- #

def compute_work_order(record: Dict[str, Any]) -> None:
    warnings: List[Dict[str, Any]] = []
    start, done = _d(record.get("start_date")), _d(record.get("completed_date"))
    if record.get("status") == "completed" and not done:
        raise _error("Enter the completion date of a completed work order")
    if start and done and done < start:
        raise _error("Completed on is before work started")
    parts = sum(_n(p.get("qty")) * _n(p.get("unit_cost")) for p in record.get("parts") or [])
    record["parts_cost"] = _money(parts)
    record["total_cost"] = _money(parts + _n(record.get("labour_cost")) + _n(record.get("vendor_cost")))
    manual = _opt(record.get("downtime_days"))
    reported = _d(record.get("date"))
    if manual is not None:
        record["downtime"] = manual
    elif record.get("type") == "corrective" and reported and done and done >= reported:
        # A repair: down from the failure (taken as the day it was reported) until restored
        # (time to restoration, IEC 60050-192:2015 192-07-06 and its note 1).
        record["downtime"] = float((done - reported).days)
    else:
        record["downtime"] = float((done - start).days) if (start and done) else None
    record["next_calibration_due"] = None
    cfg = settings()
    if record["total_cost"] > cfg["wo_approval_limit"] and not record.get("procurement_id") and record.get("status") != "cancelled":
        _warn(warnings, "The cost is above {limit}: raise a purchase request (procurement card) for approval", money=["limit"],
              limit=cfg["wo_approval_limit"])
    if record.get("performed_by") == "vendor" and not record.get("vendor_id"):
        _warn(warnings, "Choose the vendor that does the work")
    if record.get("type") == "calibration" and record.get("status") == "completed":
        if not record.get("certificate_no"):
            _warn(warnings, "Enter the calibration certificate number")
        from . import records

        try:
            eq = records.get_record("equipment", str(record.get("equipment_id") or ""))
        except records.NotFound:
            eq = {}
        if record.get("calibration_result") == "fail":
            _warn(warnings, "Calibration failed: the equipment must not be used until it is repaired and calibrated again")
            if done:
                from . import erp_lab

                affected = erp_lab.tests_since_last_good_calibration(eq, _list("work_orders"), done, record.get("id"))
                if affected["tests"]:
                    _warn(warnings, "{n} laboratory tests used this equipment since its last good calibration ({since}): "
                                    "raise a nonconformity and check their results (ISO/IEC 17025 6.4.9, 7.10)",
                          n=len(affected["tests"]), since=affected["since"] or "–")
        months = int(_n(eq.get("calibration_months")))
        if months and done and record.get("calibration_result") != "fail":
            record["next_calibration_due"] = add_months(done, months).isoformat()
    _set_warnings(record, warnings)


# --------------------------------------------------------------------------- #
# Procurement card and purchase orders
# --------------------------------------------------------------------------- #

def required_quotes(value: float, cfg: Dict[str, float]) -> int:
    if value >= cfg["three_quotes_from"]:
        return 3
    if value >= cfg["two_quotes_from"]:
        return 2
    return 1


def compute_procurement(record: Dict[str, Any]) -> None:
    warnings: List[Dict[str, Any]] = []
    cfg = settings()
    est = sum(_n(i.get("qty")) * _n(i.get("est_price")) for i in record.get("items") or [])
    record["est_total"] = _money(est)
    quotes = [q for q in record.get("quotations") or [] if _opt(q.get("amount")) is not None]
    chosen = [q for q in record.get("quotations") or [] if q.get("chosen")]
    if len(chosen) > 1:
        raise _error("Choose only one quotation")
    for q in record.get("quotations") or []:
        if not q.get("vendor_id") and not q.get("vendor_name"):
            raise _error("Each quotation needs a vendor")
    vendors = {v["id"]: v for v in _list("vendors")} if quotes else {}

    def vendor_of(q: Dict[str, Any]) -> str:
        v = vendors.get(q.get("vendor_id") or "")
        return str(v.get("name")) if v else str(q.get("vendor_name") or "")

    record["quote_count"] = float(len(quotes))
    lowest = min((_n(q.get("amount")) for q in quotes), default=None)
    record["lowest_amount"] = lowest
    pick = chosen[0] if chosen else None
    record["chosen_vendor"] = vendor_of(pick) if pick else ""
    record["chosen_vendor_id"] = (pick.get("vendor_id") or "") if pick else ""
    chosen_amount = _opt(pick.get("amount")) if pick else None
    approved = chosen_amount if chosen_amount is not None else est
    record["approved_amount"] = _money(approved)
    needed = required_quotes(max(est, approved), cfg)
    record["required_quotes"] = float(needed)

    if not record.get("items"):
        _warn(warnings, "List the items requested")
    if len(quotes) < needed and not str(record.get("exception_reason") or "").strip():
        limit = cfg["three_quotes_from"] if needed == 3 else cfg["two_quotes_from"]
        _warn(warnings, "{needed} quotations are needed from {limit}; {got} received. Add quotations or give the reason for fewer.",
              money=["limit"], needed=needed, limit=limit, got=len(quotes))
    if quotes and not pick:
        _warn(warnings, "Mark the chosen quotation")
    if pick and pick.get("vendor_id") and vendors.get(pick["vendor_id"], {}).get("active") is False:
        _warn(warnings, "The chosen vendor is marked inactive")
    standing = vendor_standing(str(pick.get("vendor_id")), _list("vendor_evaluations"), date.today()) \
        if (pick and pick.get("vendor_id")) else None
    record["chosen_vendor_status"] = standing["status"] if standing else ""
    if standing and standing["status"] == "blocked":
        _warn(warnings, "The chosen vendor is blocked after its evaluation on {date} (score {score}%): choose another vendor",
              date=standing["date"] or "", score=standing["score"] if standing["score"] is not None else "–")
    elif standing and standing["status"] == "conditional":
        _warn(warnings, "The chosen vendor is conditional after its evaluation on {date}: check the agreed improvement actions",
              date=standing["date"] or "")
    if standing and standing["reevaluation_overdue"]:
        _warn(warnings, "The chosen vendor's re-evaluation was due on {date}", date=standing["next_due"] or "")
    # Conflict of interest: the people choosing the vendor declare any interest in it.
    if pick and not record.get("coi_status"):
        _warn(warnings, "Record the conflict-of-interest declaration of the people choosing the vendor")
    if record.get("coi_status") == "declared" and not (str(record.get("coi_details") or "").strip()
                                                       and str(record.get("coi_mitigation") or "").strip()):
        _warn(warnings, "Describe the declared conflict of interest and how it is handled")
    if pick and chosen_amount is not None and lowest is not None and chosen_amount > lowest \
            and not str(record.get("selection_reason") or "").strip():
        _warn(warnings, "The chosen quotation is not the lowest; give the reason for the choice")
    budget = _opt(record.get("budget"))
    if budget is not None and approved > budget:
        _warn(warnings, "Above the budget by {over}", money=["over"], over=_money(approved - budget))
    if record.get("cost_centre") == "project" and not record.get("project_id"):
        _warn(warnings, "Choose the project the purchase is charged to")
    _set_warnings(record, warnings)


def _po_lines(record: Dict[str, Any]) -> Tuple[float, int, int]:
    """Received share of the ordered quantity (good receipts only), lines fully received, lines."""
    items = record.get("items") or []
    received: Dict[int, float] = {}
    for r in record.get("receipts") or []:
        if r.get("condition") == "damaged":
            continue
        line = int(_n(r.get("line")))
        received[line] = received.get(line, 0.0) + _n(r.get("qty"))
    ordered_total = sum(_n(i.get("qty")) for i in items)
    got_total = sum(min(received.get(n, 0.0), _n(i.get("qty"))) for n, i in enumerate(items, start=1))
    full = sum(1 for n, i in enumerate(items, start=1) if received.get(n, 0.0) >= _n(i.get("qty")) > 0)
    pct = got_total / ordered_total * 100 if ordered_total else 0.0
    return round(pct, 1), full, len(items)


def po_progress(po: Dict[str, Any]) -> str:
    status = po.get("status") or "draft"
    if status in ("draft", "cancelled", "closed"):
        return status
    if po.get("paid_date"):
        return "paid"
    if po.get("invoice_no") or _opt(po.get("invoice_amount")) is not None:
        return "invoiced"
    pct, full, lines = _po_lines(po)
    if lines and full == lines:
        return "received"
    if pct > 0:
        return "partly_received"
    return "ordered"


def _issued_before(record: Dict[str, Any]) -> bool:
    """The stored version of this purchase order was already issued (receipts and invoices of an
    order issued before its vendor was blocked can still be recorded)."""
    from . import records

    try:
        before = records.get_record("purchase_orders", str(record.get("id") or ""))
    except records.NotFound:
        return False
    return before.get("status") in ("issued", "closed")


def compute_purchase_order(record: Dict[str, Any]) -> None:
    from . import records

    warnings: List[Dict[str, Any]] = []
    items = record.get("items") or []
    for r in record.get("receipts") or []:
        if int(_n(r.get("line"))) > len(items):
            raise _error("A goods receipt refers to a PO item number that does not exist")
    subtotal = sum(_n(i.get("qty")) * _n(i.get("unit_price")) for i in items)
    record["subtotal"] = _money(subtotal)
    record["tax"] = _money(subtotal * _n(record.get("tax_pct")) / 100)
    record["total"] = record["subtotal"] + record["tax"]
    record["received_pct"], _, _ = _po_lines(record)
    try:
        pr = records.get_record("procurements", str(record.get("procurement_id") or ""))
    except records.NotFound:
        pr = {}
    if record.get("status") in ("issued", "closed") and pr.get("wf_status") != "approved":
        raise _error("The procurement card must be approved before the purchase order is issued")
    if pr.get("cancelled") and record.get("status") != "cancelled":
        _warn(warnings, "The procurement card is cancelled")
    if pr.get("chosen_vendor_id") and record.get("vendor_id") and pr["chosen_vendor_id"] != record["vendor_id"]:
        _warn(warnings, "The vendor differs from the chosen quotation")
    standing = vendor_standing(str(record.get("vendor_id") or ""), _list("vendor_evaluations"), date.today())
    if standing["status"] == "blocked" and record.get("status") != "cancelled":
        if record.get("status") in ("issued", "closed") and not _issued_before(record):
            raise _error("This vendor is blocked after its last evaluation; a purchase order cannot be issued to it")
        _warn(warnings, "This vendor is blocked after its evaluation on {date}", date=standing["date"] or "")
    elif standing["status"] == "conditional" and record.get("status") != "cancelled":
        _warn(warnings, "This vendor is conditional after its evaluation on {date}: check the agreed improvement actions",
              date=standing["date"] or "")
    # Segregation of duties: the person who approved the request does not also raise the order.
    approver = next((str(h.get("by") or "").lower() for h in reversed(pr.get("wf_history") or []) if h.get("action") == "approve"), "")
    if approver and approver == str(record.get("created_by") or "").lower():
        _warn(warnings, "The person who approved the procurement card also raised this purchase order: "
                        "have another person raise or check it (segregation of duties)")
    if pr and record.get("status") != "cancelled":
        ordered = record["total"] + sum(_n(p.get("total")) for p in _list("purchase_orders")
                                        if p.get("procurement_id") == pr.get("id") and p.get("id") != record.get("id")
                                        and p.get("status") != "cancelled")
        approved = _n(pr.get("approved_amount"))
        if ordered > approved + 0.5:
            _warn(warnings, "Purchase orders exceed the approved amount by {over}", money=["over"], over=_money(ordered - approved))
    invoice = _opt(record.get("invoice_amount"))
    if invoice is not None and abs(invoice - record["total"]) > 0.5:
        _warn(warnings, "The invoice amount differs from the PO total by {diff}", money=["diff"], diff=_money(invoice - record["total"]))
    if (invoice is not None or record.get("invoice_no")) and record["received_pct"] < 100:
        _warn(warnings, "Invoice entered before all goods were received")
    if record.get("paid_date") and invoice is None:
        _warn(warnings, "Enter the invoice before marking it paid")
    record["progress"] = po_progress(record)
    _set_warnings(record, warnings)


PROCUREMENT_STAGES = ("request", "approval", "approved", "ordered", "partly_received", "received", "invoiced", "paid", "cancelled")


def procurement_status(pr: Dict[str, Any], pos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Where a procurement card stands across its purchase orders (live)."""
    mine = [p for p in pos if p.get("procurement_id") == pr.get("id") and p.get("status") != "cancelled"]
    issued = [p for p in mine if p.get("status") != "draft"]
    progress = [po_progress(p) for p in issued]
    wf = pr.get("wf_status") or "draft"
    if pr.get("cancelled"):
        stage = "cancelled"
    elif wf in ("draft", "returned"):
        stage = "request"
    elif wf in ("submitted", "reviewed"):
        stage = "approval"
    elif not issued:
        stage = "approved"
    elif all(p in ("paid", "closed") for p in progress):
        stage = "paid"
    elif all(p in ("invoiced", "paid", "closed") for p in progress):
        stage = "invoiced"
    elif all(p in ("received", "invoiced", "paid", "closed") for p in progress):
        stage = "received"
    elif any(p != "ordered" for p in progress):
        stage = "partly_received"
    else:
        stage = "ordered"
    return {
        "id": pr.get("id"), "number": pr.get("number"), "title": pr.get("title"), "stage": stage, "wf_status": wf,
        "approved_amount": _n(pr.get("approved_amount")),
        "ordered": _money(sum(_n(p.get("total")) for p in issued)),
        "invoiced": _money(sum(_n(p.get("invoice_amount")) for p in issued)),
        "paid": _money(sum(_n(p.get("invoice_amount")) for p in issued if p.get("paid_date"))),
        "orders": [{"id": p["id"], "number": p.get("number"), "progress": po_progress(p), "total": _n(p.get("total"))} for p in mine],
        "warning_count": int(_n(pr.get("warning_count"))),
    }


# --------------------------------------------------------------------------- #
# Fixed assets: depreciation
# --------------------------------------------------------------------------- #

# PMK 72 Tahun 2023 Pasal 2 ayat (3) / UU PPh Pasal 11 ayat (6): (useful life in years,
# straight-line rate %, declining-balance rate % or None for buildings).
TAX_TABLE: Dict[str, Tuple[float, float, Optional[float]]] = {
    "g1": (4, 25.0, 50.0),
    "g2": (8, 12.5, 25.0),
    "g3": (16, 6.25, 12.5),
    "g4": (20, 5.0, 10.0),
    "building_permanent": (20, 5.0, None),
    "building_nonpermanent": (10, 10.0, None),
    "none": (0, 0.0, None),
}

# Suggested tax group per asset category (reading of the PMK 72/2023 annex; the company's tax
# adviser confirms the group of each asset). Shown in the form, never applied silently.
SUGGESTED_GROUP: Dict[str, str] = {
    "land": "none", "building_permanent": "building_permanent", "building_nonpermanent": "building_nonpermanent",
    "drilling": "g2", "instruments": "g1", "lab": "g1", "vehicle": "g2", "office_it": "g1", "furniture": "g1", "other": "g3",
}


def _months_through(start: date, end: date) -> int:
    """Months from the start month to the end month, both counted in full."""
    return (end.year - start.year) * 12 + end.month - start.month + 1


def depreciation_rows(cost: float, start: date, life_years: float, method: str, rate_pct: float,
                      residual: float = 0.0, stop: Optional[date] = None) -> List[Dict[str, Any]]:
    """Yearly schedule (calendar years). Full-month convention: the month of acquisition and the
    month of disposal count in full. Straight line spreads cost − residual evenly over the months
    of the useful life; declining balance applies the rate to the opening book value (pro rata for
    a part year) and depreciates what is left down to the residual in the year the life ends."""
    if cost <= 0 or life_years <= 0 or method == "none":
        return []
    residual = min(max(residual, 0.0), cost)
    life = max(1, round(life_years * 12))
    total = life if stop is None else max(0, min(life, _months_through(start, stop)))
    monthly = (cost - residual) / life
    rows: List[Dict[str, Any]] = []
    nbv, used, year = cost, 0, start.year
    while used < total:
        available = 12 - start.month + 1 if year == start.year else 12
        months = min(available, total - used)
        ends_here = used + months >= life
        if ends_here:
            dep = nbv - residual
        elif method == "straight_line":
            dep = _money(monthly * months)
        else:
            dep = min(_money(nbv * rate_pct / 100 * months / 12), nbv - residual)
        dep = max(0.0, dep)
        opening = nbv
        nbv -= dep
        used += months
        rows.append({"year": year, "months": months, "opening": opening, "dep": dep, "accumulated": cost - nbv, "closing": nbv})
        year += 1
    return rows


def accumulated_at(rows: List[Dict[str, Any]], start: date, when: date) -> float:
    """Accumulated depreciation through the month of ``when`` (that month counted in full)."""
    acc = 0.0
    for r in rows:
        if r["year"] < when.year:
            acc += r["dep"]
        elif r["year"] == when.year:
            first = start.month if r["year"] == start.year else 1
            elapsed = max(0, min(r["months"], when.month - first + 1))
            acc += r["dep"] * elapsed / r["months"] if r["months"] else 0.0
    return _money(acc)


ASSET_NOTES = [
    "Tax depreciation follows PMK 72 Tahun 2023 Pasal 2 (UU PPh Pasal 11 as amended by UU HPP): non-building groups 1–4 have useful lives of 4, 8, 16 and 20 years, straight-line rates of 25%, 12.5%, 6.25% and 5%, or declining-balance rates of 50%, 25%, 12.5% and 10%.",
    "Permanent buildings: 20 years, 5% a year; non-permanent buildings: 10 years, 10% a year; buildings use the straight-line method only.",
    "Depreciation starts in the month the cost is incurred (PMK 72/2023 Pasal 5); that month counts in full, so an asset acquired in October has 3 months in its first year.",
    "Declining balance: the rate applies to the remaining book value, pro rata for a part year; at the end of the useful life the remaining book value is depreciated at once (PMK 72/2023 Pasal 2 ayat 2).",
    "Tax depreciation has no residual value: the asset is depreciated to zero. Years are calendar years.",
    "Book depreciation follows PSAK 216 Aset Tetap (formerly PSAK 16): cost less residual value over the useful life, from when the asset is available for use; the same full-month convention keeps the book and tax schedules comparable.",
    "Double declining balance uses twice the straight-line rate (2 ÷ useful life) and stops at the residual value.",
    "On disposal, depreciation runs to the end of the month of disposal; the gain or loss is the proceeds less the book value at that date (for tax, PMK 72/2023 Pasal 8: the tax book value is a loss and the proceeds are income).",
    "Land is not depreciated.",
    "Impairment (PSAK 236 Penurunan Nilai Aset, formerly PSAK 48; IAS 36 paragraphs 9 and 12): at each reporting date check for signs that the asset may be impaired, such as physical damage or obsolescence, the asset becoming idle, worse economic performance than expected, a decline in its value, or adverse changes in technology, market or law. When there is a sign, estimate the recoverable amount.",
    "When a recoverable amount below the book value is entered, the difference is shown as an indicated impairment loss. It is not deducted in the schedules above: the accountant books it and adjusts the later depreciation.",
]

IMPAIRMENT_INDICATORS = [
    ("value_decline", "Market value fell clearly more than expected"),
    ("adverse_change", "Adverse change in technology, market, economy or law"),
    ("interest_rates", "Higher market interest rates or required returns"),
    ("damage_obsolete", "Physical damage or obsolescence"),
    ("idle_or_disposal", "Idle, restructured or to be disposed of early"),
    ("poor_performance", "Economic performance worse than expected"),
]


def impairment_indicated(record: Dict[str, Any], book_value: float, disposed: bool) -> Optional[float]:
    """Book value less the recoverable amount entered, when positive (information for the accountant)."""
    recoverable = _opt(record.get("recoverable_amount"))
    if disposed or recoverable is None:
        return None
    return _money(max(0.0, book_value - recoverable))


def asset_figures(record: Dict[str, Any], as_of: Optional[date] = None) -> Dict[str, Any]:
    """Tax and book schedules and the values as of a date (default today, or the disposal date)."""
    start = _d(record.get("acquisition_date"))
    cost = _n(record.get("cost"))
    group = str(record.get("tax_group") or "none")
    life_tax, sl_rate, db_rate = TAX_TABLE.get(group, TAX_TABLE["none"])
    tax_method = str(record.get("tax_method") or "straight_line")
    if tax_method == "declining" and db_rate is None:
        tax_method = "straight_line"
    tax_rate = db_rate if (tax_method == "declining" and db_rate is not None) else sl_rate
    book_method = str(record.get("book_method") or "same_as_tax")
    residual = _n(record.get("residual_value"))
    book_life = _opt(record.get("book_life_years")) or life_tax
    if book_method == "same_as_tax":
        b_method, b_life, b_rate, b_residual = (tax_method if life_tax else "none"), life_tax, tax_rate, 0.0
    elif book_method == "declining":
        b_method, b_life, b_rate, b_residual = "declining", book_life, (200.0 / book_life if book_life else 0.0), residual
    elif book_method == "straight_line":
        b_method, b_life, b_rate, b_residual = "straight_line", book_life, (100.0 / book_life if book_life else 0.0), residual
    else:
        b_method, b_life, b_rate, b_residual = "none", 0.0, 0.0, 0.0
    disposal = _d(record.get("disposal_date"))
    today = date.today()
    when = as_of or today
    disposed = bool(disposal and disposal <= when)
    if disposed and disposal:
        when = disposal
    stop = disposal
    tax_rows = depreciation_rows(cost, start, life_tax, tax_method if life_tax else "none", tax_rate, 0.0, stop) if start else []
    book_rows = depreciation_rows(cost, start, b_life, b_method, b_rate, b_residual, stop) if start else []
    acc_tax = accumulated_at(tax_rows, start, when) if start else 0.0
    acc_book = accumulated_at(book_rows, start, when) if start else 0.0
    year_of = lambda rows: next((r["dep"] for r in rows if r["year"] == when.year), 0.0)  # noqa: E731
    out: Dict[str, Any] = {
        "as_of": when.isoformat(), "tax_life": life_tax, "tax_rate": tax_rate, "tax_method": tax_method,
        "book_life": b_life, "book_rate": round(b_rate, 4), "book_method": b_method, "residual": b_residual,
        "tax_rows": tax_rows, "book_rows": book_rows,
        "accumulated_tax": acc_tax, "tax_value": _money(cost - acc_tax),
        "accumulated_book": acc_book, "book_value": _money(cost - acc_book),
        "dep_year_tax": year_of(tax_rows), "dep_year_book": year_of(book_rows),
        "disposed": disposed, "gain_loss_book": None, "gain_loss_tax": None,
    }
    if disposed:
        proceeds = _n(record.get("disposal_proceeds"))
        out["gain_loss_book"] = _money(proceeds - out["book_value"])
        out["gain_loss_tax"] = _money(proceeds - out["tax_value"])
    if disposed:
        out["status"] = "disposed"
    elif b_method == "none" and not tax_rows:
        out["status"] = "not_depreciated"
    elif book_rows and acc_book >= cost - b_residual - 0.5:
        out["status"] = "fully_depreciated"
    else:
        out["status"] = "active"
    return out


def asset_schedule_result(record: Dict[str, Any], as_of: Optional[date] = None) -> Dict[str, Any]:
    """The depreciation schedules in the worksheet result format."""
    fig = asset_figures(record, as_of)
    cost = _n(record.get("cost"))

    def rows_of(rows: List[Dict[str, Any]]) -> List[List[Any]]:
        return [[str(r["year"]), float(r["months"]), _money(r["opening"]), _money(r["dep"]), _money(r["accumulated"]), _money(r["closing"])]
                for r in rows]

    cols = ["Year", "Months", "Opening book value (IDR)", "Depreciation (IDR)", "Accumulated (IDR)", "Closing book value (IDR)"]
    key = ["Year", "Depreciation (IDR)", "Closing book value (IDR)"]
    tables = []
    if fig["book_rows"]:
        tables.append(table("Book depreciation schedule (PSAK 216)", cols, rows_of(fig["book_rows"]), key=key))
    if fig["tax_rows"]:
        tables.append(table("Tax depreciation schedule (PMK 72/2023)", cols, rows_of(fig["tax_rows"]), key=key))
    values = [
        ("Acquisition cost", _money(cost), "IDR"),
        ("Accumulated depreciation (books)", fig["accumulated_book"], "IDR"),
        ("Book value", fig["book_value"], "IDR"),
        ("Depreciation this year (books)", fig["dep_year_book"], "IDR"),
        ("Accumulated depreciation (tax)", fig["accumulated_tax"], "IDR"),
        ("Tax book value", fig["tax_value"], "IDR"),
        ("Depreciation this year (tax)", fig["dep_year_tax"], "IDR"),
    ]
    if fig["disposed"]:
        values += [("Proceeds", _money(_n(record.get("disposal_proceeds"))), "IDR"),
                   ("Gain / loss on disposal (books)", fig["gain_loss_book"], "IDR"),
                   ("Gain / loss on disposal (tax)", fig["gain_loss_tax"], "IDR")]
    loss = impairment_indicated(record, fig["book_value"], fig["disposed"])
    if loss:
        values.append(("Impairment loss indicated (not in the schedule)", loss, "IDR"))
    summary = [("Tax useful life", fig["tax_life"] or None, "years"), ("Tax rate", fig["tax_rate"] or None, "%/year"),
               ("Book useful life", fig["book_life"] or None, "years")]
    out = result(summary=summary, values=values, tables=tables, notes=ASSET_NOTES,
                 method="PMK 72 Tahun 2023; PSAK 216")
    return out


def compute_fixed_asset(record: Dict[str, Any]) -> None:
    _unique("fixed_assets", record, "code", "Asset code")
    group = str(record.get("tax_group") or "")
    if record.get("tax_method") == "declining" and group.startswith("building"):
        raise _error("Buildings are depreciated with the straight-line method only")
    acquired, disposed = _d(record.get("acquisition_date")), _d(record.get("disposal_date"))
    if acquired and disposed and disposed < acquired:
        raise _error("Disposed on is before acquired on")
    if _n(record.get("residual_value")) > _n(record.get("cost")):
        raise _error("The residual value cannot be more than the cost")
    if disposed and not record.get("disposal_type"):
        raise _error("Choose how the asset was disposed of")
    fig = asset_figures(record)
    record["tax_life_years"] = fig["tax_life"] or None
    record["tax_rate_pct"] = fig["tax_rate"] or None
    record["book_life"] = fig["book_life"] or None
    for key in ("dep_year_book", "accumulated_book", "book_value", "dep_year_tax", "accumulated_tax", "tax_value",
                "gain_loss_book", "gain_loss_tax", "as_of"):
        record[key] = fig[key]
    record["asset_status"] = fig["status"]
    record["impairment_loss"] = impairment_indicated(record, fig["book_value"], fig["disposed"])
    record["schedule"] = asset_schedule_result(record)


# --------------------------------------------------------------------------- #
# Individual work plan & performance card
# --------------------------------------------------------------------------- #

# Behaviour score 1–5 as a percentage on the same scale as KPI achievement (3 = meets = 100%).
COMPETENCY_PCT = {1: 60.0, 2: 80.0, 3: 100.0, 4: 110.0, 5: 120.0}

# Rating bands on the final score; the limits sit halfway between the behaviour score steps.
RATING_BANDS: List[Tuple[float, str]] = [(115.0, "outstanding"), (105.0, "very_good"), (90.0, "good"), (70.0, "needs_improvement"),
                                         (float("-inf"), "unsatisfactory")]
RATING_LABEL = {"outstanding": "Exceptional", "very_good": "Very good", "good": "Good",
                "needs_improvement": "Needs improvement", "unsatisfactory": "Unsatisfactory"}
PERSPECTIVE_LABEL = {"financial": "Financial", "customer": "Customer", "internal": "Internal process", "learning": "Learning & growth"}


def kpi_achievement(target: float, actual: float, polarity: str, cap: float) -> float:
    """Achievement in %: actual ÷ target when higher is better; (2 − actual ÷ target) when lower is
    better (floored at 0). A zero target works only when lower is better (e.g. zero accidents):
    100% when the actual is zero or less, else 0%. Capped at ``cap``."""
    if polarity == "lower":
        if target == 0:
            pct = 100.0 if actual <= 0 else 0.0
        else:
            pct = max(0.0, (2 - actual / target) * 100)
    else:
        if target == 0:
            raise _error("A KPI with target 0 must be lower is better")
        pct = max(0.0, actual / target * 100)
    return min(pct, cap)


def rating_for(score: float) -> str:
    for limit, name in RATING_BANDS:
        if score >= limit:
            return name
    return "unsatisfactory"


def _period_label(record: Dict[str, Any]) -> str:
    start = _d(record.get("period_start"))
    if not start:
        return ""
    kind = record.get("period_type")
    if kind == "semester":
        return f"{start.year} S{1 if start.month <= 6 else 2}"
    if kind == "quarter":
        return f"{start.year} Q{(start.month - 1) // 3 + 1}"
    return str(start.year)


def compute_performance(record: Dict[str, Any]) -> None:
    ps, pe = _d(record.get("period_start")), _d(record.get("period_end"))
    if ps and pe and pe < ps:
        raise _error("Period to is before period from")
    record["title"] = f"{record.get('employee_name') or record.get('employee') or ''} – {_period_label(record)}".strip(" –")
    cap = _opt(record.get("cap_pct")) or 120.0
    kpis = record.get("kpis") or []
    comps = record.get("competencies") or []
    kw = round(sum(_n(k.get("weight")) for k in kpis), 4)
    cw = round(sum(_n(c.get("weight")) for c in comps), 4)
    record["kpi_weight_total"] = kw
    record["competency_weight_total"] = cw
    if kpis and abs(kw - 100) > 0.01:
        raise _error("KPI weights must add up to 100%")
    if comps and abs(cw - 100) > 0.01:
        raise _error("Competency weights must add up to 100%")

    kpi_rows: List[List[Any]] = []
    kpi_score = 0.0
    kpi_done = True
    by_perspective: Dict[str, List[float]] = {}
    for k in kpis:
        actual = _opt(k.get("actual"))
        weight = _n(k.get("weight"))
        persp = str(k.get("perspective") or "")
        agg = by_perspective.setdefault(persp, [0.0, 0.0])
        agg[0] += weight
        if actual is None:
            kpi_done = False
            ach: Optional[float] = None
            weighted: Optional[float] = None
        else:
            ach = kpi_achievement(_n(k.get("target")), actual, str(k.get("polarity") or "higher"), cap)
            weighted = ach * weight / 100
            kpi_score += weighted
            agg[1] += weighted
        kpi_rows.append([PERSPECTIVE_LABEL.get(persp, persp), k.get("kpi"), k.get("unit") or "", _opt(k.get("target")), actual,
                         "Higher is better" if k.get("polarity") != "lower" else "Lower is better", weight,
                         round(ach, 1) if ach is not None else None, round(weighted, 2) if weighted is not None else None])

    comp_rows: List[List[Any]] = []
    comp_score = 0.0
    comp_done = True
    for c in comps:
        score = int(_n(c.get("score"))) if c.get("score") else 0
        weight = _n(c.get("weight"))
        if score not in COMPETENCY_PCT:
            comp_done = False
            pct: Optional[float] = None
            weighted = None
        else:
            pct = min(COMPETENCY_PCT[score], cap)
            weighted = pct * weight / 100
            comp_score += weighted
        comp_rows.append([c.get("competency"), weight, float(score) if score else None, pct,
                          round(weighted, 2) if weighted is not None else None])

    share = _opt(record.get("kpi_share_pct"))
    share = 70.0 if share is None else share
    if not comps:
        share = 100.0
    elif not kpis:
        share = 0.0
    complete = bool(kpis or comps) and kpi_done and comp_done
    record["kpi_score"] = round(kpi_score, 2) if (kpis and kpi_done) else None
    record["competency_score"] = round(comp_score, 2) if (comps and comp_done) else None
    final = round(kpi_score * share / 100 + comp_score * (100 - share) / 100, 2) if complete else None
    record["final_score"] = final
    record["rating"] = rating_for(final) if final is not None else ""

    filled_kpi = sum(1 for k in kpis if _opt(k.get("actual")) is not None)
    filled_comp = sum(1 for c in comps if c.get("score"))
    tables = []
    if kpi_rows:
        tables.append(table("KPIs", ["Perspective", "KPI", "Unit", "Target", "Actual", "Polarity", "Weight (%)", "Achievement (%)", "Weighted score"],
                            kpi_rows, key=["KPI", "Weight (%)", "Achievement (%)", "Weighted score"]))
        tables.append(table("Balanced scorecard perspectives", ["Perspective", "Weight (%)", "Weighted score"],
                            [[PERSPECTIVE_LABEL.get(p, p), round(v[0], 2), round(v[1], 2)] for p, v in by_perspective.items()]))
    if comp_rows:
        tables.append(table("Behaviour & competencies", ["Competency / behaviour", "Weight (%)", "Score (1–5)", "Score (%)", "Weighted score"],
                            comp_rows, key=["Competency / behaviour", "Score (1–5)", "Weighted score"]))
    summary: List[Tuple[str, Any, str]] = [("Final score", final, "%")] if final is not None else []
    summary += [("KPI score", record["kpi_score"], "%"), ("Competency score", record["competency_score"], "%")]
    values: List[Tuple[str, Any, str]] = [
        ("Rating", RATING_LABEL.get(record["rating"], "") or None, ""),
        ("KPIs with an actual", f"{filled_kpi}/{len(kpis)}", ""),
        ("Competencies scored", f"{filled_comp}/{len(comps)}", ""),
        ("Share of KPIs in the final score (%)", share, ""),
        ("Achievement cap per KPI (%)", cap, ""),
    ]
    record["scorecard"] = result(summary=summary, values=values, tables=tables, notes=[
        "Achievement when higher is better = actual ÷ target × 100%; when lower is better = (2 − actual ÷ target) × 100%, not below 0%.",
        "A KPI with target 0 must be lower is better: 100% when the actual is 0, otherwise 0%.",
        "Each KPI's achievement is capped (120% unless set otherwise); weighted score = achievement × weight.",
        "Behaviour scores: 1 = 60%, 2 = 80%, 3 (meets expectations) = 100%, 4 = 110%, 5 = 120%.",
        "Final score = KPI score × KPI share + competency score × (100% − KPI share).",
        "Rating: 115% and above Exceptional; 105–115% Very good; 90–105% Good; 70–90% Needs improvement; below 70% Unsatisfactory.",
        "The final score and rating appear once every KPI has an actual and every competency a score.",
    ], method="Balanced scorecard KPIs and behavioural competencies")


# --------------------------------------------------------------------------- #
# Overview for the management dashboard
# --------------------------------------------------------------------------- #

def overview(role: str, email: str, today: Optional[date] = None) -> Dict[str, Any]:
    """Operations figures for the management dashboard, built from the records this user may see.
    A section is None when the role cannot read its records."""
    from . import records
    from .entities import ENTITIES

    today = today or date.today()

    def visible(name: str) -> Optional[List[Dict[str, Any]]]:
        entity = ENTITIES[name]
        if not records.can_read(entity, role):
            return None
        return [r for r in records.list_records(name) if records.can_see(entity, role, r, email)]

    out: Dict[str, Any] = {"as_of": today.isoformat()}

    equipment = visible("equipment")
    if equipment is None:
        out["equipment"] = None
        out["maintenance"] = None
    else:
        board = equipment_board(today)
        by_status: Dict[str, int] = {}
        for b in board:
            by_status[b["status"]] = by_status.get(b["status"], 0) + 1
        live = [b for b in board if b["status"] != "disposed"]
        out["equipment"] = {
            "total": len(board), "by_status": by_status,
            "utilisation_pct": round(by_status.get("mobilised", 0) / len(live) * 100, 1) if live else None,
        }
        orders = visible("work_orders") or []
        open_orders = [w for w in orders if w.get("status") in OPEN_WO]
        year = str(today.year)
        done_this_year = [w for w in orders if w.get("status") == "completed" and str(w.get("completed_date") or "").startswith(year)]
        out["maintenance"] = {
            "calibration_overdue": sum(1 for b in live if b["calibration_status"] in ("overdue", "missing")),
            "calibration_due_soon": sum(1 for b in live if b["calibration_status"] == "due_soon"),
            "service_overdue": sum(1 for b in live if b["service_status"] in ("overdue", "missing")),
            "service_due_soon": sum(1 for b in live if b["service_status"] == "due_soon"),
            "open_work_orders": len(open_orders),
            "open_by_type": {k: sum(1 for w in open_orders if w.get("type") == k) for k in ("preventive", "corrective", "calibration", "inspection")},
            "urgent_open": sum(1 for w in open_orders if w.get("priority") == "urgent"),
            "downtime_days_year": round(sum(_n(w.get("downtime")) for w in done_this_year), 1),
            "cost_year": _money(sum(_n(w.get("total_cost")) for w in done_this_year)),
        }
        fleet = maintenance_metrics(today=today)["fleet"]
        out["maintenance"]["last_12_months"] = {k: fleet[k] for k in (
            "availability_pct", "mtbf_days", "mttr_days", "failures", "preventive_pct", "pm_compliance_pct", "pm_late")}

    prs = visible("procurements")
    if prs is None:
        out["procurement"] = None
    else:
        pos = visible("purchase_orders")
        stages = [procurement_status(p, pos or []) for p in prs]
        by_stage: Dict[str, int] = {}
        for s in stages:
            by_stage[s["stage"]] = by_stage.get(s["stage"], 0) + 1
        year = str(today.year)
        year_pos = [p for p in (pos or []) if p.get("status") in ("issued", "closed") and str(p.get("date") or "").startswith(year)]
        out["procurement"] = {
            "by_stage": by_stage,
            "in_progress": sum(1 for s in stages if s["stage"] not in ("paid", "cancelled")),
            "waiting_approval": by_stage.get("approval", 0),
            "approval_value": _money(sum(s["approved_amount"] for s in stages if s["stage"] == "approval")),
            "spend_year": _money(sum(_n(p.get("total")) for p in year_pos)) if pos is not None else None,
            "unpaid_invoices": _money(sum(_n(p.get("invoice_amount")) for p in (pos or []) if p.get("invoice_amount") and not p.get("paid_date")
                                          and p.get("status") != "cancelled")) if pos is not None else None,
        }
        board = [v for v in vendor_board(today) if v["active"]]
        out["procurement"]["vendors"] = {
            "active": len(board),
            **{s: sum(1 for v in board if v["status"] == s) for s in ("approved", "conditional", "blocked", "not_evaluated")},
            "reevaluation_due": sum(1 for v in board if v["reevaluation_overdue"]),
        }

    assets = visible("fixed_assets")
    if assets is None:
        out["assets"] = None
    else:
        figs = [(a, asset_figures(a, today)) for a in assets]
        held = [(a, f) for a, f in figs if not f["disposed"]]
        by_cat: Dict[str, Dict[str, float]] = {}
        for a, f in held:
            cat = by_cat.setdefault(str(a.get("category") or "other"), {"count": 0, "cost": 0.0, "book_value": 0.0})
            cat["count"] += 1
            cat["cost"] += _n(a.get("cost"))
            cat["book_value"] += f["book_value"]
        out["assets"] = {
            "count": len(held),
            "cost": _money(sum(_n(a.get("cost")) for a, _ in held)),
            "accumulated_book": _money(sum(f["accumulated_book"] for _, f in held)),
            "book_value": _money(sum(f["book_value"] for _, f in held)),
            "tax_value": _money(sum(f["tax_value"] for _, f in held)),
            "depreciation_year_book": _money(sum(f["dep_year_book"] for _, f in held)),
            "fully_depreciated": sum(1 for _, f in held if f["status"] == "fully_depreciated"),
            "impairment_indicated": sum(1 for a, _ in held if a.get("impairment_indicators")),
            "by_category": {k: {"count": v["count"], "cost": _money(v["cost"]), "book_value": _money(v["book_value"])} for k, v in by_cat.items()},
        }

    cards = visible("performance_cards")
    if cards is None:
        out["performance"] = None
    else:
        by_state: Dict[str, int] = {}
        by_rating: Dict[str, int] = {}
        for c in cards:
            st = str(c.get("wf_status") or "draft")
            by_state[st] = by_state.get(st, 0) + 1
            if c.get("rating"):
                by_rating[str(c["rating"])] = by_rating.get(str(c["rating"]), 0) + 1
        scored = [_n(c.get("final_score")) for c in cards if c.get("final_score") is not None]
        approved_scored = [_n(c.get("final_score")) for c in cards if c.get("final_score") is not None and c.get("wf_status") == "approved"]
        out["performance"] = {
            "cards": len(cards), "by_state": by_state, "by_rating": by_rating,
            "average_score": round(sum(scored) / len(scored), 1) if scored else None,
            "average_score_approved": round(sum(approved_scored) / len(approved_scored), 1) if approved_scored else None,
        }

    from . import erp_lab

    tests = visible("lab_tests")
    out["laboratory"] = None if tests is None else erp_lab.lab_overview(tests, visible("nonconformities") or [],
                                                                        visible("sample_receipts") or [], today)
    return out
