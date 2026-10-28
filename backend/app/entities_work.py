"""Work coordination entities: project tasks with phase templates, field submissions (field → office
hand-off), the crew deployment roster and laboratory work orders with turnaround targets.

Calculations are in :mod:`erp_work` and run on every save through COMPUTE_HOOKS; the live views
(my tasks, submission inbox, roster, laboratory board, counters) are in routers/erp_work.py.
Imported at the end of entities.py.
"""
from __future__ import annotations

from typing import Any, Dict

from . import erp_work
from .entities import ENTITIES, SERVICE_LINES, Entity, F, _add
from .fields import ALL_ROLES, COMPUTE_HOOKS, LOCK_HOOKS

WARNINGS = F("warnings", "json", "Checks", readonly=True)
WARNING_COUNT = F("warning_count", "int", "Warnings", readonly=True, list=True)

_add(Entity(
    name="tasks", label="Project tasks", label_one="Task", title="title", group="work", sort="due_date",
    read=ALL_ROLES, write=("admin", "manager"), own_write=("general", "lab", "finance"),
    fields=[
        F("title", "text", "Task", required=True, maxlen=160, list=True),
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("phase", "select", "Phase", default="other", options=erp_work.PHASES, list=True),
        F("service", "select", "Service", options=SERVICE_LINES),
        F("assignee", "user", "Assigned to", list=True),
        F("priority", "select", "Priority", default="normal", options=erp_work.TASK_PRIORITY),
        F("status", "select", "Status", required=True, default="todo", options=erp_work.TASK_STATUS, list=True),
        F("start_date", "date", "Start"),
        F("due_date", "date", "Due", list=True),
        F("description", "longtext", "Description", maxlen=4000),
        F("blocked_reason", "text", "Why it is blocked", maxlen=300),
        F("checklist", "items", "Checklist", max_items=40, fields=[
            F("item", "text", "Item", required=True, maxlen=200),
            F("done", "bool", "Done"),
        ]),
        F("borehole_id", "text", "Borehole", maxlen=64, section="Links"),
        F("field_activity_id", "ref", "Field worksheet", ref="field_activities", section="Links"),
        F("lab_test_id", "ref", "Laboratory test", ref="lab_tests", section="Links"),
        F("completed_at", "date", "Completed on", readonly=True),
        F("checklist_done", "int", "Checklist items done", readonly=True),
        F("checklist_pct", "percent", "Checklist done (%)", readonly=True),
        F("template_key", "text", "Standard task", readonly=True),
        F("generated_title", "text", "Standard title", readonly=True),
        F("sequence", "int", "Order", readonly=True),
        F("history", "json", "Status history", readonly=True),
        WARNINGS, WARNING_COUNT,
        F("files", "files", "Files"),
    ],
))

_add(Entity(
    name="field_submissions", label="Field submissions", label_one="Field submission", title="number", group="field",
    sort="-date", read=("admin", "manager", "general", "lab"), write=("admin",), own_write=("general", "manager", "lab"),
    own_read=("general",), number_prefix="FS", number_field="number",
    fields=[
        F("number", "text", "Number", maxlen=40, list=True, help="Left empty: assigned automatically (FS-year-number)."),
        F("date", "date", "Work date", required=True, list=True),
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("daily_report_id", "ref", "Daily report", ref="field_activities",
          help="The daily report worksheet of this day (Field worksheets, 01.03)."),
        F("boreholes", "items", "Borehole logs", max_items=50, fields=[
            F("borehole_id", "text", "Borehole", required=True, maxlen=64),
            F("note", "text", "Note", maxlen=200, help="e.g. drilled 12.5 to 20 m today, log finished"),
        ]),
        F("worksheets", "items", "Field worksheets", max_items=100, fields=[
            F("activity_id", "ref", "Worksheet", required=True, ref="field_activities"),
            F("note", "text", "Note", maxlen=200),
        ]),
        F("cpt_tests", "items", "CPT / sondir", max_items=50, fields=[
            F("cpt_id", "ref", "CPT test", required=True, ref="cpt"),
            F("note", "text", "Note", maxlen=200),
        ]),
        F("samples_included", "bool", "Samples sent to the laboratory",
          help="The laboratory receives this package too."),
        F("sample_count", "int", "Number of samples", min=0, max=1000),
        F("sample_note", "text", "Samples and how they were sent", maxlen=300, help="e.g. 6 UDS and 10 SPT bags, by the project pickup."),
        F("note", "longtext", "Note to the office", maxlen=2000),
        F("files", "files", "Attachments", help="Photos of the log sheets, site photos, scans."),
        F("sub_status", "select", "Status", readonly=True, list=True, options=erp_work.SUB_STATES),
        F("recipients", "select", "Sent to", readonly=True, options=[("office", "Office"), ("office_lab", "Office and laboratory")]),
        F("item_count", "int", "Items", readonly=True, list=True),
        F("submitted_at", "text", "Sent on", readonly=True),
        F("done_at", "text", "Done on", readonly=True),
        F("resubmissions", "int", "Sent again after return", readonly=True),
        F("sub_history", "json", "History", readonly=True),
        WARNINGS, WARNING_COUNT,
    ],
))

_add(Entity(
    name="crew_deployments", label="Crew roster", label_one="Crew deployment", title="person_name", group="operations",
    sort="-deploy_start", read=("admin", "manager", "general", "finance"), write=("admin", "manager"),
    fields=[
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("person_name", "text", "Name", required=True, maxlen=120, list=True),
        F("position", "select", "Position", required=True, options=erp_work.POSITIONS, list=True),
        F("employer_type", "select", "Employment", required=True, default="permanent", options=erp_work.EMPLOYER_TYPES),
        F("employer", "text", "Employer / subcontractor", maxlen=120, help="For subcontracted or hired crew."),
        F("phone", "text", "Phone", maxlen=40),
        F("emergency_name", "text", "Emergency contact", maxlen=120),
        F("emergency_phone", "text", "Emergency contact phone", maxlen=40),
        F("deploy_start", "date", "Deployed from", required=True, list=True),
        F("deploy_end", "date", "Deployed to", list=True, help="Empty while the end is not known."),
        F("location", "text", "Work location", maxlen=120),
        F("accommodation", "select", "Accommodation", options=erp_work.ACCOMMODATION),
        F("mobilisation_id", "ref", "Mobilisation", ref="mobilisations"),
        F("medical_expiry", "date", "Medical clearance valid until", section="Safety documents"),
        F("induction_date", "date", "Safety induction on", section="Safety documents",
          help="Valid for the months set in Operations settings (default 12)."),
        F("daily_rate", "money", "Daily rate (IDR)", min=0, max=1e10, private=True,
          help="Seen only by administrators, managers and finance."),
        F("notes", "longtext", "Notes", maxlen=2000),
        F("deployment_status", "select", "On site", readonly=True, list=True, options=erp_work.DEPLOY_STATUS),
        F("man_days", "number", "Man-days to date", readonly=True),
        F("planned_man_days", "number", "Planned man-days", readonly=True),
        F("cost_to_date", "money", "Cost to date", readonly=True, private=True),
        F("induction_valid_until", "date", "Induction valid until", readonly=True),
        F("compliance", "select", "Safety documents", readonly=True, list=True, options=erp_work.COMPLIANCE),
        WARNINGS, WARNING_COUNT,
        F("files", "files", "Documents", help="Medical certificate, induction record, ID card copy."),
    ],
))

_add(Entity(
    name="lab_work_orders", label="Laboratory work orders", label_one="Lab work order", title="number", group="lab",
    sort="-received", read=("admin", "manager", "lab", "finance"), write=("admin", "manager", "lab"),
    number_prefix="LWO", number_field="number",
    fields=[
        F("number", "text", "Number", maxlen=40, list=True, help="Left empty: assigned automatically (LWO-year-number)."),
        F("project_id", "ref", "Project", ref="projects", list=True),
        F("client_id", "ref", "Client", ref="clients", help="Empty: the project's client."),
        F("received", "date", "Received on", required=True, list=True),
        F("priority", "select", "Priority", default="normal", list=True, options=[("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")]),
        F("technician", "user", "Technician", list=True),
        F("tests", "items", "Samples and tests", max_items=300, fields=[
            F("lab_test_id", "ref", "Laboratory test", required=True, ref="lab_tests"),
            F("note", "text", "Note", maxlen=200),
        ], help="Laboratory tests of the samples; the work order follows their status and authorisation."),
        F("agreed_due", "date", "Due date agreed", help="Empty: received date plus the turnaround days of the slowest test (Operations settings)."),
        F("instructions", "longtext", "Customer instructions", maxlen=2000),
        F("reported_on", "date", "Reported on", help="The date the laboratory report was issued."),
        F("report_ref", "text", "Report no.", maxlen=60),
        F("cancelled", "bool", "Cancelled"),
        F("source", "select", "Created from", readonly=True, options=[("instruction", "Laboratory instruction"), ("manual", "By hand")]),
        F("status", "select", "Status", readonly=True, list=True, options=erp_work.LWO_STATUS),
        F("sla_days", "int", "Turnaround target (days)", readonly=True),
        F("due_date", "date", "Due", readonly=True, list=True),
        F("progress_pct", "percent", "Progress (%)", readonly=True, list=True),
        F("test_count", "int", "Tests", readonly=True),
        F("tests_done", "int", "Tests done", readonly=True),
        F("tests_authorised", "int", "Tests authorised", readonly=True),
        F("turnaround_days", "number", "Turnaround (days)", readonly=True),
        F("on_time", "select", "On time", readonly=True, options=[("yes", "Yes"), ("no", "No")]),
        F("by_category", "json", "Tests by category", readonly=True),
        WARNINGS, WARNING_COUNT,
        F("files", "files", "Documents", help="Customer request, laboratory report."),
    ],
))


# Turnaround targets and crew document warnings live in the operations settings.
_SETTINGS_EXTRA = [
    F("lab_sla_basis", "select", "Count turnaround in", default="working", section="Laboratory turnaround", options=[
        ("working", "Working days (Monday to Friday)"), ("calendar", "Calendar days")],
      help="Public holidays are not counted out; agree the due date by hand around them."),
    *[F(f"sla_{key}_days", "int", f"Turnaround: {label} (days)", min=1, max=365, default=days, section="Laboratory turnaround")
      for key, label, days in erp_work.LAB_CATEGORIES],
    F("crew_warning_days", "int", "Warn this many days before a medical clearance or induction expires", min=0, max=180, default=14,
      section="Crew roster"),
    F("induction_valid_months", "int", "Safety induction valid for (months)", min=1, max=60, default=12, section="Crew roster"),
]
_ops_settings = ENTITIES["ops_settings"]
for _f in _SETTINGS_EXTRA:
    if not _ops_settings.field(_f.name):
        _ops_settings.fields.append(_f)


def _source(record: Dict[str, Any]) -> None:
    record.setdefault("source", "manual")
    erp_work.compute_lab_order(record)


def _project_tasks(record: Dict[str, Any]) -> None:
    """A project entering the contract or ongoing stage gets its standard phase tasks (never twice)."""
    if record.get("status") not in erp_work.TRIGGER_STATUSES:
        return
    previous = erp_work._previous("projects", record)
    if previous.get("status") in erp_work.TRIGGER_STATUSES:
        return
    erp_work.create_standard_tasks(record, str(record.get("updated_by") or ""), pending=not previous)


COMPUTE_HOOKS.update({
    "tasks": erp_work.compute_task,
    "field_submissions": erp_work.compute_submission,
    "crew_deployments": erp_work.compute_deployment,
    "lab_work_orders": _source,
})
erp_work.chain_hook("projects", _project_tasks)
erp_work.chain_hook("lab_tests", erp_work.refresh_orders_for_test)
LOCK_HOOKS["field_submissions"] = erp_work.submission_lock
LOCK_HOOKS.setdefault("projects", erp_work.project_delete_guard)
