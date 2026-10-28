"""What each kind of record holds, who may read and change it.

The same definitions validate input on the server and are sent to the browser
(``GET /api/schemas``), which builds the lists and forms from them. Labels are English;
the interface translates them.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from . import erp_commercial, sheets, sheets_lab
from .fields import ALL_ROLES, COMMERCIAL, Entity, F, Option  # noqa: F401


SERVICE_LINES: List[Option] = [
    ("geotechnical", "Geotechnical drilling"),
    ("cpt", "CPT / sondir"),
    ("geophysics", "Geophysics"),
    ("geology", "Geology"),
    ("survey", "Geodesy & mapping"),
    ("laboratory", "Laboratory testing"),
    ("analysis", "Engineering analysis"),
]

PROJECT_STATUS: List[Option] = [
    ("tender", "Tender"),
    ("contract", "Contract"),
    ("ongoing", "Ongoing"),
    ("reporting", "Reporting"),
    ("completed", "Completed"),
    ("cancelled", "Cancelled"),
]

# Laboratory: test types and the results recorded for each (see sheets_lab.py).
LAB_TESTS = sheets_lab.LAB_TESTS
LAB_RESULTS = sheets_lab.LAB_RESULTS

# Methods without their own worksheet (results are written as text and measurements).
OTHER_METHODS: List[Tuple[str, str, str]] = [
    ("seismic_refraction", "Seismic refraction", "geophysics"),
    ("masw", "MASW (surface waves)", "geophysics"),
    ("gpr", "Ground penetrating radar", "geophysics"),
    ("outcrop", "Outcrop description", "geology"),
    ("mapping", "Geological mapping", "geology"),
    ("structure", "Structural measurement (strike/dip)", "geology"),
    ("stakeout", "Stake-out of test points", "survey"),
    ("drone", "Drone / photogrammetry", "survey"),
    ("other_general", "Other", "general"),
    ("other_survey", "Other", "survey"),
    ("other_geotechnical", "Other", "geotechnical"),
    ("other", "Other", "geophysics"),
    ("other_geology", "Other", "geology"),
]


def _field_methods() -> List[Tuple[str, str, str]]:
    return [(s.key, s.label, s.group) for s in sheets.all_sheets("field")] + OTHER_METHODS


def _field_variants() -> Dict[str, List[F]]:
    return {s.key: s.fields for s in sheets.all_sheets("field") if s.fields}


def _lab_variants() -> Dict[str, List[F]]:
    return {s.key: s.fields for s in sheets.all_sheets("lab") if s.fields}


FIELD_METHODS = _field_methods()

ITEM_FIELDS = [
    F("rate_id", "ref", "From price list", ref="rates"),
    F("description", "text", "Description", required=True),
    F("unit", "text", "Unit", maxlen=20),
    F("qty", "number", "Quantity", required=True, min=0, max=1e9),
    F("unit_price", "money", "Unit price", required=True, min=0, max=1e13),
]

ENTITIES: Dict[str, Entity] = {}

CONTRACT_KINDS: List[Option] = [
    ("contract", "Contract"), ("spk", "Work order (SPK)"), ("spmk", "Notice to proceed (SPMK)"), ("subcontract", "Subcontract"),
]
COLLECTION_ACTIONS: List[Option] = [
    ("call", "Phone call"), ("email", "Email / letter"), ("visit", "Visit"), ("reminder", "Formal reminder (somasi)"),
    ("meeting", "Meeting"), ("npar", "Handed to the NPAR committee"), ("promise", "Payment promised"), ("other", "Other"),
]


WF_STATES: List[Option] = [("draft", "Draft"), ("submitted", "Waiting for review"), ("reviewed", "Waiting for approval"),
                           ("approved", "Approved"), ("returned", "Returned for correction")]


def _add(entity: Entity) -> None:
    if entity.workflow and not entity.field("wf_status"):
        entity.fields.append(F("wf_status", "select", "Approval", readonly=True, list=True, options=WF_STATES))
        entity.fields.append(F("wf_history", "json", "Approval history", readonly=True))
    ENTITIES[entity.name] = entity


_add(Entity(
    name="clients", label="Clients", label_one="Client", title="name", group="commercial", sort="name",
    fields=[
        F("name", "text", "Name", required=True, list=True),
        F("type", "select", "Type", required=True, list=True, options=[
            ("contractor", "Contractor"), ("bumn", "State-owned (BUMN)"), ("private", "Private company"),
            ("government", "Government"), ("other", "Other")]),
        F("pricing_tier", "select", "Price tier", default="client", options=[
            ("client", "Client price"), ("internal", "Internal / group price")]),
        F("contact_person", "text", "Contact person", list=True),
        F("contact_title", "text", "Contact's position"),
        F("phone", "text", "Phone", maxlen=40, list=True),
        F("email", "email", "Email"),
        F("npwp", "text", "Tax number (NPWP)", maxlen=30),
        F("address", "longtext", "Address", maxlen=500),
        F("since_year", "int", "Client since (year)", min=1900, max=2100,
          help="Empty: the year of the client's first project."),
        F("files", "files", "Documents (e.g. power of attorney for a joint operation)"),
        F("notes", "longtext", "Notes", maxlen=2000),
    ],
))

_add(Entity(
    name="projects", label="Projects", label_one="Project", title="name", group="commercial", sort="-start_date",
    fields=[
        F("code", "text", "Project code", required=True, maxlen=40, list=True),
        F("name", "text", "Project name", required=True, list=True,
          help="Borehole logs whose Project is this name belong to the project."),
        F("client_id", "ref", "Client", required=True, ref="clients", list=True),
        F("status", "select", "Status", required=True, options=PROJECT_STATUS, default="tender", list=True),
        F("leader", "user", "Project leader", list=True),
        F("location", "text", "Location"),
        F("province", "select", "Province", options=erp_commercial.PROVINCES, list=True),
        F("zone", "select", "Region zone", options=erp_commercial.ZONE_OPTIONS, readonly=True,
          help="Follows the province (company zone table)."),
        F("services", "multiselect", "Services", options=SERVICE_LINES),
        F("start_date", "date", "Start date", list=True),
        F("end_date", "date", "End date"),
        F("contract_value", "money", "Contract value (IDR)", min=0, max=1e14, private=True),
        F("notes", "longtext", "Notes", maxlen=4000),
    ],
))

BUILDUP_SECTIONS: List[Option] = [
    ("equipment", "Equipment depreciation"), ("aux", "Auxiliary tools"), ("calibration", "Calibration"),
    ("consumable", "Consumables"), ("labour", "Direct labour"), ("operations", "Operations"),
    ("overhead", "Overhead (G&A)"), ("subcontract", "Subcontract"),
]

_add(Entity(
    name="rates", label="Price list", label_one="Rate", title="description", group="finance", sort="code",
    read=COMMERCIAL, write=("admin", "manager", "finance"),
    fields=[
        F("code", "text", "Code", required=True, maxlen=20, list=True),
        F("description", "text", "Description", required=True, list=True),
        F("line", "select", "Service", options=SERVICE_LINES, list=True),
        F("unit", "text", "Unit", required=True, maxlen=20, list=True, help="e.g. m, point, sample, day, lump sum"),
        F("price", "money", "Client price (IDR)", required=True, min=0, max=1e13, list=True,
          help="Published price for external clients, before VAT."),
        F("internal_price", "money", "Internal / group price (IDR)", min=0, max=1e13, list=True,
          help="Tier 1 price; quoting below it needs approval."),
        F("min_price", "money", "Minimum selling price (IDR)", min=0, max=1e13,
          help="Quotations below this price are refused."),
        F("price_on_request", "bool", "Price on request (costing needed before quoting)"),
        F("exclusions", "text", "Standard exclusions", maxlen=300,
          help="e.g. mobilisation, transport, accommodation; printed on quotations."),
        F("buildup", "items", "Rate build-up (cost per unit)", max_items=80, section="Rate build-up", fields=[
            F("section", "select", "Cost group", required=True, options=BUILDUP_SECTIONS),
            F("description", "text", "Description", required=True),
            F("qty", "number", "Quantity", min=0, max=1e6, default=1),
            F("unit_cost", "money", "Cost (IDR)", min=0, max=1e13,
              help="Purchase cost, daily wage or annual amount."),
            F("life_hours", "number", "Hours of use / life (h)", min=0.01, max=1e7,
              help="e.g. 16 years × 365 × 8 h; 8 h for a daily wage."),
            F("residual_pct", "percent", "Residual value (%)", min=0, max=100),
            F("allocation_pct", "percent", "Allocation (%)", min=0, max=100, help="Share of an overhead account; empty = 100%."),
            F("coef", "number", "Hours per unit", min=0, max=1e5, help="8 h ÷ output per day, e.g. 0.667 h/m."),
        ]),
        F("contingency_pct", "percent", "Contingency (%)", min=0, max=50),
        F("risk_pct", "percent", "Risk premium (%)", min=0, max=20, help="Risk scale 1–5 → 1–5% of the cost."),
        F("margin_internal_pct", "percent", "Margin, internal price (%)", min=0, max=5000, default=30),
        F("margin_client_pct", "percent", "Margin, client price (%)", min=0, max=5000, default=60),
        F("rounding", "select", "Round up to", default="1000", options=[
            ("1", "1"), ("10", "10"), ("100", "100"), ("1000", "1,000"), ("10000", "10,000"), ("100000", "100,000")]),
        F("cost_unit", "money", "Cost per unit (HPJ)", readonly=True),
        F("suggested_internal", "money", "Calculated internal price", readonly=True),
        F("suggested_client", "money", "Calculated client price", readonly=True),
        F("variance_pct", "percent", "Published vs calculated (%)", readonly=True),
        F("notes", "longtext", "Notes", maxlen=2000),
    ],
))

_add(Entity(
    name="quotes", label="Quotations", label_one="Quotation", title="number", group="commercial",
    read=COMMERCIAL, number_prefix="QUO", number_field="number", sort="-date",
    fields=[
        F("number", "text", "Number", maxlen=40, list=True, help="Left empty: assigned automatically."),
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("pbd_id", "ref", "From PBD", ref="pbd", help="The Pricing & Budgeting Decision this quotation was converted from."),
        F("date", "date", "Date", required=True, list=True),
        F("valid_until", "date", "Valid until"),
        F("status", "select", "Status", required=True, default="draft", list=True, options=[
            ("draft", "Draft"), ("sent", "Sent"), ("won", "Won"), ("lost", "Lost")]),
        F("price_tier", "select", "Price tier", default="client", options=[
            ("client", "Client price"), ("internal", "Internal / group price")]),
        F("items", "items", "Items", fields=ITEM_FIELDS),
        F("discount_pct", "percent", "Discount (%)", min=0, max=100, default=0),
        F("tax_pct", "percent", "VAT / PPN (%)", min=0, max=100, default=11),
        F("mob_demob", "select", "Mobilisation / demobilisation", default="excluded", options=[
            ("excluded", "Excluded (stated in the quotation)"), ("included", "Priced in the items")]),
        F("subtotal", "money", "Subtotal", readonly=True),
        F("tax", "money", "VAT", readonly=True),
        F("total", "money", "Total", readonly=True, list=True),
        F("price_check", "text", "Price check", readonly=True, maxlen=1000),
        F("notes", "longtext", "Terms and notes", maxlen=4000),
    ],
))

_add(Entity(
    name="contracts", label="Contracts", label_one="Contract", title="number", group="commercial",
    read=COMMERCIAL, sort="-date", workflow=True,
    fields=[
        F("number", "text", "Contract number", required=True, maxlen=60, list=True),
        F("kind", "select", "Document", default="contract", list=True, options=CONTRACT_KINDS,
          help="SPMK and subcontracts are not counted in the client's contract value."),
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("pbd_id", "ref", "PBD", ref="pbd"),
        F("parent_contract_id", "ref", "Main contract", ref="contracts", help="For an SPMK, a subcontract or an amendment."),
        F("date", "date", "Signed on", required=True, list=True),
        F("value", "money", "Contract value (IDR, incl. VAT)", required=True, min=0, max=1e14, list=True,
          help="For an SPMK: the value of the contract it starts. For a subcontract: the value paid to the subcontractor."),
        F("status", "select", "Status", required=True, default="draft", list=True, options=[
            ("draft", "Draft"), ("signed", "Signed"), ("amended", "Amended"), ("closed", "Closed")]),
        F("start_date", "date", "Work starts"),
        F("end_date", "date", "Work ends"),
        F("client_signatory", "text", "Signed for the client"),
        F("our_signatory", "text", "Signed for us"),
        F("subcontractor", "text", "Subcontractor"),
        F("subcontractor_contact", "text", "Subcontractor contact"),
        F("subcontract_scope", "longtext", "Subcontracted work", maxlen=4000),
        F("retention_pct", "percent", "Retention (%)", min=0, max=100, help="Held back from each payment until the maintenance period ends."),
        F("late_penalty_permille", "number", "Late penalty (‰ of the value per day)", min=0, max=100),
        F("penalty_cap_pct", "percent", "Penalty cap (% of the value)", min=0, max=100),
        F("terms", "items", "Payment terms", fields=[
            F("name", "text", "Term", required=True, help="e.g. Down payment, Field work done, Final report"),
            F("percent", "percent", "Share (%)", required=True, min=0, max=100),
            F("condition", "text", "Due when"),
        ], max_items=20),
        F("files", "files", "Documents"),
        F("notes", "longtext", "Notes / legal remarks", maxlen=4000),
    ],
))

_add(Entity(
    name="cpt", label="CPT / sondir", label_one="CPT test", title="test_id", group="field", sort="-date",
    write=("admin", "manager"), own_write=("general",),
    fields=[
        F("test_id", "text", "Test ID", required=True, maxlen=40, list=True),
        F("project_id", "ref", "Project", ref="projects", list=True),
        F("date", "date", "Date", required=True, list=True),
        F("equipment", "select", "Equipment", default="mechanical", options=[
            ("mechanical", "Mechanical (Begemann, 2.5 t)"), ("electric", "Electric CPT"), ("cptu", "CPTu (piezocone)")]),
        F("latitude", "number", "Latitude", min=-90, max=90),
        F("longitude", "number", "Longitude", min=-180, max=180),
        F("elevation", "number", "Ground elevation (mRL)", min=-1000, max=9000),
        F("final_depth", "number", "Final depth (m)", min=0, max=200, list=True),
        F("gw_depth", "number", "Groundwater depth (m)", min=0, max=200),
        F("operator", "text", "Operator"),
        F("qc", "select", "Field QC", default="pending", list=True, options=[
            ("pending", "Waiting for QC"), ("passed", "QC passed"), ("redo", "Redo / repeat")]),
        F("checked_by", "user", "Checked by"),
        F("qc_unit", "select", "Units of qc and fs", default="kgcm2", options=[
            ("kgcm2", "qc and fs in kg/cm² (mechanical sondir)"), ("mpa_kpa", "qc in MPa, fs in kPa (electric CPT / CPTu)"),
            ("mpa", "qc and fs in MPa")]),
        F("area_ratio", "number", "Cone area ratio a", min=0.3, max=1, default=0.8),
        F("unit_weight", "number", "Average unit weight γ (kN/m³)", min=10, max=25, default=18),
        F("nkt", "number", "Cone factor Nkt", min=5, max=30, default=15),
        F("readings", "items", "Readings", max_items=3000, fields=[
            F("depth", "number", "Depth (m)", required=True, min=0, max=200),
            F("qc", "number", "qc", required=True, min=0, max=2000),
            F("fs", "number", "fs", min=0, max=5000),
            F("u2", "number", "u2 (kPa)", min=-500, max=10000),
        ]),
        F("dissipation_depth", "number", "Dissipation test depth (m)", min=0, max=200),
        F("rigidity_index", "number", "Rigidity index Ir", min=10, max=1000, default=100),
        F("dissipation", "items", "Dissipation readings", max_items=1000, fields=[
            F("time", "number", "Time (s)", required=True, min=0, max=1e6),
            F("u2", "number", "u2 (kPa)", required=True, min=-500, max=10000),
        ]),
        F("results", "json", "Interpretation", readonly=True),
        F("summary", "text", "Result", readonly=True, list=True, maxlen=300),
        F("files", "files", "Files"),
        F("remarks", "longtext", "Remarks", maxlen=2000),
    ],
))

_add(Entity(
    name="field_activities", label="Field worksheets", label_one="Field worksheet", title="code", group="field",
    sort="-date", write=("admin", "manager"), own_write=("general",),
    fields=[
        F("code", "text", "Document / point ID", required=True, maxlen=60, list=True,
          help="e.g. the point, line or borehole ID, or DR-2026-10-26 for a daily report."),
        F("type", "select", "Discipline", required=True, list=True,
          options=[(value, label) for value, label, _ in sheets.FIELD_GROUPS]),
        F("method", "select", "Worksheet", required=True, list=True, options=FIELD_METHODS, options_filter="type"),
        F("project_id", "ref", "Project", ref="projects", list=True),
        F("borehole_id", "text", "Borehole", maxlen=64),
        F("date", "date", "Date", required=True, list=True),
        F("latitude", "number", "Latitude", min=-90, max=90),
        F("longitude", "number", "Longitude", min=-180, max=180),
        F("elevation", "number", "Elevation (mRL)", min=-1000, max=9000),
        F("length", "number", "Line length (m)", min=0, max=100000),
        F("crew", "text", "Crew"),
        F("standard", "text", "Standard", maxlen=300),
        F("data", "json", "Worksheet", variants_by="method", variants=_field_variants()),
        F("results_calc", "json", "Calculated results", readonly=True),
        F("summary", "text", "Result", readonly=True, list=True, maxlen=300),
        F("results", "longtext", "Results / interpretation", maxlen=6000,
          help="e.g. layers and velocities, resistivity zones, lithology, strike/dip, coordinates and accuracy."),
        F("values", "items", "Measurements", max_items=500, fields=[
            F("name", "text", "Parameter", required=True, maxlen=60),
            F("value", "text", "Value", required=True, maxlen=60),
            F("unit", "text", "Unit", maxlen=20),
        ]),
        F("files", "files", "Files"),
        F("qc", "select", "Field QC", default="pending", list=True, options=[
            ("pending", "Waiting for QC"), ("passed", "QC passed"), ("redo", "Redo / repeat")]),
        F("checked_by", "user", "Checked by"),
    ],
))

_add(Entity(
    name="lab_tests", label="Laboratory tests", label_one="Lab test", title="sample_ref", group="lab",
    sort="-received", write=("admin", "manager", "lab"), own_write=("general",),
    fields=[
        F("borehole_id", "text", "Borehole", required=True, maxlen=64, list=True),
        F("sample_ref", "text", "Sample", required=True, maxlen=40, list=True, help="e.g. UDS-1"),
        F("depth_top", "number", "From (m)", required=True, min=0, max=500, list=True),
        F("depth_base", "number", "To (m)", min=0, max=500),
        F("test_type", "select", "Test", required=True, options=LAB_TESTS, list=True),
        F("status", "select", "Status", required=True, default="received", list=True, options=[
            ("requested", "Requested"), ("received", "Received"), ("testing", "Testing"), ("done", "Done")]),
        F("received", "date", "Received on", list=True),
        F("tested", "date", "Tested on"),
        F("technician", "text", "Technician"),
        F("checked_by", "user", "Checked by"),
        F("project_id", "ref", "Project", ref="projects"),
        F("standard", "text", "Standard", maxlen=300, help="e.g. SNI 1965:2008, ASTM D2216"),
        F("raw", "json", "Test data", variants_by="test_type", variants=_lab_variants()),
        F("calc", "json", "Calculated results", readonly=True),
        F("summary", "text", "Result", readonly=True, list=True, maxlen=300),
        F("results", "json", "Results", variants_by="test_type", variants=LAB_RESULTS),
        F("files", "files", "Lab sheets"),
        F("remarks", "longtext", "Remarks", maxlen=2000),
        # Laboratory quality (ISO/IEC 17025:2017, see erp_lab.py): sample receipt, equipment used, authorisation.
        F("receipt_id", "ref", "Sample receipt", ref="sample_receipts", section="Quality",
          help="Empty: linked automatically to the receipt of the same borehole and sample."),
        F("equipment_used", "items", "Equipment used", max_items=20, section="Quality", fields=[
            F("equipment_id", "ref", "Equipment", required=True, ref="equipment"),
            F("note", "text", "Note", maxlen=120),
        ], help="Measuring equipment that affects the result; its calibration on the test date is checked."),
        F("uncertainty", "text", "Measurement uncertainty", maxlen=200, section="Quality",
          help="When it matters for the result or the customer asks: expanded uncertainty with its coverage factor, "
               "e.g. ±0.4 % moisture (k = 2, about 95 %). ISO/IEC 17025 7.6 and 7.8.3.1 c."),
        F("authorised", "bool", "Results reviewed and authorised", section="Quality",
          help="Tick when the results have been reviewed and may be released. Changing the results afterwards clears it."),
        F("authorised_by", "user", "Authorised by", readonly=True),
        F("authorised_at", "date", "Authorised on", readonly=True),
        F("results_entered_by", "user", "Results entered by", readonly=True),
        F("result_status", "select", "Release", readonly=True, list=True, options=[
            ("in_progress", "Not finished"), ("awaiting", "Awaiting authorisation"), ("authorised", "Authorised")]),
        F("report_disclaimer", "text", "Disclaimer for the report", readonly=True, maxlen=600),
        F("calibration_check", "json", "Calibration on the test date", readonly=True),
        F("warnings", "json", "Checks", readonly=True),
        F("warning_count", "int", "Warnings", readonly=True),
    ],
))

_add(Entity(
    name="analyses", label="Engineering analyses", label_one="Analysis", title="title", group="analysis",
    fields=[
        F("title", "text", "Title", required=True, list=True),
        F("project_id", "ref", "Project", ref="projects", list=True),
        F("borehole_id", "text", "Borehole", maxlen=64, list=True),
        F("type", "select", "Analysis", required=True, list=True, options=[
            ("bearing", "Shallow foundation bearing capacity"),
            ("pile", "Pile capacity from SPT (Decourt)"),
            ("settlement", "Consolidation settlement"),
            ("liquefaction", "Liquefaction (SPT, Idriss & Boulanger)"),
            ("bearing_table", "Bearing capacity table (several widths and depths)"),
            ("site_class", "Seismic site class and design spectrum (SNI 1726:2019)"),
            ("spt_correction", "SPT corrections N60 and (N1)60"),
            ("retaining_wall", "Retaining wall stability (overturning, sliding, bearing)"),
            ("slope", "Slope stability (Bishop circular slip, infinite slope)")]),
        F("inputs", "json", "Inputs"),
        F("results", "json", "Results", readonly=True),
        F("summary", "text", "Result", readonly=True, list=True, maxlen=300),
        F("engineer", "user", "Engineer"),
        F("notes", "longtext", "Notes", maxlen=4000),
    ],
))

_add(Entity(
    name="project_reports", label="Reports & recommendations", label_one="Report", title="number", group="analysis",
    number_prefix="RPT", number_field="number", sort="-date",
    fields=[
        F("number", "text", "Report number", maxlen=40, list=True, help="Left empty: assigned automatically."),
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("title", "text", "Title", required=True, list=True),
        F("date", "date", "Date", required=True, list=True),
        F("status", "select", "Status", required=True, default="draft", list=True, options=[
            ("draft", "Draft"), ("review", "In review"), ("approved", "Approved"), ("sent", "Sent to client")]),
        F("summary", "longtext", "Summary", maxlen=8000),
        F("scope", "longtext", "Scope of work", maxlen=8000),
        F("recommendations", "longtext", "Recommendations", maxlen=12000),
        F("prepared_by", "user", "Prepared by"),
        F("reviewed_by", "user", "Reviewed by"),
        F("approved_by", "user", "Approved by"),
        F("files", "files", "Attachments"),
    ],
))

_add(Entity(
    name="invoices", label="Invoices", label_one="Invoice", title="number", group="finance",
    read=COMMERCIAL, write=("admin", "finance"), number_prefix="INV", number_field="number", sort="-date",
    fields=[
        F("number", "text", "Invoice number", maxlen=40, list=True, help="Left empty: assigned automatically."),
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("contract_id", "ref", "Contract", ref="contracts"),
        F("term", "text", "Payment term", help="e.g. Down payment 30%"),
        F("date", "date", "Invoice date", required=True, list=True),
        F("due_date", "date", "Due date", list=True),
        F("items", "items", "Items", fields=ITEM_FIELDS),
        F("tax_pct", "percent", "VAT / PPN (%)", min=0, max=100, default=11),
        F("pph_pct", "percent", "Withholding PPh 23 (%)", min=0, max=100, default=2,
          help="Withheld by the client; shown for information."),
        F("payments", "items", "Payments received", max_items=50, fields=[
            F("date", "date", "Date", required=True),
            F("amount", "money", "Amount", required=True, min=0, max=1e14),
            F("method", "text", "Method / reference", maxlen=80),
        ]),
        F("collection_notes", "items", "Collection notes", max_items=200, section="Collection", fields=[
            F("date", "date", "Date", required=True),
            F("action", "select", "Action", required=True, options=COLLECTION_ACTIONS),
            F("note", "text", "Note", required=True, maxlen=500),
            F("next_date", "date", "Follow up on"),
            F("by", "text", "By", maxlen=254),
        ]),
        F("status", "select", "Status", required=True, default="draft", list=True, options=[
            ("draft", "Draft"), ("sent", "Sent"), ("cancelled", "Cancelled")]),
        F("subtotal", "money", "Subtotal", readonly=True),
        F("tax", "money", "VAT", readonly=True),
        F("total", "money", "Total", readonly=True, list=True),
        F("pph", "money", "PPh 23 withheld", readonly=True),
        F("paid", "money", "Paid", readonly=True),
        F("outstanding", "money", "Outstanding", readonly=True, list=True),
        F("payment_status", "select", "Payment", readonly=True, list=True, options=[
            ("unpaid", "Unpaid"), ("partial", "Partly paid"), ("paid", "Paid"), ("overdue", "Overdue")]),
        F("notes", "longtext", "Notes", maxlen=2000),
    ],
))

_add(Entity(
    name="settings", label="Company settings", label_one="Company settings", title="company_name", group="admin",
    write=("admin",), singleton=True,
    fields=[
        F("company_name", "text", "Company name", required=True),
        F("address", "longtext", "Address", maxlen=500),
        F("phone", "text", "Phone", maxlen=40),
        F("email", "email", "Email"),
        F("npwp", "text", "Tax number (NPWP)", maxlen=30),
        F("bank", "longtext", "Bank account for invoices", maxlen=400,
          help="Bank name, account number and account holder, printed on invoices."),
        F("signatory", "text", "Signatory name"),
        F("signatory_title", "text", "Signatory title"),
        F("report_footer", "longtext", "Report footer / disclaimer", maxlen=2000),
        F("self_signup", "bool", "Account requests from the sign-in page", default=True,
          help="People can ask for an account on the sign-in page; nobody gets in until an administrator approves the request under Users and chooses the role."),
        F("approval_separation", "bool", "Different people for drafting, review and approval", default=True,
          help="Turn off only when the company is too small for three people in the approval flow."),
        F("difficulty_factors", "items", "Project difficulty factors", max_items=30, section="Pricing policy", fields=[
            F("key", "text", "Code", maxlen=30, help="Short code; \"zone\" is scored from the region zone."),
            F("factor", "text", "Factor", required=True),
            F("weight", "number", "Weight", min=0, max=100),
            F("level_1", "text", "1 Very easy"),
            F("level_2", "text", "2 Easy"),
            F("level_3", "text", "3 Fairly easy"),
            F("level_4", "text", "4 Difficult"),
            F("level_5", "text", "5 Very difficult"),
        ], help="Empty: the 16 company default factors with equal weights (to be confirmed by the pricing committee)."),
        F("risk_premium_table", "items", "Risk premium by difficulty index", max_items=5, section="Pricing policy", fields=[
            F("index", "int", "Difficulty index", required=True, min=1, max=5),
            F("premium_pct", "percent", "Risk premium (%)", required=True, min=0, max=100),
        ], help="Empty: company defaults 5, 8, 11, 14 and 17% for index 1 to 5 (to be confirmed by the pricing committee)."),
        F("default_margin_pct", "percent", "Default margin (% of the ABP)", min=0, max=500,
          help="Empty: 30% (company default, to be confirmed by the pricing committee)."),
        F("max_cost_ratio_pct", "percent", "Maximum cost ratio ABP / project revenue (%)", min=1, max=100,
          help="Empty: 75% (company default, to be confirmed by the pricing committee)."),
        F("approval_limits", "items", "Approval authority by bid value", max_items=10, section="Pricing policy", fields=[
            F("up_to", "money", "Bid value below (IDR)", min=0, max=1e15, help="Empty on the last row: no upper limit."),
            F("level", "text", "Approved by", required=True),
        ], help="Empty: below 2 bn approver 1; 2–5 bn approvers 1 and 2; 5–10 bn approvers 1, 2 and 3; above 10 bn approvers 1 to 4."),
        F("npar_days", "int", "Receivables move to the NPAR committee after (days since the invoice)", min=30, max=720,
          help="Empty: 90 days."),
        F("default_payment_days", "int", "Payment period when an invoice has no due date (days)", min=0, max=365,
          help="Empty: 30 days."),
        F("guarantee_warning_days", "int", "Warn before a guarantee expires (days)", min=1, max=365, help="Empty: 30 days."),
    ],
))


def public_schema() -> Dict[str, Any]:
    """Definitions for the browser."""
    out: Dict[str, Any] = {}
    for name, entity in ENTITIES.items():
        data = asdict(entity)
        out[name] = data
    return out


# ERP modules (blueprint A.1–A.5): each file adds its entities with _add and its calculations to COMPUTE_HOOKS.
from . import entities_commercial, entities_ops  # noqa: E402,F401
