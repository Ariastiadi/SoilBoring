"""ERP entities (commercial, blueprint A.1): Pricing & Budgeting Decision, client decision,
weekly work plan and budget drawdown, bank guarantee / SKBDN requests. The calculations are in
erp_commercial.py; the hooks below run them on every save (see fields.COMPUTE_HOOKS).

Approval flow on each document: drafted by commercial staff (Konseptor), reviewed by a manager
(Pengulas), approved by the pricing committee / an administrator (Pemutus)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import erp_commercial as calc
from .entities import COMMERCIAL, ENTITIES, SERVICE_LINES, Entity, F, _add
from .fields import COMPUTE_HOOKS

REVIEWERS = ("admin", "manager")
APPROVERS = ("admin",)

PBD_SERVICES = [
    ("geotechnical", "Geotechnical investigation"), ("topography", "Topography"), ("laboratory", "Laboratory"),
    ("supervision", "Supervision"), ("design_analysis", "Geotechnical design and analysis"), ("advisory", "Advisory"),
]
PROCUREMENT = [("tender", "Tender"), ("direct", "Direct appointment")]
ROUNDING = [("1000", "1,000"), ("10000", "10,000"), ("100000", "100,000"), ("1000000", "1,000,000")]
PAYMENT_TERM_FIELDS = [
    F("name", "text", "Term", required=True, help="e.g. Down payment, Field work done, Final report"),
    F("percent", "percent", "Share (%)", required=True, min=0, max=100),
    F("condition", "text", "Due when"),
]

_add(Entity(
    name="pbd", label="Pricing & Budgeting Decisions", label_one="PBD", title="number", group="commercial",
    read=COMMERCIAL, write=("admin", "manager"), number_prefix="PBD", number_field="number", sort="-date",
    workflow=True, reviewers=REVIEWERS, approvers=APPROVERS,
    fields=[
        F("number", "text", "PBD number", maxlen=40, list=True, help="Left empty: assigned automatically."),
        F("date", "date", "Date", required=True, list=True),
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("client_id", "ref", "Client", ref="clients", readonly=True),
        F("procurement", "select", "Procurement method", options=PROCUREMENT, default="tender"),
        F("amendment", "bool", "For a contract amendment"),
        F("proposal_number", "text", "Proposal number", maxlen=60),
        F("project_manager", "user", "Project manager"),
        F("province", "select", "Province", options=calc.PROVINCES, help="Taken from the project when left empty."),
        F("zone", "select", "Region zone", options=calc.ZONE_OPTIONS, help="Follows the province when left empty."),
        F("location", "text", "Project location"),
        F("scope", "select", "Scope", options=[("full", "Full scope"), ("partial", "Partial")], default="partial"),
        F("services", "multiselect", "Services", options=PBD_SERVICES),
        F("duration_weeks", "int", "Duration (weeks)", min=1, max=520),
        F("start_date", "date", "Planned start"),
        F("difficulty", "items", "Difficulty index scoring", max_items=40, section="Difficulty index", fields=[
            F("key", "text", "Factor code", maxlen=30),
            F("factor", "text", "Factor", maxlen=200),
            F("score", "int", "Score (1–5)", min=1, max=5),
            F("note", "text", "Note", maxlen=200),
        ]),
        F("risk_pct_override", "percent", "Risk premium set by the committee (%)", min=0, max=100,
          help="Leave empty to take the premium from the difficulty index."),
        F("margin_pct", "percent", "Margin (% of the ABP)", min=0, max=500),
        F("tax_pct", "percent", "VAT / PPN (%)", min=0, max=100, default=11),
        F("rounding", "select", "Round the bid price up to", options=ROUNDING, default="1000"),
        F("cost_reference", "select", "Government cost reference", options=calc.COST_REFERENCES,
          help="Checks the price against the government rules: AHSP construction work adds 10–15% indirect cost "
               "(overhead and profit) to the direct cost; consultancy keeps direct cost at most 40% of the contract value. "
               "Empty: company pricing only."),
        F("conversion", "select", "Conversion to client rates", default="spread", options=[
            ("spread", "Spread project costs over the work items"), ("separate", "Each budget line as its own item")],
          help="How the quotation is built from this PBD. Mobilisation and demobilisation are always separate items."),
        F("costs", "items", "Cost budget lines", max_items=300, section="Cost budget", fields=[
            F("section", "select", "Cost group", required=True, options=calc.SECTIONS),
            F("rate_id", "ref", "From price list", ref="rates"),
            F("description", "text", "Description", required=True),
            F("unit", "text", "Unit", maxlen=20),
            F("qty", "number", "Quantity", required=True, min=0, max=1e9),
            F("days", "number", "Days", min=0, max=1e5, help="Empty = 1."),
            F("unit_cost", "money", "Unit cost (HPJ, IDR)", min=0, max=1e13,
              help="Empty on a price-list line: the unit cost (HPJ) of its rate build-up."),
        ]),
        F("technical_review", "longtext", "Technical review", maxlen=4000),
        F("legal_review", "longtext", "Legal review", maxlen=4000),
        F("risk_review", "longtext", "Risk management review", maxlen=4000),
        F("files", "files", "Supporting documents"),
        F("notes", "longtext", "Notes", maxlen=4000),
        F("difficulty_score", "number", "Difficulty score", readonly=True),
        F("difficulty_index", "int", "Difficulty index", readonly=True, list=True),
        F("risk_premium_pct", "percent", "Risk premium (%)", readonly=True),
        F("abp", "money", "Project cost budget (ABP)", readonly=True, list=True),
        F("risk_amount", "money", "Risk premium amount", readonly=True),
        F("margin_amount", "money", "Margin amount", readonly=True),
        F("bid_price", "money", "Bid price (excl. VAT)", readonly=True, list=True),
        F("bid_with_vat", "money", "Bid price incl. VAT", readonly=True),
        F("min_client_price", "money", "Minimum client price", readonly=True),
        F("price_list_value", "money", "Price-list value of the work items", readonly=True),
        F("cost_ratio_pct", "percent", "Cost ratio ABP/revenue (%)", readonly=True),
        F("max_cost_ratio_pct", "percent", "Company maximum ratio (%)", readonly=True),
        F("indirect_pct", "percent", "Risk premium and margin (% of the ABP)", readonly=True),
        F("approval_level", "text", "Approval authority", readonly=True),
        F("checks", "json", "Checks", readonly=True),
        F("result", "json", "Calculation", readonly=True),
    ],
))

_add(Entity(
    name="client_decisions", label="Client decisions", label_one="Client decision", title="number", group="commercial",
    read=COMMERCIAL, write=("admin", "manager"), number_prefix="CD", number_field="number", sort="-date",
    workflow=True, reviewers=REVIEWERS, approvers=APPROVERS,
    fields=[
        F("number", "text", "Number", maxlen=40, list=True, help="Left empty: assigned automatically."),
        F("date", "date", "Date", required=True, list=True),
        F("pbd_id", "ref", "PBD", ref="pbd", list=True,
          help="The project, location, proposed price, minimum price and difficulty index are taken from the PBD."),
        F("project_id", "ref", "Project", ref="projects", list=True, help="Taken from the PBD when left empty."),
        F("client_id", "ref", "Client", ref="clients", readonly=True),
        F("procurement", "select", "Procurement method", options=PROCUREMENT),
        F("amendment", "bool", "Contract amendment"),
        F("proposal_number", "text", "Proposal number", maxlen=60),
        F("project_manager", "user", "Project manager"),
        F("scope_description", "longtext", "Description of work", maxlen=6000),
        F("location", "text", "Project location"),
        F("field_situation", "longtext", "Location and field situation", maxlen=4000,
          help="Access, terrain, soil, water depth, HSE rules, land status: what the site visit found."),
        F("service_levels", "items", "Service quality level", max_items=30, fields=[
            F("standard", "text", "Service standard", required=True),
            F("level", "text", "Service level"),
            F("deadline", "text", "Deadline"),
            F("penalty", "text", "Consequence / penalty"),
        ]),
        F("price_max", "money", "Highest price, e.g. owner's estimate (IDR)", min=0, max=1e14),
        F("decided_price", "money", "Decided offer price (IDR, excl. VAT)", min=0, max=1e14, list=True,
          help="Price approved by the pricing committee; not below the minimum client price."),
        F("terms", "longtext", "Terms and conditions", maxlen=8000),
        F("duration_days", "int", "Project duration (days)", min=1, max=5000),
        F("duration_basis", "select", "Days counted as", default="calendar", options=[
            ("calendar", "Calendar days"), ("working", "Working days")]),
        F("start_date", "date", "Work starts"),
        F("end_date", "date", "Work ends"),
        F("report_date", "date", "Report due"),
        F("offering_no", "text", "Offer number", maxlen=60),
        F("spk_no", "text", "SPK / LOI number", maxlen=60),
        F("contract_no", "text", "Contract number", maxlen=60),
        F("payment_terms", "items", "Payment terms", max_items=20, fields=PAYMENT_TERM_FIELDS),
        F("files", "files", "Attachments (tender documents, site photos)"),
        F("notes", "longtext", "Notes", maxlen=4000),
        F("proposed_price", "money", "Proposed price from the PBD", readonly=True),
        F("price_min", "money", "Minimum client price", readonly=True),
        F("zone", "select", "Region zone", options=calc.ZONE_OPTIONS, readonly=True),
        F("difficulty_index", "int", "Difficulty index", readonly=True),
        F("risk_premium_pct", "percent", "Risk premium (%)", readonly=True),
        F("approval_level", "text", "Approval authority", readonly=True),
        F("checks", "json", "Checks", readonly=True),
        F("result", "json", "Calculation", readonly=True),
    ],
))

WP_GROUPS = [
    ("geotechnical", "Geotechnical"), ("topography", "Topography"), ("supervision", "Supervision"),
    ("design_analysis", "Design and analysis"), ("field_lab", "Field laboratory tests"), ("laboratory", "Laboratory"),
    ("mobilisation", "Mobilisation / demobilisation"), ("reporting", "Reporting"), ("other", "Other"),
]

_add(Entity(
    name="work_plans", label="Weekly work plans", label_one="Weekly work plan", title="number", group="commercial",
    read=COMMERCIAL, write=("admin", "manager"), number_prefix="WP", number_field="number", sort="-date",
    workflow=True, reviewers=REVIEWERS, approvers=APPROVERS,
    fields=[
        F("number", "text", "Number", maxlen=40, list=True, help="Left empty: assigned automatically."),
        F("date", "date", "Date", required=True, list=True),
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("pbd_id", "ref", "PBD", ref="pbd", help="The budget and the duration are checked against this PBD."),
        F("site_manager", "user", "Site manager"),
        F("start_date", "date", "Week 1 starts"),
        F("activities", "items", "Activities (Gantt)", max_items=100, section="Work plan", fields=[
            F("group", "select", "Group", options=WP_GROUPS),
            F("activity", "text", "Activity", required=True),
            F("start_week", "int", "Start week", required=True, min=1, max=520),
            F("end_week", "int", "End week", required=True, min=1, max=520),
            F("weight_pct", "percent", "Weight (%)", min=0, max=100),
            F("progress_pct", "percent", "Done (%)", min=0, max=100),
        ]),
        F("weeks", "items", "Weekly budget and progress", max_items=520, section="Weekly budget", fields=[
            F("week", "int", "Week", required=True, min=1, max=520),
            F("planned_pct", "percent", "Planned progress (%)", min=0, max=100, help="This week's share of the work."),
            F("budget_plan", "money", "Budget plan (IDR)", min=0, max=1e13),
            F("drawdown", "money", "Drawdown requested (IDR)", min=0, max=1e13),
            F("realised", "money", "Realised cost (IDR)", min=0, max=1e13),
            F("actual_pct", "percent", "Actual progress (%)", min=0, max=100),
            F("notes", "text", "Notes", maxlen=300),
        ]),
        F("files", "files", "Receipts and supporting documents"),
        F("notes", "longtext", "Notes", maxlen=4000),
        F("duration_weeks", "int", "Duration (weeks)", readonly=True),
        F("pbd_budget", "money", "PBD budget (ABP)", readonly=True),
        F("pbd_weeks", "int", "PBD duration (weeks)", readonly=True),
        F("revenue", "money", "Project revenue (PBD bid price)", readonly=True),
        F("total_plan", "money", "Budget plan", readonly=True, list=True),
        F("total_drawdown", "money", "Drawdown requested", readonly=True),
        F("total_realised", "money", "Realised cost", readonly=True, list=True),
        F("report_week", "int", "Reported up to week", readonly=True),
        F("planned_to_date", "percent", "Planned progress to date (%)", readonly=True),
        F("actual_to_date", "percent", "Actual progress to date (%)", readonly=True, list=True),
        F("deviation", "number", "Deviation (percentage points)", readonly=True),
        F("cost_ratio_pct", "percent", "Cost ratio ABP/revenue (%)", readonly=True),
        # Earned value at the reporting week (see erp_commercial.earned_value).
        F("bac", "money", "Budget at completion (BAC)", readonly=True),
        F("bac_source", "select", "BAC taken from", readonly=True, options=[
            ("plan", "Weekly budget plan"), ("pbd", "PBD budget (ABP)")]),
        F("pv", "money", "Planned value (PV)", readonly=True),
        F("ev", "money", "Earned value (EV)", readonly=True),
        F("ac", "money", "Actual cost (AC)", readonly=True),
        F("cv", "money", "Cost variance (CV)", readonly=True),
        F("sv", "money", "Schedule variance (SV)", readonly=True),
        F("cpi", "number", "CPI", readonly=True, list=True),
        F("spi", "number", "SPI", readonly=True, list=True),
        F("eac", "money", "Estimate at completion (EAC)", readonly=True),
        F("etc", "money", "Estimate to complete (ETC)", readonly=True),
        F("vac", "money", "Variance at completion (VAC)", readonly=True),
        F("tcpi", "number", "TCPI", readonly=True),
        F("checks", "json", "Checks", readonly=True),
        F("result", "json", "Calculation", readonly=True),
    ],
))

GUARANTEE_TYPES = [
    ("performance", "Performance bond (jaminan pelaksanaan)"), ("advance", "Advance payment bond (jaminan uang muka)"),
    ("skbdn", "SKBDN (domestic letter of credit)"), ("bid", "Bid bond (jaminan penawaran)"),
    ("maintenance", "Maintenance / retention bond"),
]

_add(Entity(
    name="guarantees", label="Bank guarantees & SKBDN", label_one="Guarantee request", title="number", group="commercial",
    read=COMMERCIAL, write=("admin", "manager", "finance"), number_prefix="BG", number_field="number", sort="-date",
    workflow=True, reviewers=REVIEWERS, approvers=APPROVERS,
    fields=[
        F("number", "text", "Request number", maxlen=40, list=True, help="Left empty: assigned automatically."),
        F("date", "date", "Request date", required=True),
        F("type", "select", "Type", required=True, options=GUARANTEE_TYPES, list=True),
        F("direction", "select", "Direction", options=[
            ("issued", "Issued by our bank for the client"), ("received", "Received from the client's bank")],
          help="Empty: an SKBDN is received from the client (payment security), a bank guarantee is issued for the client."),
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("contract_id", "ref", "Contract", ref="contracts"),
        F("beneficiary", "text", "Beneficiary", help="Empty: the client, or the company for an SKBDN received."),
        F("required_pct", "percent", "Required (% of the contract value)", min=0, max=100,
          help="e.g. 5% for a performance bond; fills the amount when it is empty."),
        F("amount", "money", "Amount (IDR)", min=0, max=1e14, list=True),
        F("bank", "text", "Bank / issuer"),
        F("guarantee_no", "text", "Guarantee / SKBDN number", maxlen=80),
        F("issue_date", "date", "Issued on"),
        F("expiry_date", "date", "Valid until", list=True),
        F("claim_days", "int", "Claim period after expiry (days)", min=0, max=365),
        F("fee_pct", "percent", "Bank fee (% of the amount)", min=0, max=20),
        F("collateral_pct", "percent", "Cash collateral (% of the amount)", min=0, max=100),
        F("status", "select", "Status", required=True, default="requested", list=True, options=[
            ("requested", "Requested"), ("issued", "Issued / in force"), ("released", "Returned / released"),
            ("claimed", "Claimed"), ("cancelled", "Cancelled")]),
        F("files", "files", "Documents (memo, contract, draft wording)"),
        F("notes", "longtext", "Notes", maxlen=4000),
        F("pct_of_contract", "percent", "Share of the contract value (%)", readonly=True),
        F("fee_amount", "money", "Bank fee", readonly=True),
        F("collateral_amount", "money", "Cash collateral", readonly=True),
        F("expiry_status", "select", "Expiry", readonly=True, list=True, options=[
            ("ok", "Valid"), ("expiring", "Expires soon"), ("expired", "Expired")]),
        F("checks", "json", "Checks", readonly=True),
    ],
))


# --------------------------------------------------------------------------- #
# Hooks: run inside the save (see records.compute)
# --------------------------------------------------------------------------- #

def _get(entity: str, record_id: Any) -> Optional[Dict[str, Any]]:
    from . import records

    if not record_id:
        return None
    try:
        return records.get_record(entity, str(record_id))
    except records.NotFound:
        return None


def _settings() -> Optional[Dict[str, Any]]:
    from . import records

    return records.get_singleton("settings")


def _guard(fn: Any, *args: Any) -> None:
    """Calculation errors refuse the save with a readable message (HTTP 422)."""
    from . import records

    try:
        fn(*args)
    except calc.CommercialError as exc:
        raise records.RecordError(str(exc)) from exc


def _pbd(record: Dict[str, Any]) -> None:
    from . import records

    rates = {r["id"]: r for r in records.list_records("rates")}
    project = _get("projects", record.get("project_id"))
    _guard(calc.pbd_compute, record, rates, _settings(), project, _get("clients", (project or {}).get("client_id")))


def _client_decision(record: Dict[str, Any]) -> None:
    from . import records

    pbd = _get("pbd", record.get("pbd_id"))
    if pbd and not record.get("project_id"):
        record["project_id"] = pbd.get("project_id") or ""
    if not record.get("project_id"):
        raise records.RecordError("Choose the PBD or the project")
    _guard(calc.client_decision_compute, record, pbd, _get("projects", record.get("project_id")), _settings())


def _work_plan(record: Dict[str, Any]) -> None:
    _guard(calc.work_plan_compute, record, _get("pbd", record.get("pbd_id")), _settings())


def _guarantee(record: Dict[str, Any]) -> None:
    contract = _get("contracts", record.get("contract_id"))
    project = _get("projects", record.get("project_id"))
    client = _get("clients", (project or {}).get("client_id"))
    _guard(calc.guarantee_compute, record, contract, client, _settings())


def _project(record: Dict[str, Any]) -> None:
    record["zone"] = calc.PROVINCE_ZONE.get(str(record.get("province") or ""), "")


# Commercial policy fields of the company settings (the settings entity itself is in entities.py).
_SETTINGS_EXTRA = [
    F("evm_warning_index", "number", "Warn when CPI or SPI falls below", min=0.5, max=1, section="Pricing policy",
      help="Earned value of the weekly work plans. Empty: 0.90 (values between this and 0.95 are flagged to watch)."),
    F("ecl_rates", "items", "Expected credit loss rates by days overdue", max_items=7, section="Pricing policy", fields=[
        F("bucket", "select", "Days overdue", required=True, options=calc.ECL_BUCKETS),
        F("rate_pct", "percent", "Loss rate (%)", required=True, min=0, max=100),
    ], help="Indicative loss allowance on client receivables (PSAK 109 simplified approach, provision matrix). "
            "Empty: example rates 1, 2, 5, 10, 25, 50 and 100%, to be set by finance from the company's own loss history."),
]
_settings_entity = ENTITIES["settings"]
for _f in _SETTINGS_EXTRA:
    if not _settings_entity.field(_f.name):
        _settings_entity.fields.append(_f)

COMPUTE_HOOKS.update({"pbd": _pbd, "client_decisions": _client_decision, "work_plans": _work_plan,
                      "guarantees": _guarantee, "projects": _project})

SERVICE_LABELS: Dict[str, str] = dict(SERVICE_LINES)
