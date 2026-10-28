"""Work coordination: project tasks with phase templates, the field submission inbox, the crew
deployment roster and laboratory work orders with turnaround (see entities_work.py).

Each ``compute_*`` function is a COMPUTE_HOOK: it runs on every save inside the entity lock, fills the
readonly fields and refuses input that cannot be stored (RecordError). Values that depend on today's
date or on other records changing later (overdue tasks, who is on site, a work order's progress) are
also worked out live by the functions further down, used by routers/erp_work.py.

Warnings use the same format as erp_ops: [{"text": English template, "vars": {...}, "money": [...]}].
"""
from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .erp_ops import _d, _list, _n, _opt, _set_warnings, _warn, add_months, lab_authorisation_mode, separation_on


def _error(message: str) -> Exception:
    from . import records

    return records.RecordError(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _previous(entity: str, record: Dict[str, Any]) -> Dict[str, Any]:
    """The stored version of a record being saved ({} for a new one)."""
    from . import records

    try:
        return records.get_record(entity, str(record.get("id") or ""))
    except records.NotFound:
        return {}


def _round(x: float) -> int:
    """Half up (Python's round() rounds half to even)."""
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


MANAGEMENT = ("admin", "manager", "finance")


# --------------------------------------------------------------------------- #
# Settings (fields added to the operations settings by entities_work.py)
# --------------------------------------------------------------------------- #

# Turnaround targets in days per test category. These are planning defaults for the laboratory to
# set from its own capacity and the customer agreement (ISO/IEC 17025 7.1 review of requests);
# they are not prices and not taken from any company.
LAB_CATEGORIES: List[Tuple[str, str, int]] = [
    ("index", "Index tests (water content, density, Gs, grain size, Atterberg)", 5),
    ("compaction", "Compaction and CBR", 7),
    ("strength", "Strength (UCS, direct shear)", 7),
    ("triaxial", "Triaxial", 14),
    ("consolidation", "Consolidation and swelling", 21),
    ("rock", "Rock and aggregate tests", 10),
    ("chemical", "Chemical tests", 7),
    ("other", "Other tests", 10),
]
CATEGORY_LABEL = {k: label for k, label, _ in LAB_CATEGORIES}

DEFAULT_SETTINGS: Dict[str, Any] = {
    **{f"sla_{k}_days": days for k, _, days in LAB_CATEGORIES},
    "lab_sla_basis": "working",
    "crew_warning_days": 14,
    "induction_valid_months": 12,
}

TEST_CATEGORY: Dict[str, str] = {
    "moisture": "index", "density": "index", "specific_gravity": "index", "grain_size": "index", "atterberg": "index",
    "relative_density": "index",
    "compaction": "compaction", "cbr_lab": "compaction",
    "ucs": "strength", "direct_shear": "strength",
    "triaxial": "triaxial", "triaxial_cu": "triaxial", "triaxial_cd": "triaxial",
    "consolidation": "consolidation", "swelling": "consolidation", "crs": "consolidation",
    "la_abrasion": "rock", "soundness": "rock", "slake_durability": "rock", "point_load": "rock",
}
# Test types added later are placed by their key.
_KEYWORDS: List[Tuple[Tuple[str, ...], str]] = [
    (("triax",), "triaxial"),
    (("consol", "oedo", "swell", "crs"), "consolidation"),
    (("ph", "sulfate", "sulphate", "chloride", "organic", "chem", "resistivity_lab"), "chemical"),
    (("rock", "point_load", "abrasion", "slake", "sound"), "rock"),
    (("proctor", "compaction", "cbr"), "compaction"),
    (("ucs", "shear", "vane"), "strength"),
    (("moisture", "density", "gravity", "grain", "sieve", "hydrometer", "atterberg", "limit"), "index"),
]


def test_category(test_type: str) -> str:
    key = str(test_type or "").lower()
    if key in TEST_CATEGORY:
        return TEST_CATEGORY[key]
    for words, cat in _KEYWORDS:
        if any(w == key or w in key.split("_") or (len(w) > 3 and w in key) for w in words):
            return cat
    return "other"


def settings() -> Dict[str, Any]:
    from . import records

    saved = records.get_singleton("ops_settings") or {}
    out = dict(DEFAULT_SETTINGS)
    for key, default in DEFAULT_SETTINGS.items():
        if isinstance(default, str):
            if saved.get(key):
                out[key] = str(saved[key])
            continue
        value = _opt(saved.get(key))
        if value is not None:
            out[key] = int(value)
    return out


def sla_days(test_type: str, cfg: Dict[str, Any]) -> int:
    return int(cfg.get(f"sla_{test_category(test_type)}_days") or DEFAULT_SETTINGS[f"sla_{test_category(test_type)}_days"])


# --------------------------------------------------------------------------- #
# Working days
# --------------------------------------------------------------------------- #

def add_days(start: date, n: int, basis: str = "working") -> date:
    """The date n days after start: calendar days, or working days (Monday to Friday).
    Public holidays are not known to the app; agree the due date by hand around them."""
    if basis == "calendar":
        return start + timedelta(days=n)
    d, left = start, n
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


def days_between(a: date, b: date, basis: str = "working") -> int:
    """Days after a up to and including b (negative when b is before a)."""
    if basis == "calendar":
        return (b - a).days
    if b < a:
        return -days_between(b, a, basis)
    full_weeks, rest = divmod((b - a).days, 7)
    count = full_weeks * 5
    d = a + timedelta(days=full_weeks * 7)
    for _ in range(rest):
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return count


# --------------------------------------------------------------------------- #
# Project tasks
# --------------------------------------------------------------------------- #

TASK_STATUS: List[Tuple[str, str]] = [("todo", "To do"), ("in_progress", "In progress"), ("blocked", "Blocked"), ("done", "Done")]
TASK_PRIORITY: List[Tuple[str, str]] = [("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")]

PHASES: List[Tuple[str, str]] = [
    ("reconnaissance", "Site reconnaissance"),
    ("mobilisation", "Mobilisation"),
    ("field_data", "Field data collection"),
    ("processing", "Data processing and laboratory"),
    ("analysis", "Analysis and interpretation"),
    ("report", "Report"),
    ("demobilisation", "Demobilisation"),
    ("other", "Other"),
]
PHASE_LABEL = dict(PHASES)

# Share of the project period from its start: (task starts, task is due). Field work takes the first
# half; demobilisation follows it, processing and laboratory testing overlap it, the report closes the period.
PHASE_WINDOW: Dict[str, Tuple[float, float]] = {
    "reconnaissance": (0.0, 0.05),
    "mobilisation": (0.03, 0.10),
    "field_data": (0.10, 0.55),
    "processing": (0.25, 0.72),
    "analysis": (0.55, 0.85),
    "report": (0.75, 1.0),
    "demobilisation": (0.55, 0.62),
}
FIELD_PHASES = ("reconnaissance", "mobilisation", "field_data", "processing", "analysis", "report", "demobilisation")
SERVICE_PHASES: Dict[str, Tuple[str, ...]] = {
    "geotechnical": FIELD_PHASES, "cpt": FIELD_PHASES, "geophysics": FIELD_PHASES, "geology": FIELD_PHASES, "survey": FIELD_PHASES,
    "laboratory": ("processing", "report"),
    "analysis": ("analysis", "report"),
}
CHECKLISTS: Dict[str, List[str]] = {
    "reconnaissance": ["Site access and work permits checked", "Underground utilities and overhead lines located",
                       "Test points staked out and photographed"],
    "mobilisation": ["Equipment inspected and calibration valid", "Crew safety induction and medical clearance checked",
                     "Transport and accommodation arranged"],
    "field_data": ["Daily reports sent to the office", "Logs and worksheets checked in the field",
                   "Samples labelled and sent to the laboratory"],
    "processing": ["Field data entered and checked", "Laboratory tests requested and received", "Laboratory results authorised"],
    "analysis": ["Soil profile and design parameters chosen", "Engineering analyses checked by a second engineer"],
    "report": ["Draft report reviewed", "Report approved and sent to the client"],
    "demobilisation": ["Equipment returned and checked", "Site restored and test holes backfilled"],
}
DEFAULT_PROJECT_DAYS = 60
TRIGGER_STATUSES = ("contract", "ongoing")


def generated_title(service_label: str, phase: str) -> str:
    return f"{PHASE_LABEL.get(phase, phase)} – {service_label}"


def standard_task_plan(project: Dict[str, Any], today: Optional[date] = None) -> List[Dict[str, Any]]:
    """The phase tasks of a project: one per service and phase, dated over the project period.
    Without an end date a period of DEFAULT_PROJECT_DAYS is assumed; without a start date, today."""
    from .entities import SERVICE_LINES

    labels = dict(SERVICE_LINES)
    start = _d(project.get("start_date")) or today or date.today()
    end = _d(project.get("end_date"))
    total = (end - start).days if end and end > start else DEFAULT_PROJECT_DAYS
    services = [s for s in (project.get("services") or []) if s in SERVICE_PHASES] or ["geotechnical"]
    out: List[Dict[str, Any]] = []
    for service in services:
        for seq, phase in enumerate(SERVICE_PHASES[service], start=1):
            a, b = PHASE_WINDOW[phase]
            title = generated_title(labels.get(service, service), phase)
            out.append({
                "template_key": f"{service}:{phase}", "service": service, "phase": phase, "sequence": seq,
                "title": title, "generated_title": title,
                "start_date": (start + timedelta(days=_round(a * total))).isoformat(),
                "due_date": (start + timedelta(days=_round(b * total))).isoformat(),
                "checklist": [{"item": c, "done": False} for c in CHECKLISTS.get(phase, [])],
                "assignee": str(project.get("leader") or ""),
                "priority": "normal", "status": "todo",
            })
    return out


def create_standard_tasks(project: Dict[str, Any], user: str, pending: bool = False) -> Dict[str, int]:
    """Create the phase tasks the project does not have yet (never twice: matched by template key).
    ``pending``: the project is being saved and its document does not exist yet."""
    from . import docstore, records
    from .entities import ENTITIES

    entity = ENTITIES["tasks"]
    project_id = str(project.get("id") or "")

    def refs(name: str, rid: str) -> bool:
        return (pending and name == "projects" and rid == project_id) or records._exists(name, rid)

    created = skipped = 0
    with docstore.lock(records._lock_name("tasks")):
        have = {str(t.get("template_key") or "") for t in records.list_records("tasks") if t.get("project_id") == project_id}
        for plan in standard_task_plan(project):
            if plan["template_key"] in have:
                skipped += 1
                continue
            data = {k: v for k, v in plan.items() if k not in ("template_key", "generated_title", "sequence")}
            data["project_id"] = project_id
            cleaned = records.clean(entity, data, refs)
            record: Dict[str, Any] = dict(cleaned)
            stamp = datetime.now(timezone.utc).isoformat()
            record.update({"id": secrets.token_hex(8), "template_key": plan["template_key"], "generated_title": plan["generated_title"],
                           "sequence": float(plan["sequence"]), "created_at": stamp, "created_by": user, "updated_at": stamp,
                           "updated_by": user})
            records.compute("tasks", record)
            docstore.write_text(records._doc("tasks", record["id"]), json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            have.add(plan["template_key"])
            created += 1
    return {"created": created, "skipped": skipped}


def _untouched(task: Dict[str, Any]) -> bool:
    """A standard task nobody has worked on: still to do, never edited after it was generated."""
    return bool(task.get("template_key")) and task.get("status") == "todo" and task.get("updated_at") == task.get("created_at") \
        and len(task.get("history") or []) <= 1


def project_delete_guard(project: Dict[str, Any], role: str, action: str) -> Optional[str]:
    """Deleting a project removes its standard tasks when nothing else uses the project and nobody worked on them."""
    from . import docstore, records

    if action != "delete":
        return None
    tasks = [t for t in records.list_records("tasks") if t.get("project_id") == project.get("id")]
    if not tasks or not all(_untouched(t) for t in tasks):
        return None
    if any(not r.startswith("Task ") for r in records.references_to("projects", str(project.get("id")))):
        return None  # still used by quotations, worksheets ...: the delete is refused with the full list
    with docstore.lock(records._lock_name("tasks")):
        for t in tasks:
            docstore.delete(records._doc("tasks", t["id"]))
    return None


def compute_task(record: Dict[str, Any]) -> None:
    warnings: List[Dict[str, Any]] = []
    prev = _previous("tasks", record)
    start, due = _d(record.get("start_date")), _d(record.get("due_date"))
    if start and due and due < start:
        raise _error("The due date is before the start date")
    status = str(record.get("status") or "todo")
    if status != "blocked":
        record["blocked_reason"] = ""
    if status == "done":
        if not (prev.get("status") == "done" and prev.get("completed_at")):
            record["completed_at"] = date.today().isoformat()
    else:
        record["completed_at"] = ""
    rows = record.get("checklist") or []
    done = sum(1 for r in rows if r.get("done"))
    record["checklist_done"] = float(done)
    record["checklist_pct"] = round(done / len(rows) * 100, 1) if rows else None
    if status == "blocked" and not str(record.get("blocked_reason") or "").strip():
        _warn(warnings, "Write why the task is blocked")
    if status == "done" and rows and done < len(rows):
        _warn(warnings, "{n} checklist items are not ticked", n=len(rows) - done)
    if not record.get("assignee"):
        _warn(warnings, "Nobody is assigned to this task")
    history = list(record.get("history") or prev.get("history") or [])
    if not prev or prev.get("status") != status:
        history.append({"at": _now(), "by": str(record.get("updated_by") or ""), "from": prev.get("status") or "",
                        "to": status, "note": str(record.get("blocked_reason") or "") if status == "blocked" else ""})
    record["history"] = history[-100:]
    _set_warnings(record, warnings)


def task_overdue(task: Dict[str, Any], today: date) -> bool:
    due = _d(task.get("due_date"))
    return bool(due and due < today and task.get("status") != "done")


def task_view(task: Dict[str, Any], today: date, projects: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    due = _d(task.get("due_date"))
    project = projects.get(str(task.get("project_id") or "")) or {}
    return {**task, "overdue": task_overdue(task, today), "days_left": (due - today).days if due else None,
            "project_code": project.get("code") or "", "project_name": project.get("name") or ""}


def _task_order(t: Dict[str, Any]) -> Tuple[int, str, float]:
    """Overdue first, then open tasks by due date, then done ones."""
    rank = 0 if t.get("overdue") else (2 if t.get("status") == "done" else 1)
    return (rank, str(t.get("due_date") or "9999"), _n(t.get("sequence")))


def my_tasks(email: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Tasks assigned to this user: overdue first, then open by due date, then done in the last 14 days."""
    today = today or date.today()
    me = email.lower()
    projects = {p["id"]: p for p in _list("projects")}
    out = []
    for t in _list("tasks"):
        if str(t.get("assignee") or "").lower() != me:
            continue
        if t.get("status") == "done" and (_d(t.get("completed_at")) or today) < today - timedelta(days=14):
            continue
        out.append(task_view(t, today, projects))
    out.sort(key=_task_order)
    return out


def set_task_status(record_id: str, status: str, note: str, checklist: Optional[List[bool]], role: str, email: str) -> Dict[str, Any]:
    """Status (and checklist ticks) changed by the assignee or by someone who may edit the task."""
    from . import records
    from .entities import ENTITIES

    entity = ENTITIES["tasks"]
    if status not in dict(TASK_STATUS):
        raise _error("Choose one of the listed options")
    record = records.get_record("tasks", record_id)
    mine = str(record.get("assignee") or "").lower() == email.lower()
    if not (records.can_write(entity, role, record, email) or mine):
        raise PermissionError("Only the person assigned or a project manager can change this task")
    data = {f.name: record.get(f.name) for f in entity.fields if not f.readonly}
    data["status"] = status
    if status == "blocked":
        data["blocked_reason"] = (note or "").strip()[:300] or data.get("blocked_reason") or ""
    if checklist is not None:
        rows = list(data.get("checklist") or [])
        if len(checklist) != len(rows):
            raise _error("The checklist changed in the meantime; reload the task")
        data["checklist"] = [{**r, "done": bool(checklist[i])} for i, r in enumerate(rows)]
    return records.save("tasks", data, email, record_id=record_id)


def task_summary(tasks: Iterable[Dict[str, Any]], today: date) -> Dict[str, Any]:
    tasks = list(tasks)
    open_ = [t for t in tasks if t.get("status") != "done"]
    return {
        "open": len(open_), "overdue": sum(1 for t in open_ if task_overdue(t, today)),
        "blocked": sum(1 for t in open_ if t.get("status") == "blocked"),
        "done": len(tasks) - len(open_),
        "by_status": {k: sum(1 for t in tasks if t.get("status") == k) for k, _ in TASK_STATUS},
    }


# --------------------------------------------------------------------------- #
# Field submissions: field -> office hand-off
# --------------------------------------------------------------------------- #

SUB_STATES: List[Tuple[str, str]] = [
    ("draft", "Not sent yet"), ("submitted", "Sent to the office"), ("acknowledged", "Acknowledged"),
    ("processing", "In processing"), ("done", "Done"), ("returned", "Returned for correction"),
]
SUB_ACTIONS = ("submit", "acknowledge", "process", "done", "return", "reopen")
_SUB_NEXT = {"submit": "submitted", "acknowledge": "acknowledged", "process": "processing", "done": "done",
             "return": "returned", "reopen": "processing"}


class FlowError(ValueError):
    pass


def is_recipient(record: Dict[str, Any], role: str) -> bool:
    """The office (managers, administrators) receives every package; the laboratory those with samples."""
    return role in ("admin", "manager") or (role == "lab" and bool(record.get("samples_included")))


def _sender(record: Dict[str, Any]) -> str:
    return str(record.get("created_by") or "").lower()


def submission_allowed(record: Dict[str, Any], role: str, email: str) -> List[str]:
    state = record.get("sub_status") or "draft"
    me = email.lower()
    own = _sender(record) == me
    out: List[str] = []
    if state in ("draft", "returned") and (own or role == "admin"):
        out.append("submit")
    office = is_recipient(record, role) and not (separation_on() and own and role != "admin")
    if office:
        if state == "submitted":
            out += ["acknowledge", "process"]
        if state == "acknowledged":
            out += ["process", "done"]
        if state == "processing":
            out.append("done")
        if state in ("submitted", "acknowledged", "processing"):
            out.append("return")
        if state == "done" and role in ("admin", "manager"):
            out.append("reopen")
    return out


def _package_size(record: Dict[str, Any]) -> int:
    return (len(record.get("boreholes") or []) + len(record.get("worksheets") or []) + len(record.get("cpt_tests") or [])
            + (1 if record.get("daily_report_id") else 0) + len(record.get("files") or []))


def submission_act(record_id: str, action: str, note: str, role: str, email: str) -> Dict[str, Any]:
    from . import docstore, records
    from .entities import ENTITIES

    entity = ENTITIES["field_submissions"]
    if action not in SUB_ACTIONS:
        raise FlowError("Unknown step")
    note = (note or "").strip()[:1000]
    with docstore.lock(records._lock_name("field_submissions")):
        record = records.get_record("field_submissions", record_id)
        if not records.can_see(entity, role, record, email):
            raise records.NotFound()
        if action not in submission_allowed(record, role, email):
            raise FlowError("You cannot take this step on this package now")
        if action in ("return", "reopen") and not note:
            raise FlowError("Write the reason in the note")
        if action == "submit" and not _package_size(record):
            raise FlowError("Add the daily report, worksheets, logs or files of the day before sending")
        state = record.get("sub_status") or "draft"
        new = _SUB_NEXT[action]
        history = list(record.get("sub_history") or [])
        history.append({"action": action, "from": state, "to": new, "by": email, "role": role, "note": note, "at": _now()})
        record["sub_status"] = new
        record["sub_history"] = history[-200:]
        if action == "submit":
            record["submitted_at"] = _now()
            record["resubmissions"] = float(sum(1 for h in history if h["action"] == "submit") - 1)
        if action == "done":
            record["done_at"] = _now()
        record["updated_at"] = _now()
        record["updated_by"] = email
        docstore.write_text(records._doc("field_submissions", record_id), json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    return record


def submission_lock(record: Dict[str, Any], role: str, action: str) -> Optional[str]:
    state = record.get("sub_status") or "draft"
    if action == "delete" and state != "draft":
        return "A package sent to the office is kept with its history and cannot be deleted"
    if action == "edit" and state not in ("draft", "returned"):
        return "This package was sent to the office; it can be changed only when the office returns it"
    return None


def compute_submission(record: Dict[str, Any]) -> None:
    warnings: List[Dict[str, Any]] = []
    record.setdefault("sub_status", "draft")
    record.setdefault("sub_history", [])
    day = str(record.get("date") or "")
    project = str(record.get("project_id") or "")
    acts = {a["id"]: a for a in _list("field_activities")}
    seen: set = set()
    for row in record.get("worksheets") or []:
        a = acts.get(row.get("activity_id") or "")
        if a is None:
            continue
        if a["id"] in seen:
            raise _error("The same worksheet is listed twice")
        seen.add(a["id"])
        if project and a.get("project_id") and a.get("project_id") != project:
            _warn(warnings, "{code} belongs to another project", code=a.get("code") or "")
        if day and a.get("date") and a.get("date") != day:
            _warn(warnings, "{code} is dated {date}, not the day of this package", code=a.get("code") or "", date=a.get("date"))
    report = acts.get(str(record.get("daily_report_id") or ""))
    if report is not None:
        if report.get("method") != "daily_report":
            _warn(warnings, "The chosen daily report is not a daily report worksheet")
        elif day and report.get("date") and report.get("date") != day:
            _warn(warnings, "The daily report is dated {date}, not the day of this package", date=report.get("date"))
    elif record.get("sub_status") in ("draft", "returned"):
        _warn(warnings, "No daily report in this package")
    cpts = {c["id"]: c for c in _list("cpt")}
    for row in record.get("cpt_tests") or []:
        c = cpts.get(row.get("cpt_id") or "")
        if c and day and c.get("date") and c.get("date") != day:
            _warn(warnings, "{code} is dated {date}, not the day of this package", code=c.get("test_id") or "", date=c.get("date"))
    holes = [str(r.get("borehole_id") or "").strip() for r in record.get("boreholes") or []]
    if len({h.lower() for h in holes if h}) != len([h for h in holes if h]):
        raise _error("The same borehole is listed twice")
    if record.get("samples_included") and not record.get("sample_count") and not record.get("sample_note"):
        _warn(warnings, "Say how many samples were sent and how")
    record["recipients"] = "office_lab" if record.get("samples_included") else "office"
    record["item_count"] = float(_package_size(record))
    _set_warnings(record, warnings)


def submission_inbox(role: str, email: str) -> List[Dict[str, Any]]:
    """Packages waiting for this user: to handle in the office or laboratory, or returned to the sender."""
    from . import records
    from .entities import ENTITIES

    entity = ENTITIES["field_submissions"]
    if not records.can_read(entity, role):
        return []
    me = email.lower()
    projects = {p["id"]: p for p in _list("projects")}
    out = []
    for r in records.list_records("field_submissions"):
        if not records.can_see(entity, role, r, email):
            continue
        state = r.get("sub_status") or "draft"
        acts = submission_allowed(r, role, email)
        waiting = (state in ("submitted", "acknowledged", "processing") and any(a in acts for a in ("acknowledge", "process", "done"))) \
            or (state == "returned" and _sender(r) == me)
        if not waiting:
            continue
        last = (r.get("sub_history") or [{}])[-1]
        project = projects.get(str(r.get("project_id") or "")) or {}
        out.append({"id": r["id"], "number": r.get("number") or "", "date": r.get("date") or "", "state": state,
                    "project": f"{project.get('code') or ''} {project.get('name') or ''}".strip(), "by": r.get("created_by") or "",
                    "samples": bool(r.get("samples_included")), "since": last.get("at") or r.get("updated_at"),
                    "note": last.get("note") or "", "items": int(_n(r.get("item_count")))})
    out.sort(key=lambda x: str(x.get("since") or ""))
    return out


def day_records(day: str, project_id: str, role: str, email: str) -> Dict[str, Any]:
    """A user's field records of one day, to pick from when building a package. Field users see their own."""
    from . import records, storage
    from .entities import ENTITIES

    me = email.lower()
    own_only = role not in ("admin", "manager")
    projects = {p["id"]: p for p in _list("projects")}
    project_name = str((projects.get(project_id) or {}).get("name") or "").strip().lower()

    def keep(r: Dict[str, Any]) -> bool:
        if own_only and str(r.get("created_by") or "").lower() != me:
            return False
        return (not project_id or r.get("project_id") == project_id) and str(r.get("date") or "") == day

    acts = [r for r in records.list_records("field_activities") if keep(r)] if records.can_read(ENTITIES["field_activities"], role) else []
    cpts = [r for r in records.list_records("cpt") if keep(r)] if records.can_read(ENTITIES["cpt"], role) else []
    logs = []
    for row in storage.load_reports():
        start, end = str(row.get("StartDate") or ""), str(row.get("EndDate") or row.get("StartDate") or "")
        if not (start and start <= day <= (end or start)):
            continue
        if own_only and str(row.get("SubmittedBy") or "").lower() != me:
            continue
        if project_name and str(row.get("ProjectName") or "").strip().lower() != project_name:
            continue
        logs.append({"borehole_id": row.get("BoreholeID"), "site": row.get("SiteName") or "", "depth": row.get("FinalDepth_m") or ""})
    return {
        "daily_reports": [{"id": a["id"], "code": a.get("code"), "method": a.get("method")} for a in acts if a.get("method") == "daily_report"],
        "worksheets": [{"id": a["id"], "code": a.get("code"), "method": a.get("method"), "summary": a.get("summary") or ""}
                       for a in acts if a.get("method") != "daily_report"],
        "cpt": [{"id": c["id"], "code": c.get("test_id"), "depth": c.get("final_depth")} for c in cpts],
        "logs": logs,
    }


# --------------------------------------------------------------------------- #
# Crew deployment roster
# --------------------------------------------------------------------------- #

POSITIONS: List[Tuple[str, str]] = [
    ("project_manager", "Project manager"), ("site_engineer", "Site engineer"), ("geologist", "Geologist"),
    ("geotechnical_engineer", "Geotechnical engineer"), ("surveyor", "Surveyor"), ("geophysicist", "Geophysicist"),
    ("driller", "Driller"), ("driller_helper", "Driller helper"), ("cpt_operator", "CPT operator"),
    ("lab_technician", "Lab technician"), ("safety_officer", "Safety officer"), ("driver", "Driver"),
    ("operator", "Equipment operator"), ("mechanic", "Mechanic"), ("labourer", "Labourer"), ("other", "Other"),
]
EMPLOYER_TYPES: List[Tuple[str, str]] = [("permanent", "Permanent"), ("contract", "Contract"), ("subcontract", "Subcontractor"),
                                         ("daily", "Daily worker")]
ACCOMMODATION: List[Tuple[str, str]] = [("camp", "Site camp"), ("hotel", "Hotel / guest house"), ("local", "Local hire, own home"),
                                        ("commute", "Commutes from base")]
DEPLOY_STATUS: List[Tuple[str, str]] = [("planned", "Planned"), ("on_site", "On site"), ("finished", "Finished")]
COMPLIANCE: List[Tuple[str, str]] = [("ok", "OK"), ("expiring", "Expiring soon"), ("expired", "Expired"), ("missing", "Missing")]
_COMPLIANCE_RANK = {"ok": 0, "expiring": 1, "missing": 2, "expired": 3}


def _expiry_state(until: Optional[date], today: date, warn_days: int) -> str:
    if until is None:
        return "missing"
    if until < today:
        return "expired"
    if (until - today).days <= warn_days:
        return "expiring"
    return "ok"


def deployment_figures(record: Dict[str, Any], today: date, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Status, man-days and document checks of one person's deployment on a date."""
    start, end = _d(record.get("deploy_start")), _d(record.get("deploy_end"))
    if start is None:
        status = "planned"
    elif start > today:
        status = "planned"
    elif end is not None and end < today:
        status = "finished"
    else:
        status = "on_site"
    last = min(end, today) if end else today
    man_days = (last - start).days + 1 if start and last >= start else 0
    planned = (end - start).days + 1 if start and end and end >= start else None
    rate = _opt(record.get("daily_rate"))
    warn_days = int(cfg.get("crew_warning_days") or 14)
    medical_until = _d(record.get("medical_expiry"))
    induction = _d(record.get("induction_date"))
    induction_until = add_months(induction, int(cfg.get("induction_valid_months") or 12)) if induction else None
    medical = _expiry_state(medical_until, today, warn_days)
    induct = _expiry_state(induction_until, today, warn_days)
    warnings: List[Dict[str, Any]] = []
    active = status != "finished"
    if active:
        if medical == "missing":
            _warn(warnings, "No medical clearance on record")
        elif medical == "expired":
            _warn(warnings, "Medical clearance expired on {date}", date=medical_until.isoformat() if medical_until else "")
        elif medical == "expiring":
            _warn(warnings, "Medical clearance expires on {date}", date=medical_until.isoformat() if medical_until else "")
        if induct == "missing":
            _warn(warnings, "No safety induction on record")
        elif induct == "expired":
            _warn(warnings, "Safety induction expired on {date}: repeat it before work", date=induction_until.isoformat() if induction_until else "")
        elif induct == "expiring":
            _warn(warnings, "Safety induction expires on {date}", date=induction_until.isoformat() if induction_until else "")
        if medical_until and end and medical == "ok" and medical_until < end:
            _warn(warnings, "Medical clearance ends on {date}, before the deployment ends", date=medical_until.isoformat())
        if induction and start and induction > start:
            _warn(warnings, "Safety induction is after the deployment starts")
        if not str(record.get("emergency_phone") or "").strip():
            _warn(warnings, "No emergency contact phone")
    compliance = max((medical, induct), key=lambda s: _COMPLIANCE_RANK[s]) if active else "ok"
    return {
        "deployment_status": status, "man_days": float(man_days), "planned_man_days": float(planned) if planned is not None else None,
        "cost_to_date": float(round(man_days * rate)) if rate is not None else None,
        "induction_valid_until": induction_until.isoformat() if induction_until else "",
        "medical_state": medical, "induction_state": induct, "compliance": compliance, "warnings": warnings,
    }


def compute_deployment(record: Dict[str, Any]) -> None:
    start, end = _d(record.get("deploy_start")), _d(record.get("deploy_end"))
    if start and end and end < start:
        raise _error("The deployment ends before it starts")
    figs = deployment_figures(record, date.today(), settings())
    for key in ("deployment_status", "man_days", "planned_man_days", "cost_to_date", "induction_valid_until", "compliance"):
        record[key] = figs[key]
    _set_warnings(record, figs["warnings"])


def roster(role: str, email: str, project_id: str = "", today: Optional[date] = None) -> Dict[str, Any]:
    """Live roster with man-days per project; daily rates and costs only for management and finance."""
    from . import records
    from .entities import ENTITIES

    today = today or date.today()
    cfg = settings()
    entity = ENTITIES["crew_deployments"]
    money = role in MANAGEMENT
    projects = {p["id"]: p for p in _list("projects")}
    rows = []
    for r in records.list_records("crew_deployments"):
        if not records.can_see(entity, role, r, email) or (project_id and r.get("project_id") != project_id):
            continue
        figs = deployment_figures(r, today, cfg)
        row = {**records.for_viewer(entity, r, role), **{k: v for k, v in figs.items() if k != "cost_to_date"},
               "warning_count": float(len(figs["warnings"]))}
        if money:
            row["cost_to_date"] = figs["cost_to_date"]
        rows.append(row)
    rows.sort(key=lambda r: (str(r.get("project_id")), {"on_site": 0, "planned": 1, "finished": 2}[r["deployment_status"]],
                             str(r.get("position")), str(r.get("person_name"))))
    by_project: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        pid = str(r.get("project_id") or "")
        p = projects.get(pid) or {}
        s = by_project.setdefault(pid, {"project_id": pid, "code": p.get("code") or "", "name": p.get("name") or "", "people": 0,
                                        "on_site": 0, "planned": 0, "man_days": 0.0, "planned_man_days": 0.0, "warnings": 0,
                                        **({"cost_to_date": 0.0} if money else {})})
        s["people"] += 1
        s["on_site"] += 1 if r["deployment_status"] == "on_site" else 0
        s["planned"] += 1 if r["deployment_status"] == "planned" else 0
        s["man_days"] += r["man_days"]
        s["planned_man_days"] += r["planned_man_days"] or 0
        s["warnings"] += 1 if r["warnings"] else 0
        if money:
            s["cost_to_date"] += r.get("cost_to_date") or 0
    return {
        "as_of": today.isoformat(), "rows": rows, "projects": sorted(by_project.values(), key=lambda s: str(s["code"])),
        "totals": {"people": len(rows), "on_site": sum(1 for r in rows if r["deployment_status"] == "on_site"),
                   "man_days": sum(r["man_days"] for r in rows),
                   "with_warnings": sum(1 for r in rows if r["warnings"]),
                   "expired": sum(1 for r in rows if r["compliance"] == "expired" and r["deployment_status"] != "finished")},
    }


# --------------------------------------------------------------------------- #
# Laboratory work orders
# --------------------------------------------------------------------------- #

LWO_STATUS: List[Tuple[str, str]] = [
    ("received", "Received"), ("in_testing", "In testing"), ("awaiting_review", "Awaiting review"),
    ("ready", "Authorised, ready to report"), ("reported", "Reported"), ("cancelled", "Cancelled"),
]
# Share of a test's work done at each stage, for the progress bar.
TEST_PROGRESS = {"requested": 0.0, "received": 0.1, "testing": 0.5, "done": 0.8}


def test_progress(test: Dict[str, Any]) -> float:
    if test.get("status") == "done" and test.get("authorised"):
        return 1.0
    return TEST_PROGRESS.get(str(test.get("status") or ""), 0.0)


def order_state(order: Dict[str, Any], tests: Dict[str, Dict[str, Any]], cfg: Dict[str, Any], today: date) -> Dict[str, Any]:
    """Status, progress, due date and turnaround of a laboratory work order from its linked tests."""
    basis = str(cfg.get("lab_sla_basis") or "working")
    linked = [tests[r["lab_test_id"]] for r in order.get("tests") or [] if r.get("lab_test_id") in tests]
    received = _d(order.get("received"))
    reported = _d(order.get("reported_on"))
    sla = max((sla_days(str(t.get("test_type") or ""), cfg) for t in linked), default=None)
    agreed = _d(order.get("agreed_due"))
    due = agreed or (add_days(received, sla, basis) if received and sla is not None else None)
    done = sum(1 for t in linked if t.get("status") == "done")
    authorised = sum(1 for t in linked if t.get("status") == "done" and t.get("authorised"))
    if order.get("cancelled"):
        status = "cancelled"
    elif reported:
        status = "reported"
    elif linked and authorised == len(linked):
        status = "ready"
    elif linked and done == len(linked):
        status = "awaiting_review"
    elif any(t.get("status") in ("testing", "done") for t in linked):
        status = "in_testing"
    else:
        status = "received"
    progress = 100.0 if status == "reported" else (round(sum(test_progress(t) for t in linked) / len(linked) * 100, 1) if linked else 0.0)
    turnaround = days_between(received, reported, basis) if received and reported else None
    end = reported or today
    open_ = status not in ("reported", "cancelled")
    late = days_between(due, end, basis) if due and end > due and status != "cancelled" else 0
    by_cat: Dict[str, Dict[str, int]] = {}
    for t in linked:
        c = by_cat.setdefault(test_category(str(t.get("test_type") or "")), {"tests": 0, "done": 0, "authorised": 0})
        c["tests"] += 1
        c["done"] += 1 if t.get("status") == "done" else 0
        c["authorised"] += 1 if t.get("status") == "done" and t.get("authorised") else 0
    return {
        "status": status, "sla_days": float(sla) if sla is not None else None, "due_date": due.isoformat() if due else "",
        "progress_pct": progress, "test_count": float(len(linked)), "tests_done": float(done), "tests_authorised": float(authorised),
        "turnaround_days": float(turnaround) if turnaround is not None else None,
        "on_time": ("yes" if reported <= due else "no") if (reported and due) else "",
        "overdue": bool(open_ and due and today > due), "days_late": float(late),
        "days_left": float(days_between(today, due, basis)) if (open_ and due) else None,
        "by_category": by_cat, "basis": basis,
    }


def compute_lab_order(record: Dict[str, Any], tests: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
    warnings: List[Dict[str, Any]] = []
    received, reported = _d(record.get("received")), _d(record.get("reported_on"))
    if received and reported and reported < received:
        raise _error("Reported on is before received on")
    rows = record.get("tests") or []
    ids = [r.get("lab_test_id") for r in rows]
    if len(set(ids)) != len(ids):
        raise _error("The same laboratory test is listed twice")
    if tests is None:
        tests = {t["id"]: t for t in _list("lab_tests")}
    project = record.get("project_id")
    if project and not record.get("client_id"):
        p = next((x for x in _list("projects") if x.get("id") == project), None)
        if p:
            record["client_id"] = p.get("client_id") or ""
    cfg = settings()
    state = order_state(record, tests, cfg, date.today())
    for key in ("status", "sla_days", "due_date", "progress_pct", "test_count", "tests_done", "tests_authorised", "turnaround_days", "on_time"):
        record[key] = state[key]
    record["by_category"] = state["by_category"]
    linked = [tests[i] for i in ids if i in tests]
    if not rows and not record.get("cancelled"):
        _warn(warnings, "Link the laboratory tests of this work order")
    others = [o for o in _list("lab_work_orders") if o.get("id") != record.get("id") and not o.get("cancelled")]
    for t in linked:
        if project and t.get("project_id") and t.get("project_id") != project:
            _warn(warnings, "{sample} belongs to another project", sample=f"{t.get('borehole_id')} {t.get('sample_ref')}")
        for o in others:
            if any(r.get("lab_test_id") == t["id"] for r in o.get("tests") or []):
                _warn(warnings, "{sample} {test} is also on work order {number}", sample=f"{t.get('borehole_id')} {t.get('sample_ref')}",
                      test=t.get("test_type") or "", number=o.get("number") or "")
    if reported and len(linked) != state["tests_authorised"]:
        if lab_authorisation_mode() == "require":
            raise _error("Every test must be done and its results authorised before the work order is reported")
        _warn(warnings, "Reported before every test was done and authorised (ISO/IEC 17025 7.8.1.1)")
    if state["overdue"]:
        _warn(warnings, "Past the due date {date}", date=state["due_date"])
    if not record.get("technician") and state["status"] in ("received", "in_testing"):
        _warn(warnings, "No technician assigned")
    _set_warnings(record, warnings)


def refresh_orders_for_test(test: Dict[str, Any]) -> None:
    """After a laboratory test is saved: recompute the work orders that list it (status, progress)."""
    from . import docstore, records

    test_id = str(test.get("id") or "")
    if not test_id:
        return
    orders = [o for o in records.list_records("lab_work_orders") if any(r.get("lab_test_id") == test_id for r in o.get("tests") or [])]
    if not orders:
        return
    tests = {t["id"]: t for t in records.list_records("lab_tests")}
    tests[test_id] = test
    with docstore.lock(records._lock_name("lab_work_orders")):
        for o in orders:
            try:
                compute_lab_order(o, tests)
            except records.RecordError:
                continue
            docstore.write_text(records._doc("lab_work_orders", o["id"]), json.dumps(o, ensure_ascii=False, separators=(",", ":")))


def chain_hook(entity: str, after: Callable[[Dict[str, Any]], None]) -> None:
    """Run ``after`` once the hook already registered for ``entity`` has run."""
    from .fields import COMPUTE_HOOKS

    before = COMPUTE_HOOKS.get(entity)

    def hook(record: Dict[str, Any]) -> None:
        if before is not None:
            before(record)
        after(record)

    COMPUTE_HOOKS[entity] = hook


def lab_board(role: str, email: str, today: Optional[date] = None) -> Dict[str, Any]:
    """Work orders with their live state, the KPIs and the test queue by category."""
    from . import records
    from .entities import ENTITIES

    today = today or date.today()
    cfg = settings()
    tests = {t["id"]: t for t in records.list_records("lab_tests")}
    entity = ENTITIES["lab_work_orders"]
    orders = [o for o in records.list_records("lab_work_orders") if records.can_see(entity, role, o, email)]
    states = []
    order_of: Dict[str, Dict[str, Any]] = {}
    for o in orders:
        s = order_state(o, tests, cfg, today)
        states.append({"id": o["id"], "number": o.get("number") or "", "project_id": o.get("project_id") or "",
                       "priority": o.get("priority") or "normal", "technician": o.get("technician") or "",
                       "received": o.get("received") or "", "reported_on": o.get("reported_on") or "", **s})
        if not o.get("cancelled"):
            for r in o.get("tests") or []:
                order_of.setdefault(str(r.get("lab_test_id")), {"id": o["id"], "number": o.get("number") or "",
                                                                "due_date": s["due_date"], "priority": o.get("priority") or "normal"})
    queue: Dict[str, List[Dict[str, Any]]] = {k: [] for k, _, _ in LAB_CATEGORIES}
    for t in tests.values():
        pending = t.get("status") != "done" or not t.get("authorised")
        if not pending:
            continue
        wo = order_of.get(t["id"])
        due = _d(wo["due_date"]) if wo else None
        queue[test_category(str(t.get("test_type") or ""))].append({
            "id": t["id"], "borehole_id": t.get("borehole_id") or "", "sample_ref": t.get("sample_ref") or "",
            "test_type": t.get("test_type") or "", "status": t.get("status") or "", "authorised": bool(t.get("authorised")),
            "stage": "review" if t.get("status") == "done" else str(t.get("status") or ""),
            "order": wo, "due_date": wo["due_date"] if wo else "", "overdue": bool(due and due < today),
            "technician": t.get("technician") or "",
        })
    for items in queue.values():
        items.sort(key=lambda x: (0 if x["overdue"] else 1, x["due_date"] or "9999", x["borehole_id"], x["sample_ref"]))
    unassigned = [t for t in tests.values() if t["id"] not in order_of and t.get("status") != "done"]
    unassigned.sort(key=lambda t: (str(t.get("project_id") or ""), str(t.get("borehole_id")), _n(t.get("depth_top"))))
    return {
        "as_of": today.isoformat(), "orders": states, "kpis": lab_kpis(states, today),
        "queue": [{"category": k, "label": CATEGORY_LABEL[k], "items": queue[k]} for k, _, _ in LAB_CATEGORIES if queue[k]],
        "unassigned": [{"id": t["id"], "project_id": t.get("project_id") or "", "borehole_id": t.get("borehole_id") or "",
                        "sample_ref": t.get("sample_ref") or "", "depth_top": t.get("depth_top"), "test_type": t.get("test_type") or "",
                        "status": t.get("status") or "", "category": test_category(str(t.get("test_type") or ""))} for t in unassigned],
        "sla": {k: int(cfg[f"sla_{k}_days"]) for k, _, _ in LAB_CATEGORIES}, "basis": cfg["lab_sla_basis"],
    }


def lab_kpis(states: List[Dict[str, Any]], today: date, months: int = 12) -> Dict[str, Any]:
    """Average turnaround and on-time share of the orders reported in the last ``months`` months;
    open, overdue and awaiting-review counts now."""
    since = add_months(today, -months)
    reported = [s for s in states if s["status"] == "reported" and s.get("turnaround_days") is not None
                and (_d(s.get("reported_on")) or today) >= since]
    timed = [s for s in reported if s.get("on_time")]
    open_ = [s for s in states if s["status"] not in ("reported", "cancelled")]
    return {
        "reported": len(reported),
        "average_turnaround_days": round(sum(s["turnaround_days"] for s in reported) / len(reported), 1) if reported else None,
        "on_time_pct": round(sum(1 for s in timed if s["on_time"] == "yes") / len(timed) * 100, 1) if timed else None,
        "open": len(open_), "overdue": sum(1 for s in open_ if s["overdue"]),
        "awaiting_review": sum(1 for s in open_ if s["status"] == "awaiting_review"),
        "in_testing": sum(1 for s in open_ if s["status"] == "in_testing"),
        "ready": sum(1 for s in open_ if s["status"] == "ready"),
        "period_months": months,
    }


def create_order_from_tests(test_ids: List[str], extra: Dict[str, Any], user: str) -> Dict[str, Any]:
    """A work order for tests requested through a laboratory instruction (sample register)."""
    from . import records

    tests = {t["id"]: t for t in records.list_records("lab_tests")}
    picked = []
    for tid in dict.fromkeys(test_ids):
        if tid not in tests:
            raise _error("A laboratory test was not found; reload the list")
        picked.append(tests[tid])
    if not picked:
        raise _error("Choose the tests for the work order")
    projects = {str(t.get("project_id") or "") for t in picked} - {""}
    if len(projects) > 1:
        raise _error("The tests belong to different projects; make one work order per project")
    received = min((str(t.get("received") or "") for t in picked if t.get("received")), default="") or date.today().isoformat()
    data = {"project_id": next(iter(projects), ""), "received": received, "priority": extra.get("priority") or "normal",
            "technician": extra.get("technician") or "", "agreed_due": extra.get("agreed_due") or "",
            "tests": [{"lab_test_id": t["id"]} for t in picked]}
    from . import docstore

    with docstore.lock(records._lock_name("lab_work_orders")):
        record = records.save("lab_work_orders", data, user)
        record["source"] = "instruction"
        docstore.write_text(records._doc("lab_work_orders", record["id"]), json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    return record


# --------------------------------------------------------------------------- #
# Menu counters and the management overview
# --------------------------------------------------------------------------- #

def summary(role: str, email: str, today: Optional[date] = None) -> Dict[str, Any]:
    from . import records
    from .entities import ENTITIES

    today = today or date.today()
    me = email.lower()
    mine = [t for t in _list("tasks") if str(t.get("assignee") or "").lower() == me and t.get("status") != "done"]
    inbox = submission_inbox(role, email)
    out: Dict[str, Any] = {
        "tasks_open": len(mine), "tasks_overdue": sum(1 for t in mine if task_overdue(t, today)),
        "submissions_waiting": sum(1 for i in inbox if i["state"] in ("submitted", "returned")),
        "submissions_open": len(inbox),
        "lab_overdue": None, "roster_warnings": None,
    }
    if role in ("admin", "manager", "lab") and records.can_read(ENTITIES["lab_work_orders"], role):
        cfg = settings()
        tests = {t["id"]: t for t in _list("lab_tests")}
        out["lab_overdue"] = sum(1 for o in _list("lab_work_orders") if order_state(o, tests, cfg, today)["overdue"])
    if role in ("admin", "manager"):
        cfg = settings()
        out["roster_warnings"] = sum(1 for r in _list("crew_deployments") if deployment_figures(r, today, cfg)["compliance"] in ("expired", "missing"))
    return out


def overview(role: str, email: str, today: Optional[date] = None) -> Dict[str, Any]:
    """Tasks, field submissions, crew and laboratory turnaround for the management dashboard."""
    from . import records
    from .entities import ENTITIES

    today = today or date.today()
    out: Dict[str, Any] = {"as_of": today.isoformat()}
    tasks = _list("tasks") if records.can_read(ENTITIES["tasks"], role) else None
    if tasks is None:
        out["tasks"] = None
    else:
        projects = {p["id"]: p for p in _list("projects")}
        per: Dict[str, Dict[str, Any]] = {}
        for t in tasks:
            if t.get("status") == "done":
                continue
            pid = str(t.get("project_id") or "")
            p = projects.get(pid) or {}
            s = per.setdefault(pid, {"project_id": pid, "code": p.get("code") or "", "name": p.get("name") or "", "open": 0, "overdue": 0})
            s["open"] += 1
            s["overdue"] += 1 if task_overdue(t, today) else 0
        out["tasks"] = {**task_summary(tasks, today),
                        "projects": sorted(per.values(), key=lambda s: (-s["overdue"], -s["open"]))[:8]}
    subs = [r for r in records.list_records("field_submissions") if records.can_see(ENTITIES["field_submissions"], role, r, email)] \
        if records.can_read(ENTITIES["field_submissions"], role) else None
    out["submissions"] = None if subs is None else {
        "by_state": {k: sum(1 for r in subs if (r.get("sub_status") or "draft") == k) for k, _ in SUB_STATES},
        "waiting": sum(1 for r in subs if r.get("sub_status") == "submitted"),
        "this_month": sum(1 for r in subs if str(r.get("submitted_at") or "")[:7] == today.isoformat()[:7]),
    }
    if records.can_read(ENTITIES["crew_deployments"], role):
        out["crew"] = roster(role, email, today=today)["totals"]
    else:
        out["crew"] = None
    if records.can_read(ENTITIES["lab_work_orders"], role):
        board = lab_board(role, email, today)
        out["lab"] = board["kpis"]
        out["lab_basis"] = board["basis"]
    else:
        out["lab"] = None
    return out
