"""ERP entities (operations): blueprint A.4 Logistic & General Affair, A.5 Maintenance, the
procurement card (Kartu Procurement), the fixed asset card (Kartu Aktiva Tetap) and the individual
work plan & performance card (Kartu Rencana Kerja & Kinerja Individual).

Calculations are in :mod:`erp_ops` and run on every save through COMPUTE_HOOKS; the live views
(due lists, equipment status, procurement stage, overview) are in routers/erp_ops.py.
"""
from __future__ import annotations

from typing import List

from . import erp_ops
from .entities import Entity, F, _add
from .fields import ALL_ROLES, COMMERCIAL, COMPUTE_HOOKS, Option

OPS = ("admin", "manager")

EQUIPMENT_CATEGORIES: List[Option] = [
    ("drill_rig", "Drill rig"), ("cpt_rig", "CPT / sondir rig"), ("pump", "Pump"),
    ("survey", "Survey instrument"), ("geophysics", "Geophysics instrument"), ("lab", "Laboratory equipment"),
    ("vehicle", "Vehicle"), ("other", "Other"),
]

EQUIPMENT_STATUS: List[Option] = [
    ("available", "Available"), ("mobilised", "Mobilised"), ("maintenance", "In maintenance"),
    ("broken", "Broken"), ("disposed", "Disposed"),
]

DUE_STATUS: List[Option] = [("ok", "OK"), ("due_soon", "Due soon"), ("overdue", "Overdue"), ("missing", "No record yet")]

MOB_STATUS: List[Option] = [
    ("planned", "Planned"), ("in_transit", "In transit to site"), ("on_site", "On site"),
    ("demobilising", "Demobilising"), ("returned", "Returned to base"), ("cancelled", "Cancelled"),
]

TRANSPORT: List[Option] = [
    ("truck", "Truck"), ("pickup", "Pickup / car"), ("boat", "Boat / barge"), ("train", "Train"),
    ("air", "Air freight"), ("combined", "Combined"), ("other", "Other"),
]

WO_TYPES: List[Option] = [
    ("preventive", "Preventive (scheduled service)"), ("corrective", "Corrective (repair)"),
    ("calibration", "Calibration"), ("inspection", "Inspection"),
]

WO_STATUS: List[Option] = [
    ("open", "Not started"), ("scheduled", "Scheduled"), ("in_progress", "In progress"),
    ("waiting_parts", "Waiting for parts"), ("completed", "Completed"), ("cancelled", "Cancelled"),
]

VENDOR_CATEGORIES: List[Option] = [
    ("rental", "Equipment rental"), ("parts", "Spare parts"), ("calibration", "Calibration laboratory"),
    ("workshop", "Workshop / service"), ("transport", "Transport / logistics"), ("consumables", "Consumables"),
    ("lab_supplies", "Laboratory supplies"), ("subcontract", "Subcontractor"), ("office_it", "Office / IT"),
    ("other", "Other"),
]

COST_CENTRES: List[Option] = [
    ("project", "Project"), ("field_ops", "Field operations"), ("laboratory", "Laboratory"),
    ("workshop", "Workshop & maintenance"), ("office", "Office / general affair"), ("it", "IT"),
]

PO_STATUS: List[Option] = [("draft", "Draft"), ("issued", "Issued to vendor"), ("closed", "Closed"), ("cancelled", "Cancelled")]

PO_PROGRESS: List[Option] = [
    ("draft", "Draft"), ("ordered", "Ordered"), ("partly_received", "Partly received"), ("received", "Received"),
    ("invoiced", "Invoiced"), ("paid", "Paid"), ("closed", "Closed"), ("cancelled", "Cancelled"),
]

ASSET_CATEGORIES: List[Option] = [
    ("land", "Land plot"), ("building_permanent", "Building, permanent"), ("building_nonpermanent", "Building, non-permanent"),
    ("drilling", "Drilling & CPT equipment"), ("instruments", "Survey, geophysics & testing instruments"),
    ("lab", "Laboratory equipment"), ("vehicle", "Vehicles"), ("office_it", "Office equipment & computers"),
    ("furniture", "Furniture & fittings"), ("other", "Other"),
]

TAX_GROUPS: List[Option] = [
    ("g1", "Non-building group 1 (4 years)"), ("g2", "Non-building group 2 (8 years)"),
    ("g3", "Non-building group 3 (16 years)"), ("g4", "Non-building group 4 (20 years)"),
    ("building_permanent", "Permanent building (20 years)"), ("building_nonpermanent", "Non-permanent building (10 years)"),
    ("none", "Not depreciated (land)"),
]

TAX_METHODS: List[Option] = [("straight_line", "Straight line"), ("declining", "Declining balance")]

BOOK_METHODS: List[Option] = [
    ("same_as_tax", "Same as tax"), ("straight_line", "Straight line"),
    ("declining", "Double declining balance"), ("none", "Not depreciated"),
]

ASSET_STATUS: List[Option] = [("active", "In use"), ("fully_depreciated", "Fully depreciated"), ("disposed", "Disposed"), ("not_depreciated", "Not depreciated")]

DISPOSAL_TYPES: List[Option] = [("sale", "Sale"), ("scrap", "Scrapped"), ("loss", "Lost / damaged (insurance)"), ("transfer", "Transfer / donation")]

PERSPECTIVES: List[Option] = [
    ("financial", "Financial"), ("customer", "Customer"), ("internal", "Internal process"), ("learning", "Learning & growth"),
]

POLARITY: List[Option] = [("higher", "Higher is better"), ("lower", "Lower is better")]

PERIOD_TYPES: List[Option] = [("annual", "Annual"), ("semester", "Semester"), ("quarter", "Quarter")]

RATINGS: List[Option] = [
    ("outstanding", "Exceptional"), ("very_good", "Very good"), ("good", "Good"),
    ("needs_improvement", "Needs improvement"), ("unsatisfactory", "Unsatisfactory"),
]

WARNINGS = F("warnings", "json", "Checks", readonly=True)
WARNING_COUNT = F("warning_count", "int", "Warnings", readonly=True, list=True)


# --------------------------------------------------------------------------- #
# Settings of the operations modules
# --------------------------------------------------------------------------- #

_add(Entity(
    name="ops_settings", label="Operations settings", label_one="Operations settings", title="name", group="operations",
    write=("admin",), singleton=True,
    fields=[
        F("name", "text", "Name", default="Operations settings", maxlen=60),
        F("two_quotes_from", "money", "Two quotations needed from (IDR)", min=0, max=1e13, default=10_000_000,
          help="Purchases from this value need at least two quotations."),
        F("three_quotes_from", "money", "Three quotations needed from (IDR)", min=0, max=1e13, default=50_000_000,
          help="Purchases from this value need at least three quotations."),
        F("wo_approval_limit", "money", "Work order cost needing a purchase request (IDR)", min=0, max=1e13, default=25_000_000,
          help="Work orders above this cost should go through a procurement card with approval."),
        F("due_soon_days", "int", "Warn this many days before a service or calibration is due", min=0, max=365, default=30),
        F("due_soon_hours", "number", "Warn this many hour-meter hours before a service is due", min=0, max=10000, default=50),
        F("weight_quality", "percent", "Weight: quality of goods or work (%)", min=0, max=100, default=30, section="Vendor evaluation"),
        F("weight_delivery", "percent", "Weight: delivery on time and complete (%)", min=0, max=100, default=25, section="Vendor evaluation"),
        F("weight_price", "percent", "Weight: price and terms (%)", min=0, max=100, default=20, section="Vendor evaluation"),
        F("weight_hse", "percent", "Weight: HSE, legal and document compliance (%)", min=0, max=100, default=15, section="Vendor evaluation"),
        F("weight_responsiveness", "percent", "Weight: responsiveness and service (%)", min=0, max=100, default=10, section="Vendor evaluation"),
        F("vendor_approved_from", "percent", "Approved from score (%)", min=0, max=100, default=75, section="Vendor evaluation"),
        F("vendor_conditional_from", "percent", "Conditional from score (%)", min=0, max=100, default=60, section="Vendor evaluation",
          help="Below this score the vendor is blocked."),
        F("vendor_reevaluate_months", "int", "Re-evaluate vendors every (months)", min=1, max=60, default=12, section="Vendor evaluation"),
        F("lab_authorisation", "select", "Lab results not yet authorised", default="warn", section="Laboratory", options=[
            ("warn", "Allow marking the test done, with a warning"), ("require", "Refuse marking the test done")],
          help="ISO/IEC 17025 7.8.1.1: results are reviewed and authorised before release."),
    ],
))


# --------------------------------------------------------------------------- #
# A.4 Logistic & General Affair: vendors, equipment register, mobilisation
# --------------------------------------------------------------------------- #

_add(Entity(
    name="vendors", label="Vendors", label_one="Vendor", title="name", group="operations", sort="name",
    write=("admin", "manager", "finance"),
    fields=[
        F("name", "text", "Name", required=True, list=True),
        F("category", "select", "Category", required=True, options=VENDOR_CATEGORIES, list=True),
        F("contact_person", "text", "Contact person", list=True),
        F("phone", "text", "Phone", maxlen=40, list=True),
        F("email", "email", "Email"),
        F("address", "longtext", "Address", maxlen=500),
        F("npwp", "text", "Tax number (NPWP)", maxlen=30, private=True),
        F("bank_name", "text", "Bank", maxlen=80, private=True),
        F("bank_account", "text", "Account number", maxlen=40, private=True),
        F("bank_holder", "text", "Account holder", maxlen=120, private=True),
        F("rating", "select", "Rating", list=True, options=[
            ("5", "5 – Excellent"), ("4", "4 – Good"), ("3", "3 – Adequate"), ("2", "2 – Poor"), ("1", "1 – Do not use")],
          help="Quality, price, delivery time and service of past orders."),
        F("active", "bool", "Active", default=True, list=True),
        F("notes", "longtext", "Notes", maxlen=2000),
        F("files", "files", "Documents", help="e.g. company deed, NIB, NPWP, bank letter, price list."),
    ],
))

SCORE_1_5: List[Option] = [("5", "5 – Excellent"), ("4", "4 – Good"), ("3", "3 – Adequate"), ("2", "2 – Poor"), ("1", "1 – Unacceptable")]

VENDOR_OUTCOMES: List[Option] = [("approved", "Approved"), ("conditional", "Conditional"), ("blocked", "Blocked")]

_add(Entity(
    name="vendor_evaluations", label="Vendor evaluations", label_one="Vendor evaluation", title="vendor_id", group="operations",
    sort="-date", read=ALL_ROLES, write=("admin", "manager", "finance"), own_write=("general", "lab"),
    fields=[
        F("vendor_id", "ref", "Vendor", required=True, ref="vendors", list=True),
        F("date", "date", "Evaluated on", required=True, list=True),
        F("period_from", "date", "Period from"),
        F("period_to", "date", "Period to"),
        F("evaluator", "user", "Evaluated by"),
        F("basis", "longtext", "Basis of the evaluation", maxlen=2000,
          help="Orders, deliveries, inspections, incidents and complaints reviewed."),
        F("score_quality", "select", "Quality of goods or work", options=SCORE_1_5, section="Scores"),
        F("score_delivery", "select", "Delivery on time and complete", options=SCORE_1_5, section="Scores"),
        F("score_price", "select", "Price and terms", options=SCORE_1_5, section="Scores"),
        F("score_hse", "select", "HSE, legal and document compliance", options=SCORE_1_5, section="Scores",
          help="Safety record on site, permits and licences, tax and company documents, and sustainability."),
        F("score_responsiveness", "select", "Responsiveness and service", options=SCORE_1_5, section="Scores"),
        F("critical_issue", "bool", "Serious breach (blocks the vendor whatever the score)", section="Scores",
          help="e.g. a serious safety incident, fraud or bribery, falsified documents."),
        F("critical_note", "text", "What happened", maxlen=300, section="Scores"),
        F("actions", "longtext", "Improvement actions agreed", maxlen=2000),
        F("score_pct", "percent", "Score (%)", readonly=True, list=True),
        F("outcome", "select", "Outcome", readonly=True, list=True, options=VENDOR_OUTCOMES),
        F("next_evaluation", "date", "Next evaluation due", readonly=True),
        F("weights", "json", "Weights used", readonly=True),
        WARNINGS, WARNING_COUNT,
        F("files", "files", "Evidence"),
    ],
))

_add(Entity(
    name="equipment", label="Equipment register", label_one="Equipment", title="name", group="operations", sort="code",
    write=OPS,
    fields=[
        F("code", "text", "Equipment code", required=True, maxlen=40, list=True, help="e.g. DR-01, SD-03, TS-02"),
        F("name", "text", "Name", required=True, list=True),
        F("category", "select", "Category", required=True, options=EQUIPMENT_CATEGORIES, list=True),
        F("brand", "text", "Brand", maxlen=80),
        F("model", "text", "Model / type", maxlen=80),
        F("serial", "text", "Serial number", maxlen=80),
        F("status", "select", "Status", required=True, default="available", options=EQUIPMENT_STATUS, list=True,
          help="Set by hand. While the equipment is on an active mobilisation it is shown as mobilised there."),
        F("location", "text", "Location", list=True, help="Base, warehouse or site."),
        F("project_id", "ref", "Current project", ref="projects"),
        F("custodian", "user", "Person in charge"),
        F("in_service_date", "date", "In service since", help="Start of the service schedule when no service has been recorded yet."),
        F("hour_meter", "number", "Hour meter (h)", min=0, max=1e6),
        F("hour_meter_date", "date", "Hour meter read on"),
        F("calibration_months", "int", "Calibration interval (months)", min=0, max=120, section="Calibration",
          help="Empty for equipment that needs no calibration."),
        F("last_calibration", "date", "Last calibration", section="Calibration",
          help="A completed calibration work order updates the due date too."),
        F("calibration_cert", "text", "Last calibration certificate no.", maxlen=80, section="Calibration"),
        F("service_days", "int", "Service interval (days)", min=0, max=3650, section="Servicing"),
        F("service_hours", "number", "Service interval (hour meter, h)", min=0, max=100000, section="Servicing"),
        F("last_service_date", "date", "Last service", section="Servicing",
          help="A completed preventive work order updates the due date too."),
        F("last_service_hours", "number", "Hour meter at last service (h)", min=0, max=1e6, section="Servicing"),
        F("asset_id", "ref", "Fixed asset", ref="fixed_assets", help="The fixed asset card of this equipment."),
        F("next_calibration_due", "date", "Next calibration due", readonly=True, list=True),
        F("next_service_due", "date", "Next service due", readonly=True, list=True),
        F("next_service_hours", "number", "Next service at (h)", readonly=True),
        F("notes", "longtext", "Notes", maxlen=2000),
        F("files", "files", "Documents & photos", help="e.g. manual, calibration certificates, photos."),
    ],
))

_add(Entity(
    name="mobilisations", label="Mobilisation & demobilisation", label_one="Mobilisation", title="number",
    group="operations", sort="-date", write=OPS, own_write=("general",), number_prefix="MOB", number_field="number",
    fields=[
        F("number", "text", "Number", maxlen=40, list=True, help="Left empty: assigned automatically."),
        F("date", "date", "Request date", required=True),
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("status", "select", "Status", required=True, default="planned", options=MOB_STATUS, list=True),
        F("from_location", "text", "From (base)", default="Base"),
        F("to_location", "text", "To (site)", required=True),
        F("planned_mob_date", "date", "Planned mobilisation", list=True),
        F("actual_mob_date", "date", "Arrived on site"),
        F("planned_demob_date", "date", "Planned demobilisation"),
        F("actual_demob_date", "date", "Back at base"),
        F("equipment", "items", "Equipment", max_items=60, fields=[
            F("equipment_id", "ref", "Equipment", required=True, ref="equipment"),
            F("note", "text", "Note", maxlen=120),
        ]),
        F("crew", "items", "Crew", max_items=60, fields=[
            F("name", "text", "Name", required=True, maxlen=80),
            F("role", "text", "Role", maxlen=60, help="e.g. driller, helper, CPT operator, site engineer"),
            F("phone", "text", "Phone", maxlen=40),
        ]),
        F("transport_mode", "select", "Transport", options=TRANSPORT),
        F("vehicle", "text", "Vehicle / carrier", maxlen=120),
        F("mob_cost", "money", "Mobilisation transport cost (IDR)", min=0, max=1e13, private=True),
        F("demob_cost", "money", "Demobilisation transport cost (IDR)", min=0, max=1e13, private=True),
        F("other_cost", "money", "Other costs (IDR)", min=0, max=1e13, private=True, help="Loading, permits, escort, crew travel."),
        F("total_cost", "money", "Total cost", readonly=True, list=True, private=True),
        F("equipment_count", "int", "Equipment items", readonly=True),
        F("planned_days", "int", "Planned days on site", readonly=True),
        F("actual_days", "int", "Days on site", readonly=True),
        WARNINGS, WARNING_COUNT,
        F("notes", "longtext", "Notes", maxlen=2000),
        F("files", "files", "Documents", help="e.g. delivery note, loading checklist, photos."),
    ],
))


# --------------------------------------------------------------------------- #
# A.5 Maintenance: work orders
# --------------------------------------------------------------------------- #

_add(Entity(
    name="work_orders", label="Maintenance work orders", label_one="Maintenance work order", title="number", group="operations",
    sort="-date", write=OPS, own_write=("general", "lab"), number_prefix="WO", number_field="number",
    fields=[
        F("number", "text", "Number", maxlen=40, list=True, help="Left empty: assigned automatically."),
        F("equipment_id", "ref", "Equipment", required=True, ref="equipment", list=True),
        F("type", "select", "Type", required=True, options=WO_TYPES, list=True),
        F("priority", "select", "Priority", default="normal", options=[
            ("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent – equipment down")]),
        F("status", "select", "Status", required=True, default="open", options=WO_STATUS, list=True),
        F("date", "date", "Reported on", required=True, list=True),
        F("planned_date", "date", "Planned for"),
        F("start_date", "date", "Work started"),
        F("completed_date", "date", "Completed on"),
        F("hour_meter", "number", "Hour meter (h)", min=0, max=1e6, help="Reading when the work was done."),
        F("description", "longtext", "Problem / work requested", required=True, maxlen=4000),
        F("work_done", "longtext", "Work done", maxlen=4000),
        F("performed_by", "select", "Done by", default="internal", options=[("internal", "Own workshop"), ("vendor", "Vendor")]),
        F("technician", "text", "Technician", maxlen=120),
        F("vendor_id", "ref", "Vendor", ref="vendors"),
        F("parts", "items", "Parts and materials", max_items=100, fields=[
            F("part", "text", "Part / material", required=True),
            F("qty", "number", "Quantity", required=True, min=0, max=1e6),
            F("unit", "text", "Unit", maxlen=20),
            F("unit_cost", "money", "Unit cost (IDR)", min=0, max=1e13),
        ]),
        F("labour_cost", "money", "Labour cost (IDR)", min=0, max=1e13),
        F("vendor_cost", "money", "Vendor / service cost (IDR)", min=0, max=1e13),
        F("downtime_days", "number", "Downtime (days)", min=0, max=3650,
          help="Empty: counted from work started to completed."),
        F("calibration_result", "select", "Calibration result", options=[("pass", "Pass"), ("adjusted", "Adjusted, then pass"), ("fail", "Fail")]),
        F("certificate_no", "text", "Certificate no.", maxlen=80),
        F("procurement_id", "ref", "Procurement card", ref="procurements",
          help="Purchase request for parts or vendor work above the approval limit."),
        F("parts_cost", "money", "Parts cost", readonly=True),
        F("total_cost", "money", "Total cost", readonly=True, list=True),
        F("downtime", "number", "Downtime (days)", readonly=True),
        F("next_calibration_due", "date", "Next calibration due", readonly=True),
        WARNINGS, WARNING_COUNT,
        F("files", "files", "Documents & photos", help="e.g. job sheet, certificate, invoice, photos."),
    ],
))


# --------------------------------------------------------------------------- #
# Procurement card: purchase request -> quotations -> approval -> purchase orders
# --------------------------------------------------------------------------- #

_add(Entity(
    name="procurements", label="Procurement cards", label_one="Procurement card", title="number", group="operations",
    sort="-date", read=ALL_ROLES, write=("admin", "manager", "finance"), own_write=("general", "lab"),
    own_read=("general", "lab"), owner_field="requester",
    number_prefix="PR", number_field="number", workflow=True,
    reviewers=("admin", "manager", "finance"), approvers=("admin",),
    fields=[
        F("number", "text", "PR number", maxlen=40, list=True, help="Left empty: assigned automatically (PR-year-number)."),
        F("date", "date", "Request date", required=True, list=True),
        F("title", "text", "What is needed", required=True, list=True, maxlen=160),
        F("requester", "user", "Requested by", list=True),
        F("cost_centre", "select", "Cost centre", required=True, default="project", options=COST_CENTRES),
        F("project_id", "ref", "Project", ref="projects"),
        F("needed_by", "date", "Needed by"),
        F("justification", "longtext", "Reason for the purchase", maxlen=2000),
        F("budget", "money", "Budget available (IDR)", min=0, max=1e14, help="From the project budget (PBD) or the annual budget."),
        F("items", "items", "Items requested", max_items=100, section="Purchase request", fields=[
            F("description", "text", "Item", required=True),
            F("spec", "text", "Specification", maxlen=200),
            F("unit", "text", "Unit", maxlen=20),
            F("qty", "number", "Quantity", required=True, min=0, max=1e9),
            F("est_price", "money", "Estimated unit price (IDR)", min=0, max=1e13),
        ]),
        F("quotations", "items", "Quotations received", max_items=20, section="Quotations", fields=[
            F("vendor_id", "ref", "Vendor", ref="vendors"),
            F("vendor_name", "text", "Vendor (if not registered)", maxlen=120),
            F("quote_ref", "text", "Quotation no.", maxlen=60),
            F("quote_date", "date", "Date"),
            F("amount", "money", "Total incl. VAT (IDR)", min=0, max=1e14),
            F("delivery_days", "int", "Delivery (days)", min=0, max=3650),
            F("terms", "text", "Payment terms / warranty", maxlen=160),
            F("chosen", "bool", "Chosen"),
        ]),
        F("selection_reason", "longtext", "Reason for the choice", maxlen=2000,
          help="Required when the chosen quotation is not the lowest."),
        F("exception_reason", "longtext", "Reason for fewer quotations", maxlen=2000,
          help="Sole supplier, emergency repair, continuation of an existing contract, etc."),
        F("coi_status", "select", "Conflict of interest", section="Conflict of interest", options=[
            ("none", "None: no one choosing the vendor has an interest in it"), ("declared", "Declared")],
          help="Family, ownership, employment or gifts linking anyone who chooses or approves the vendor to it."),
        F("coi_details", "longtext", "Who has what interest", maxlen=2000, section="Conflict of interest"),
        F("coi_mitigation", "longtext", "How it is handled", maxlen=2000, section="Conflict of interest",
          help="e.g. the person takes no part in choosing or approving, an extra reviewer is added."),
        F("coi_by", "user", "Declared by", section="Conflict of interest"),
        F("coi_date", "date", "Declared on", section="Conflict of interest"),
        F("cancelled", "bool", "Cancelled"),
        F("files", "files", "Quotations & documents"),
        F("est_total", "money", "Estimated total", readonly=True),
        F("quote_count", "int", "Quotations", readonly=True),
        F("required_quotes", "int", "Quotations required", readonly=True),
        F("lowest_amount", "money", "Lowest quotation", readonly=True),
        F("chosen_vendor", "text", "Chosen vendor", readonly=True),
        F("chosen_vendor_id", "text", "Chosen vendor record", readonly=True),
        F("chosen_vendor_status", "select", "Chosen vendor's evaluation", readonly=True, options=[
            *VENDOR_OUTCOMES, ("not_evaluated", "Not evaluated yet")]),
        F("approved_amount", "money", "Amount to approve", readonly=True, list=True),
        WARNINGS, WARNING_COUNT,
        F("notes", "longtext", "Notes", maxlen=2000),
    ],
))

_add(Entity(
    name="purchase_orders", label="Purchase orders", label_one="Purchase order", title="number", group="operations",
    sort="-date", read=COMMERCIAL, write=("admin", "manager", "finance"), number_prefix="PO", number_field="number",
    fields=[
        F("number", "text", "PO number", maxlen=40, list=True, help="Left empty: assigned automatically."),
        F("procurement_id", "ref", "Procurement card", required=True, ref="procurements", list=True),
        F("vendor_id", "ref", "Vendor", required=True, ref="vendors", list=True),
        F("date", "date", "PO date", required=True, list=True),
        F("status", "select", "Status", required=True, default="draft", options=PO_STATUS),
        F("delivery_date", "date", "Delivery expected"),
        F("delivery_to", "text", "Deliver to", maxlen=200),
        F("items", "items", "Items ordered", max_items=100, fields=[
            F("description", "text", "Item", required=True),
            F("unit", "text", "Unit", maxlen=20),
            F("qty", "number", "Quantity", required=True, min=0, max=1e9),
            F("unit_price", "money", "Unit price (IDR)", required=True, min=0, max=1e13),
        ]),
        F("tax_pct", "percent", "VAT / PPN (%)", min=0, max=100, default=11),
        F("terms", "text", "Payment terms", maxlen=200),
        F("receipts", "items", "Goods received", max_items=200, section="Goods receipt", fields=[
            F("date", "date", "Date", required=True),
            F("line", "int", "PO item no.", required=True, min=1, max=100),
            F("qty", "number", "Quantity received", required=True, min=0, max=1e9),
            F("delivery_note", "text", "Delivery note no.", maxlen=60),
            F("received_by", "text", "Received by", maxlen=80),
            F("condition", "select", "Condition", default="good", options=[("good", "Good"), ("damaged", "Damaged / rejected")]),
        ]),
        F("invoice_no", "text", "Vendor invoice no.", maxlen=60, section="Vendor invoice"),
        F("invoice_date", "date", "Invoice date", section="Vendor invoice"),
        F("invoice_amount", "money", "Invoice amount incl. VAT (IDR)", min=0, max=1e14, section="Vendor invoice"),
        F("invoice_due", "date", "Payment due", section="Vendor invoice"),
        F("paid_date", "date", "Paid on", section="Vendor invoice"),
        F("subtotal", "money", "Subtotal", readonly=True),
        F("tax", "money", "VAT", readonly=True),
        F("total", "money", "Total", readonly=True, list=True),
        F("received_pct", "percent", "Received (%)", readonly=True),
        F("progress", "select", "Progress", readonly=True, list=True, options=PO_PROGRESS),
        WARNINGS, WARNING_COUNT,
        F("files", "files", "Documents", help="PO signed by the vendor, delivery notes, invoice, tax invoice."),
        F("notes", "longtext", "Notes", maxlen=2000),
    ],
))


# --------------------------------------------------------------------------- #
# Fixed asset card
# --------------------------------------------------------------------------- #

_add(Entity(
    name="fixed_assets", label="Fixed assets", label_one="Fixed asset", title="name", group="operations", sort="code",
    read=COMMERCIAL, write=("admin", "finance"),
    fields=[
        F("code", "text", "Asset code", required=True, maxlen=40, list=True),
        F("name", "text", "Name", required=True, list=True),
        F("category", "select", "Category", required=True, options=ASSET_CATEGORIES, list=True),
        F("acquisition_date", "date", "Acquired on", required=True, list=True,
          help="Month the cost was incurred (or work completed); depreciation starts in this month."),
        F("cost", "money", "Acquisition cost (IDR)", required=True, min=0, max=1e14, list=True,
          help="Purchase price plus costs to bring it into use (transport, installation), without recoverable VAT."),
        F("tax_group", "select", "Tax group (PMK 72/2023)", required=True, options=TAX_GROUPS, section="Tax depreciation"),
        F("tax_method", "select", "Tax method", required=True, default="straight_line", options=TAX_METHODS, section="Tax depreciation",
          help="Buildings: straight line only. Use one method consistently."),
        F("book_method", "select", "Book method (PSAK 216)", required=True, default="same_as_tax", options=BOOK_METHODS,
          section="Book depreciation"),
        F("book_life_years", "number", "Useful life for the books (years)", min=0.5, max=100, section="Book depreciation",
          help="Empty: the tax group's useful life."),
        F("residual_value", "money", "Residual value for the books (IDR)", min=0, max=1e14, section="Book depreciation"),
        F("location", "text", "Location", maxlen=120),
        F("custodian", "user", "Person in charge"),
        F("vendor_id", "ref", "Supplier", ref="vendors"),
        F("procurement_id", "ref", "Procurement card", ref="procurements"),
        F("invoice_ref", "text", "Purchase invoice no.", maxlen=60),
        F("disposal_date", "date", "Disposed on", section="Disposal"),
        F("disposal_type", "select", "Disposal", options=DISPOSAL_TYPES, section="Disposal"),
        F("disposal_proceeds", "money", "Proceeds (IDR)", min=0, max=1e14, section="Disposal",
          help="Sale price or insurance payment."),
        F("impairment_review_date", "date", "Impairment review on", section="Impairment (PSAK 236)",
          help="At each reporting date: is there any sign the asset may be impaired?"),
        F("impairment_indicators", "multiselect", "Signs of impairment", options=erp_ops.IMPAIRMENT_INDICATORS,
          section="Impairment (PSAK 236)"),
        F("recoverable_amount", "money", "Recoverable amount (IDR)", min=0, max=1e14, section="Impairment (PSAK 236)",
          help="The higher of fair value less costs of disposal and value in use; only when there is a sign of impairment."),
        F("impairment_note", "longtext", "Impairment notes", maxlen=2000, section="Impairment (PSAK 236)"),
        F("impairment_loss", "money", "Impairment loss indicated", readonly=True,
          help="Book value less the recoverable amount; booked by the accountant, not deducted in the schedule."),
        F("tax_life_years", "number", "Tax useful life (years)", readonly=True),
        F("tax_rate_pct", "percent", "Tax rate per year (%)", readonly=True),
        F("book_life", "number", "Book useful life (years)", readonly=True),
        F("dep_year_book", "money", "Depreciation this year (books)", readonly=True),
        F("accumulated_book", "money", "Accumulated depreciation (books)", readonly=True),
        F("book_value", "money", "Book value", readonly=True, list=True),
        F("dep_year_tax", "money", "Depreciation this year (tax)", readonly=True),
        F("accumulated_tax", "money", "Accumulated depreciation (tax)", readonly=True),
        F("tax_value", "money", "Tax book value", readonly=True),
        F("gain_loss_book", "money", "Gain / loss on disposal (books)", readonly=True),
        F("gain_loss_tax", "money", "Gain / loss on disposal (tax)", readonly=True),
        F("asset_status", "select", "Asset status", readonly=True, list=True, options=ASSET_STATUS),
        F("as_of", "date", "Values as of", readonly=True),
        F("schedule", "json", "Depreciation schedule", readonly=True),
        F("files", "files", "Documents & photos", help="Invoice, BAST, ownership papers (BPKB/STNK, certificate), photos."),
        F("notes", "longtext", "Notes", maxlen=2000),
    ],
))


# --------------------------------------------------------------------------- #
# Individual work plan & performance card
# --------------------------------------------------------------------------- #

_add(Entity(
    name="performance_cards", label="Work plan & performance cards", label_one="Performance card", title="title",
    group="operations", sort="-period_start", read=ALL_ROLES, write=OPS, own_write=("general", "lab", "finance"),
    own_read=("general", "lab", "finance"), owner_field="employee", workflow=True,
    reviewers=("admin", "manager"), approvers=("admin",),
    fields=[
        F("employee", "user", "Employee", required=True),
        F("employee_name", "text", "Employee name", required=True, list=True, maxlen=120),
        F("position", "text", "Position", list=True, maxlen=120),
        F("unit", "text", "Unit / department", maxlen=120),
        F("superior", "user", "Superior (reviewer)"),
        F("period_type", "select", "Period", required=True, default="annual", options=PERIOD_TYPES),
        F("period_start", "date", "Period from", required=True, list=True),
        F("period_end", "date", "Period to", required=True),
        F("kpis", "items", "KPIs (work plan and results)", max_items=30, section="KPIs", fields=[
            F("perspective", "select", "Perspective", required=True, options=PERSPECTIVES),
            F("kpi", "text", "KPI", required=True, maxlen=200),
            F("unit", "text", "Unit", maxlen=30, help="e.g. %, m, reports, days, IDR million"),
            F("target", "number", "Target", required=True, min=0, max=1e12),
            F("weight", "percent", "Weight (%)", required=True, min=0, max=100),
            F("polarity", "select", "Polarity", required=True, default="higher", options=POLARITY),
            F("actual", "number", "Actual", min=-1e12, max=1e12),
        ]),
        F("competencies", "items", "Behaviour & competencies", max_items=20, section="Competencies", fields=[
            F("competency", "text", "Competency / behaviour", required=True, maxlen=200),
            F("weight", "percent", "Weight (%)", required=True, min=0, max=100),
            F("score", "select", "Score", options=[
                ("1", "1 – Far below expectations"), ("2", "2 – Below expectations"), ("3", "3 – Meets expectations"),
                ("4", "4 – Above expectations"), ("5", "5 – Far above expectations")]),
            F("note", "text", "Evidence / note", maxlen=200),
        ]),
        F("kpi_share_pct", "percent", "Share of KPIs in the final score (%)", min=0, max=100, default=70,
          help="The rest is behaviour & competencies."),
        F("cap_pct", "percent", "Achievement cap per KPI (%)", min=100, max=200, default=120),
        F("employee_comment", "longtext", "Employee comments", maxlen=4000),
        F("superior_comment", "longtext", "Superior's assessment", maxlen=4000),
        F("development_plan", "longtext", "Development plan", maxlen=4000),
        F("title", "text", "Card", readonly=True),
        F("kpi_weight_total", "percent", "KPI weights total (%)", readonly=True),
        F("competency_weight_total", "percent", "Competency weights total (%)", readonly=True),
        F("kpi_score", "percent", "KPI score (%)", readonly=True),
        F("competency_score", "percent", "Competency score (%)", readonly=True),
        F("final_score", "percent", "Final score (%)", readonly=True, list=True),
        F("rating", "select", "Rating", readonly=True, list=True, options=RATINGS),
        F("scorecard", "json", "Scorecard", readonly=True),
        F("files", "files", "Evidence"),
    ],
))


COMPUTE_HOOKS.update({
    "vendors": erp_ops.compute_vendor,
    "vendor_evaluations": erp_ops.compute_vendor_evaluation,
    "equipment": erp_ops.compute_equipment,
    "mobilisations": erp_ops.compute_mobilisation,
    "work_orders": erp_ops.compute_work_order,
    "procurements": erp_ops.compute_procurement,
    "purchase_orders": erp_ops.compute_purchase_order,
    "fixed_assets": erp_ops.compute_fixed_asset,
    "performance_cards": erp_ops.compute_performance,
})

# Laboratory quality entities (sample receipt, nonconformities) and the lab test checks.
from . import entities_lab  # noqa: E402,F401
