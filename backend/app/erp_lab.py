"""Laboratory quality controls after ISO/IEC 17025:2017 (adopted identically as SNI ISO/IEC
17025:2017, the standard KAN accredits testing laboratories against):

* sample receipt (7.4): unambiguous identification, condition on arrival and deviations, the
  customer consulted when an item is doubtful, storage, chain of custody, retention and disposal;
* review and authorisation of results before release (7.8.1.1) with the date and the person
  responsible (7.5.1); results changed after authorisation have to be authorised again (7.5.2);
* metrological traceability through calibrated equipment (6.4, 6.5): the equipment used must have
  been in calibration on the test date; equipment that failed calibration is out of service (6.4.9);
* nonconforming work and corrective action (7.10, 8.7).

The ``compute_*`` functions are COMPUTE_HOOKS (see entities_lab.py); the live views are used by
routers/erp_ops.py. Warnings use the same {"text", "vars", "money"} shape as erp_ops.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .erp_ops import (_conflict, _d, _error, _list, _n, _set_warnings, _warn, add_months, lab_authorisation_mode, role_of,
                      separation_on)

AUTHORISERS = ("admin", "manager", "lab")
CLOSERS = ("admin", "manager")

# A change to any of these after authorisation means the result has to be reviewed again.
REVIEWED_FIELDS = ("test_type", "raw", "borehole_id", "sample_ref", "depth_top", "depth_base")


def _blank(value: Any) -> bool:
    """None, empty text, an unticked box, or a list or dict holding only blanks (a worksheet with nothing filled in)."""
    if isinstance(value, dict):
        return all(_blank(v) for v in value.values())
    if isinstance(value, list):
        return all(_blank(v) for v in value)
    return value is None or value == "" or value is False


def _strip(value: Any) -> Any:
    """The value without its blank entries, so {} and {"a": None} compare equal."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if not _blank(v)}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _same(a: Any, b: Any) -> bool:
    if _blank(a) and _blank(b):
        return True
    return bool(_strip(a) == _strip(b))


def _previous(entity: str, record: Dict[str, Any]) -> Dict[str, Any]:
    from . import records

    try:
        return records.get_record(entity, str(record.get("id") or ""))
    except records.NotFound:
        return {}


def _key(value: Any) -> str:
    return str(value or "").strip().lower()


# --------------------------------------------------------------------------- #
# Calibration status of equipment on a date (ISO/IEC 17025 6.4.6–6.4.9, 6.4.13 e)
# --------------------------------------------------------------------------- #

def calibration_on(eq: Dict[str, Any], orders: List[Dict[str, Any]], when: date) -> Dict[str, Any]:
    """Calibration status of one equipment item on a date, from the last calibration on the
    equipment card and the completed calibration work orders up to that date:
    not_required (no interval), not_calibrated (none on record), failed (the latest calibration
    failed: out of service), overdue (the interval had run out) or ok."""
    months = int(_n(eq.get("calibration_months")))
    out: Dict[str, Any] = {"equipment_id": eq.get("id"), "code": eq.get("code"), "name": eq.get("name"),
                           "status": "not_required", "last": None, "due": None}
    if not months:
        return out
    events = []  # (date, passed)
    card = _d(eq.get("last_calibration"))
    if card and card <= when:
        events.append((card, True))
    for wo in orders:
        if wo.get("equipment_id") != eq.get("id") or wo.get("type") != "calibration" or wo.get("status") != "completed":
            continue
        done = _d(wo.get("completed_date"))
        if done and done <= when:
            events.append((done, wo.get("calibration_result") != "fail"))
    if not events:
        out["status"] = "not_calibrated"
        return out
    events.sort()  # a pass on the same day as a fail (adjusted, then passed) comes last
    last, passed = events[-1]
    out["last"] = last.isoformat()
    if not passed:
        out["status"] = "failed"
        return out
    due = add_months(last, months)
    out["due"] = due.isoformat()
    out["status"] = "overdue" if when > due else "ok"
    return out


def _test_date(test: Dict[str, Any]) -> Optional[date]:
    return _d(test.get("tested")) or _d(test.get("received"))


def tests_since_last_good_calibration(eq: Dict[str, Any], orders: List[Dict[str, Any]], failed_on: date,
                                      exclude_wo: Any = None) -> Dict[str, Any]:
    """Laboratory tests that used this equipment after its last passed calibration before a failed
    one (ISO/IEC 17025 6.4.9: examine the effect of the defect on earlier results)."""
    passes = [_d(w.get("completed_date")) for w in orders
              if w.get("id") != exclude_wo and w.get("equipment_id") == eq.get("id") and w.get("type") == "calibration"
              and w.get("status") == "completed" and w.get("calibration_result") != "fail"]
    card = _d(eq.get("last_calibration"))
    good = [d for d in passes + [card] if d and d <= failed_on]
    since = max(good) if good else None
    hits = []
    for t in _list("lab_tests"):
        if not any(r.get("equipment_id") == eq.get("id") for r in t.get("equipment_used") or []):
            continue
        when = _test_date(t)
        if when and when <= failed_on and (since is None or when >= since):
            hits.append({"id": t.get("id"), "sample_ref": t.get("sample_ref"), "borehole_id": t.get("borehole_id"), "date": when.isoformat()})
    return {"since": since.isoformat() if since else None, "tests": hits}


# --------------------------------------------------------------------------- #
# Laboratory test: receipt link, equipment calibration, review and authorisation
# --------------------------------------------------------------------------- #

def _find_receipt(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from . import records

    if record.get("receipt_id"):
        try:
            return records.get_record("sample_receipts", str(record["receipt_id"]))
        except records.NotFound:
            return None
    same = [r for r in _list("sample_receipts") if _key(r.get("borehole_id")) == _key(record.get("borehole_id"))
            and _key(r.get("sample_ref")) == _key(record.get("sample_ref"))]
    if len(same) > 1 and record.get("depth_top") not in (None, ""):
        same = [r for r in same if abs(_n(r.get("depth_top")) - _n(record.get("depth_top"))) < 0.01] or same
    if not same:
        return None
    return max(same, key=lambda r: str(r.get("received_on") or ""))


def receipt_disclaimer(receipt: Dict[str, Any]) -> str:
    """Disclaimer for the report when the customer asked for testing despite a deviation (7.4.3)."""
    if receipt.get("condition") != "deviation" or receipt.get("decision") != "test_with_disclaimer":
        return ""
    labels = dict(DEVIATIONS)
    found = ", ".join(labels.get(d, d) for d in receipt.get("deviations") or [])
    note = str(receipt.get("condition_note") or "").strip()
    detail = "; ".join(x for x in (found, note) if x)
    return f"Sample received with deviations from the specified conditions ({detail}); the customer asked for testing. Results may be affected."


def compute_lab_test(record: Dict[str, Any]) -> None:
    warnings: List[Dict[str, Any]] = []
    previous = _previous("lab_tests", record)
    status = record.get("status")

    # Sample receipt (7.4)
    receipt = _find_receipt(record)
    record["receipt_id"] = (receipt or {}).get("id") or ""
    record["report_disclaimer"] = receipt_disclaimer(receipt) if receipt else ""
    if receipt:
        if not record.get("received"):
            record["received"] = receipt.get("received_on") or ""
        if receipt.get("condition") == "deviation" and status in ("testing", "done"):
            if receipt.get("decision") == "do_not_test":
                _warn(warnings, "The sample receipt says this sample must not be tested")
            elif receipt.get("decision") == "return":
                _warn(warnings, "The sample receipt says this sample is to be returned to the customer")
            elif not receipt.get("decision"):
                _warn(warnings, "The sample arrived with deviations and the customer has not decided yet (ISO/IEC 17025 7.4.3)")

    # Dates and the people responsible (7.5.1)
    received, tested = _d(record.get("received")), _d(record.get("tested"))
    if received and tested and tested < received:
        raise _error("Tested on is before received on")
    if status == "done" and not tested:
        _warn(warnings, "Enter the test date (ISO/IEC 17025 7.5.1)")

    # Equipment used and its calibration on the test date (6.4, 6.5)
    rows = record.get("equipment_used") or []
    when = tested or (date.today() if status in ("testing", "done") else None)
    checks: List[Dict[str, Any]] = []
    if rows and when:
        equipment = {e["id"]: e for e in _list("equipment")}
        orders = _list("work_orders")
        seen: set = set()
        for row in rows:
            eq = equipment.get(row.get("equipment_id") or "")
            if eq is None or eq["id"] in seen:
                continue
            seen.add(eq["id"])
            cal = calibration_on(eq, orders, when)
            checks.append(cal)
            label = f"{eq.get('code')} {eq.get('name')}"
            if cal["status"] == "overdue":
                _warn(warnings, "{equipment} was out of calibration on {date} (due {due}): the result is not traceable; "
                                "raise a nonconformity (ISO/IEC 17025 6.4, 7.10)", equipment=label, date=when.isoformat(), due=cal["due"])
            elif cal["status"] == "not_calibrated":
                _warn(warnings, "{equipment} has no calibration on record before {date}", equipment=label, date=when.isoformat())
            elif cal["status"] == "failed":
                _warn(warnings, "{equipment} failed its last calibration before {date} and must not be used (ISO/IEC 17025 6.4.9)",
                      equipment=label, date=when.isoformat())
            if eq.get("status") in ("broken", "disposed") and status == "testing":
                _warn(warnings, "{equipment} is marked broken or disposed", equipment=label)
    record["calibration_check"] = checks

    # Review and authorisation before release (7.8.1.1); changes after it need a new one (7.5.2)
    changed = bool(previous) and any(not _same(previous.get(k), record.get(k)) for k in REVIEWED_FIELDS)
    if not changed and previous and _blank(record.get("raw")) and _blank(previous.get("raw")):
        # Results typed in by hand (no worksheet): the results themselves are what was reviewed.
        changed = not _same(previous.get("results"), record.get("results"))
    was = bool(previous.get("authorised"))
    me = str(record.get("updated_by") or "").lower()
    has_results = not (_blank(record.get("raw")) and _blank(record.get("results")))
    if (not previous and has_results) or changed:
        record["results_entered_by"] = me
    if record.get("authorised"):
        if was and changed:
            record["authorised"] = False
            record["authorised_by"] = ""
            record["authorised_at"] = ""
            _warn(warnings, "The results changed after they were authorised: review and authorise them again (ISO/IEC 17025 7.8.1.1)")
        elif not was:
            if status != "done":
                raise _error("Mark the test done before authorising its results")
            if role_of(me) not in AUTHORISERS:
                raise _error("Only laboratory staff, managers or administrators can authorise results")
            if separation_on() and me == str(record.get("results_entered_by") or "").lower():
                raise _error("The results must be authorised by someone other than the person who entered them")
            record["authorised_by"] = me
            record["authorised_at"] = date.today().isoformat()
    else:
        record["authorised_by"] = ""
        record["authorised_at"] = ""
    if status != "done":
        record["result_status"] = "in_progress"
    elif record.get("authorised"):
        record["result_status"] = "authorised"
    else:
        record["result_status"] = "awaiting"
        if lab_authorisation_mode() == "require" and not (was and changed):
            raise _error("The results must be reviewed and authorised before the test is marked done (ISO/IEC 17025 7.8.1.1)")
        _warn(warnings, "Results are not yet reviewed and authorised (ISO/IEC 17025 7.8.1.1)")
    _set_warnings(record, warnings)


# --------------------------------------------------------------------------- #
# Sample receipt and chain of custody (7.4)
# --------------------------------------------------------------------------- #

DEVIATIONS = [
    ("seal_broken", "Seal or cap broken"), ("container_damaged", "Tube or container damaged"),
    ("disturbed", "Sample disturbed"), ("moisture_loss", "Moisture loss / dried out"),
    ("insufficient", "Not enough material for the tests"), ("label", "Label missing or unclear"),
    ("mismatch", "Does not match the description or request"), ("late", "Arrived later than the allowed time"),
    ("other", "Other"),
]


def compute_sample_receipt(record: Dict[str, Any]) -> None:
    warnings: List[Dict[str, Any]] = []
    received = _d(record.get("received_on"))
    me_key = (_key(record.get("borehole_id")), _key(record.get("sample_ref")))
    for other in _list("sample_receipts"):
        if other.get("id") != record.get("id") and (_key(other.get("borehole_id")), _key(other.get("sample_ref"))) == me_key \
                and abs(_n(other.get("depth_top")) - _n(record.get("depth_top"))) < 0.01:
            raise _conflict("This sample already has a receipt")
    deviation = record.get("condition") == "deviation"
    if deviation and not record.get("deviations") and not str(record.get("condition_note") or "").strip():
        raise _error("Describe the deviation found on receipt")
    if deviation:
        if not record.get("customer_consulted_on"):
            _warn(warnings, "Consult the customer before testing and record the outcome (ISO/IEC 17025 7.4.3)")
        if not record.get("decision"):
            _warn(warnings, "Record the decision: test, test with a disclaimer in the report, do not test, or return")
    elif record.get("decision") == "test_with_disclaimer":
        raise _error("A disclaimer is only needed for a sample received with deviations")
    if not str(record.get("storage_location") or "").strip() and not record.get("disposed_on"):
        _warn(warnings, "Record where the sample is stored (ISO/IEC 17025 7.4.1)")

    custody = record.get("custody") or []
    for row in custody:
        d = _d(row.get("date"))
        if received and d and d < received:
            raise _error("A chain of custody row is dated before the sample was received")
    ordered = sorted(custody, key=lambda r: (str(r.get("date") or ""), str(r.get("time") or "")))
    record["custody"] = ordered
    last = ordered[-1] if ordered else None
    record["current_holder"] = str((last or {}).get("to_person") or record.get("received_by") or "")
    record["current_location"] = str((last or {}).get("location") or record.get("storage_location") or "")

    disposed = _d(record.get("disposed_on"))
    if disposed and received and disposed < received:
        raise _error("Disposed on is before received on")
    if disposed and not record.get("disposal_method"):
        raise _error("Choose how the sample was disposed of")
    retain = _d(record.get("retain_until"))
    today = date.today()
    if retain and received and retain < received:
        raise _error("Keep until is before received on")
    if retain and retain < today and not disposed:
        _warn(warnings, "The retention period ended on {date}: dispose of or return the sample", date=retain.isoformat())
    record["days_in_store"] = float(((disposed or today) - received).days) if received else None
    if disposed:
        record["receipt_status"] = "returned" if record.get("disposal_method") == "returned" else "disposed"
    elif deviation and not record.get("decision"):
        record["receipt_status"] = "on_hold"
    else:
        record["receipt_status"] = "in_store"
    _set_warnings(record, warnings)


# --------------------------------------------------------------------------- #
# Nonconforming work and corrective action (7.10, 8.7)
# --------------------------------------------------------------------------- #

def compute_nonconformity(record: Dict[str, Any]) -> None:
    warnings: List[Dict[str, Any]] = []
    found = _d(record.get("date"))
    for name, label in (("action_done_on", "Action done on"), ("closed_on", "Closed on"), ("resumed_on", "Work resumed on"),
                        ("effectiveness_on", "Effectiveness checked on")):
        d = _d(record.get(name))
        if found and d and d < found:
            raise _error(f"{label} is before the date found")
    today = date.today()
    previous = _previous("nonconformities", record)
    ca = record.get("corrective_action_needed")
    missing: List[str] = []
    if not str(record.get("impact") or "").strip():
        missing.append("Evaluate the significance and the impact on earlier results (ISO/IEC 17025 7.10.1 c)")
    if not record.get("decision"):
        missing.append("Decide whether the nonconforming work is acceptable (7.10.1 d)")
    if not record.get("customer_action"):
        missing.append("Record whether the customer was notified or work recalled (7.10.1 e)")
    if record.get("work_halted") and not (record.get("resumption_authorised_by") and record.get("resumed_on")):
        missing.append("Work is halted: record who authorised its resumption and when (7.10.1 f)")
    if not ca:
        missing.append("Decide whether corrective action is needed (7.10.3)")
    elif ca == "yes":
        if not str(record.get("root_cause") or "").strip():
            missing.append("Find and record the cause (8.7.1 b)")
        if not str(record.get("corrective_action") or "").strip():
            missing.append("Describe the corrective action (8.7.1 c)")
        elif not record.get("action_done_on"):
            due = _d(record.get("action_due"))
            if due and due < today:
                _warn(warnings, "The corrective action was due on {date}", date=due.isoformat())
        if record.get("action_done_on") and record.get("effective") != "yes":
            missing.append("Review whether the corrective action was effective (8.7.1 d)")
    closing = bool(record.get("closed_on"))
    if closing:
        if missing:
            raise _error("Before closing: " + missing[0])
        me = str(record.get("updated_by") or "").lower()
        if not previous.get("closed_on"):
            if role_of(me) not in CLOSERS:
                raise _error("Only a manager or an administrator can close a nonconformity")
            record["closed_by"] = me
        else:
            record["closed_by"] = previous.get("closed_by") or me
    else:
        record["closed_by"] = ""
        for text in missing:
            _warn(warnings, text)
    if closing:
        stage = "closed"
    elif ca == "yes" and record.get("action_done_on"):
        stage = "verification"
    elif ca == "yes" and str(record.get("corrective_action") or "").strip():
        stage = "corrective_action"
    elif str(record.get("correction") or "").strip() or record.get("decision"):
        stage = "correction"
    else:
        stage = "open"
    record["stage"] = stage
    _set_warnings(record, warnings)


# --------------------------------------------------------------------------- #
# Laboratory figures for the operations overview
# --------------------------------------------------------------------------- #

def lab_overview(tests: List[Dict[str, Any]], ncrs: List[Dict[str, Any]], receipts: List[Dict[str, Any]], today: date) -> Dict[str, Any]:
    open_ncr = [n for n in ncrs if not n.get("closed_on")]
    overdue_ca = [n for n in open_ncr if n.get("corrective_action_needed") == "yes" and not n.get("action_done_on")
                  and _d(n.get("action_due")) and _d(n.get("action_due")) < today]  # type: ignore[operator]
    retention_over = [r for r in receipts if not r.get("disposed_on") and _d(r.get("retain_until"))
                      and _d(r.get("retain_until")) < today]  # type: ignore[operator]
    return {
        "tests_open": sum(1 for t in tests if t.get("status") != "done"),
        "awaiting_authorisation": sum(1 for t in tests if t.get("status") == "done" and not t.get("authorised")),
        "authorised": sum(1 for t in tests if t.get("status") == "done" and t.get("authorised")),
        "calibration_issues": sum(1 for t in tests if any(c.get("status") in ("overdue", "failed", "not_calibrated")
                                                            for c in t.get("calibration_check") or [])),
        "nonconformities_open": len(open_ncr),
        "corrective_actions_overdue": len(overdue_ca),
        "samples_on_hold": sum(1 for r in receipts if r.get("receipt_status") == "on_hold"),
        "samples_past_retention": len(retention_over),
    }
