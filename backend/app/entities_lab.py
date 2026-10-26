"""Laboratory quality records after ISO/IEC 17025:2017 (SNI ISO/IEC 17025:2017): the sample receipt
with chain of custody, storage, retention and disposal (clause 7.4), and the register of
nonconforming work and corrective actions (clauses 7.10 and 8.7). The checks on each laboratory
test (receipt link, calibration of the equipment used, authorisation of results) are in erp_lab.py.
Imported by entities_ops.py.
"""
from __future__ import annotations

from typing import List

from . import erp_lab
from .entities import Entity, F, _add
from .fields import COMPUTE_HOOKS, Option

LAB = ("admin", "manager", "lab")

WARNINGS = F("warnings", "json", "Checks", readonly=True)
WARNING_COUNT = F("warning_count", "int", "Warnings", readonly=True, list=True)

SAMPLE_TYPES: List[Option] = [
    ("uds", "Undisturbed tube (UDS / Shelby)"), ("spt", "SPT split spoon"), ("disturbed", "Disturbed (bag / jar)"),
    ("core", "Rock core (core box)"), ("block", "Block sample"), ("water", "Water"), ("other", "Other"),
]

CUSTODY_PURPOSE: List[Option] = [
    ("storage", "To storage"), ("testing", "For testing"), ("transfer", "Transfer"), ("subcontract", "To another laboratory"),
    ("return", "Return to customer"), ("disposal", "For disposal"),
]

_add(Entity(
    name="sample_receipts", label="Sample receipts", label_one="Sample receipt", title="number", group="lab",
    sort="-received_on", write=LAB, own_write=("general",), number_prefix="SR", number_field="number",
    fields=[
        F("number", "text", "Lab receipt no.", maxlen=40, list=True, help="Left empty: assigned automatically (SR-year-number)."),
        F("received_on", "date", "Received on", required=True, list=True),
        F("time", "text", "Time", maxlen=5, help="HH:MM"),
        F("received_by", "user", "Received by"),
        F("delivered_by", "text", "Delivered by", maxlen=120, help="Driller, courier or customer."),
        F("project_id", "ref", "Project", ref="projects"),
        F("borehole_id", "text", "Borehole", required=True, maxlen=64, list=True),
        F("sample_ref", "text", "Sample", required=True, maxlen=40, list=True),
        F("depth_top", "number", "From (m)", min=0, max=500),
        F("depth_base", "number", "To (m)", min=0, max=500),
        F("sample_type", "select", "Sample type", options=SAMPLE_TYPES),
        F("condition", "select", "Condition on arrival", required=True, default="as_specified", list=True, options=[
            ("as_specified", "As specified"), ("deviation", "Deviation found")]),
        F("deviations", "multiselect", "Deviations", options=erp_lab.DEVIATIONS),
        F("condition_note", "longtext", "Condition notes", maxlen=1000),
        F("customer_consulted_on", "date", "Customer consulted on", section="Deviation"),
        F("customer_instruction", "longtext", "Customer's instruction", maxlen=1000, section="Deviation"),
        F("decision", "select", "Decision", section="Deviation", options=[
            ("test", "Test"), ("test_with_disclaimer", "Test, with a disclaimer in the report"),
            ("do_not_test", "Do not test"), ("return", "Return to the customer")]),
        F("storage_location", "text", "Storage location", maxlen=120, section="Storage",
          help="Room, rack and shelf, e.g. humidity room, rack B-3."),
        F("storage_condition", "text", "Storage conditions", maxlen=200, section="Storage",
          help="e.g. sealed, upright, protected from sun and freezing; temperature or humidity when specified."),
        F("custody", "items", "Chain of custody", max_items=100, section="Chain of custody", fields=[
            F("date", "date", "Date", required=True),
            F("time", "text", "Time", maxlen=5),
            F("from_person", "text", "From", required=True, maxlen=120),
            F("to_person", "text", "To", required=True, maxlen=120),
            F("purpose", "select", "Purpose", options=CUSTODY_PURPOSE),
            F("location", "text", "Location", maxlen=120),
            F("note", "text", "Condition / note", maxlen=200),
        ]),
        F("retain_until", "date", "Keep until", section="Retention and disposal",
          help="Agreed with the customer or set by the laboratory procedure."),
        F("disposed_on", "date", "Disposed of / returned on", section="Retention and disposal"),
        F("disposal_method", "select", "How", section="Retention and disposal", options=[
            ("discarded", "Discarded"), ("returned", "Returned to the customer"), ("archived", "Kept as reference / archive")]),
        F("disposal_by", "user", "Authorised by", section="Retention and disposal"),
        F("receipt_status", "select", "Status", readonly=True, list=True, options=[
            ("in_store", "In store"), ("on_hold", "On hold: deviation"), ("disposed", "Disposed of"), ("returned", "Returned")]),
        F("current_holder", "text", "Now held by", readonly=True),
        F("current_location", "text", "Now at", readonly=True),
        F("days_in_store", "int", "Days in store", readonly=True),
        WARNINGS, WARNING_COUNT,
        F("files", "files", "Photos & documents", help="Photos on arrival, delivery note, sample list from the field."),
    ],
))

NC_SOURCES: List[Option] = [
    ("sample_receipt", "Sample receipt"), ("testing", "Testing / method"), ("equipment", "Equipment / calibration"),
    ("results", "Results / calculation"), ("report", "Report"), ("complaint", "Customer complaint"),
    ("internal_audit", "Internal audit"), ("supplier", "Supplier / subcontractor"), ("field", "Field work"), ("other", "Other"),
]

_add(Entity(
    name="nonconformities", label="Nonconformities & corrective actions", label_one="Nonconformity", title="number", group="lab",
    sort="-date", write=("admin", "manager", "lab"), own_write=("general", "finance"), number_prefix="NC", number_field="number",
    fields=[
        F("number", "text", "Number", maxlen=40, list=True, help="Left empty: assigned automatically (NC-year-number)."),
        F("date", "date", "Found on", required=True, list=True),
        F("source", "select", "Found in", required=True, options=NC_SOURCES, list=True),
        F("description", "longtext", "What does not conform", required=True, maxlen=4000,
          help="The requirement (procedure, standard, customer agreement) and what was found."),
        F("risk", "select", "Risk", default="medium", list=True, options=[("low", "Low"), ("medium", "Medium"), ("high", "High")],
          help="Sets how far to go: halting work, repeating tests, withholding reports."),
        F("lab_test_id", "ref", "Laboratory test", ref="lab_tests"),
        F("equipment_id", "ref", "Equipment", ref="equipment"),
        F("project_id", "ref", "Project", ref="projects"),
        F("detected_by", "user", "Found by"),
        F("correction", "longtext", "Immediate correction", maxlen=2000, section="Control and correction",
          help="What was done straight away to control and correct it."),
        F("work_halted", "bool", "Work halted / reports withheld", section="Control and correction"),
        F("impact", "longtext", "Significance and impact on earlier results", maxlen=2000, section="Control and correction",
          help="Which earlier results or reports could be affected, and what the check found."),
        F("decision", "select", "Decision on the work", section="Control and correction", options=[
            ("acceptable", "Acceptable as it is"), ("repeat", "Repeat the test / work"), ("correct_report", "Correct or reissue the report"),
            ("reject", "Reject the result")]),
        F("customer_action", "select", "Customer", section="Control and correction", options=[
            ("not_needed", "Not affected, no notice needed"), ("notified", "Notified"), ("recalled", "Notified and work recalled")]),
        F("resumption_authorised_by", "user", "Resumption authorised by", section="Control and correction"),
        F("resumed_on", "date", "Work resumed on", section="Control and correction"),
        F("corrective_action_needed", "select", "Corrective action needed", section="Corrective action", options=[
            ("yes", "Yes: it could happen again or the system is in doubt"), ("no", "No: a one-off, corrected")]),
        F("root_cause", "longtext", "Cause", maxlen=2000, section="Corrective action",
          help="Why it happened (e.g. 5 whys); whether similar nonconformities exist or could occur."),
        F("corrective_action", "longtext", "Corrective action", maxlen=2000, section="Corrective action"),
        F("action_owner", "user", "Person responsible", section="Corrective action"),
        F("action_due", "date", "Due", section="Corrective action"),
        F("action_done_on", "date", "Done on", section="Corrective action"),
        F("effectiveness_on", "date", "Effectiveness checked on", section="Corrective action"),
        F("effective", "select", "Effective", section="Corrective action", options=[("yes", "Yes"), ("no", "No: further action")]),
        F("effectiveness_note", "longtext", "Evidence of effectiveness", maxlen=2000, section="Corrective action"),
        F("risks_updated", "bool", "Risks and opportunities updated", section="Corrective action"),
        F("system_change", "longtext", "Changes to procedures or the management system", maxlen=2000, section="Corrective action"),
        F("closed_on", "date", "Closed on", list=True,
          help="Only a manager or an administrator can close; every step must be recorded first."),
        F("closed_by", "user", "Closed by", readonly=True),
        F("stage", "select", "Stage", readonly=True, list=True, options=[
            ("open", "Open"), ("correction", "Correction"), ("corrective_action", "Corrective action"),
            ("verification", "Effectiveness check"), ("closed", "Closed")]),
        WARNINGS, WARNING_COUNT,
        F("files", "files", "Evidence"),
    ],
))

COMPUTE_HOOKS.update({
    "lab_tests": erp_lab.compute_lab_test,
    "sample_receipts": erp_lab.compute_sample_receipt,
    "nonconformities": erp_lab.compute_nonconformity,
})
