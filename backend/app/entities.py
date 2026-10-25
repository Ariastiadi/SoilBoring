"""What each kind of record holds, who may read and change it.

The same definitions validate input on the server and are sent to the browser
(``GET /api/schemas``), which builds the lists and forms from them. Labels are English;
the interface translates them.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

ALL_ROLES = ("admin", "manager", "general", "lab", "finance")
COMMERCIAL = ("admin", "manager", "finance")

Option = Tuple[str, str]  # (stored value, English label)


@dataclass
class F:
    name: str
    type: str  # text, longtext, number, int, money, percent, date, select, multiselect, ref, user, email, bool, items, files, json
    label: str
    required: bool = False
    options: Optional[List[Any]] = None  # [(value, label)] or [(value, label, group)]
    options_filter: Optional[str] = None  # show only options whose group equals this field's value
    ref: Optional[str] = None  # entity name for type "ref"
    min: Optional[float] = None
    max: Optional[float] = None
    maxlen: int = 200
    help: str = ""
    fields: Optional[List["F"]] = None  # sub-fields for "items"
    max_items: int = 200
    list: bool = False  # shown as a column in lists
    readonly: bool = False  # computed by the server
    default: Any = None
    variants_by: Optional[str] = None  # for "json": which field picks the variant
    variants: Optional[Dict[str, List["F"]]] = None
    section: str = ""
    private: bool = False  # only shown to admin, manager and finance


@dataclass
class Entity:
    name: str
    label: str
    label_one: str
    fields: List[F]
    title: str  # field used as the record's title
    read: Tuple[str, ...] = ALL_ROLES
    write: Tuple[str, ...] = ("admin", "manager")
    own_write: Tuple[str, ...] = ()  # roles that may change only records they created
    number_prefix: str = ""  # automatic numbers such as INV-2026-001
    number_field: str = ""
    singleton: bool = False
    group: str = ""
    sort: str = "-created_at"

    def field(self, name: str) -> Optional[F]:
        return next((f for f in self.fields if f.name == name), None)


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

# Laboratory: results recorded for each kind of test.
LAB_RESULTS: Dict[str, List[F]] = {
    "moisture": [F("w", "number", "Moisture content w (%)", min=0, max=1000)],
    "density": [
        F("gamma_bulk", "number", "Bulk unit weight γ (kN/m³)", min=5, max=30),
        F("gamma_dry", "number", "Dry unit weight γd (kN/m³)", min=3, max=30),
    ],
    "specific_gravity": [F("gs", "number", "Specific gravity Gs", min=1.5, max=4)],
    "atterberg": [
        F("ll", "number", "Liquid limit LL (%)", min=0, max=500),
        F("pl", "number", "Plastic limit PL (%)", min=0, max=500),
        F("pi", "number", "Plasticity index PI (%)", min=0, max=500, help="Left empty: LL − PL"),
    ],
    "grain_size": [
        F("gravel", "number", "Gravel (%)", min=0, max=100),
        F("sand", "number", "Sand (%)", min=0, max=100),
        F("silt", "number", "Silt (%)", min=0, max=100),
        F("clay", "number", "Clay (%)", min=0, max=100),
        F("fines", "number", "Fines < 0.075 mm (%)", min=0, max=100, help="Left empty: silt + clay"),
    ],
    "ucs": [
        F("qu", "number", "Unconfined strength qu (kPa)", min=0, max=200000),
        F("strain", "number", "Strain at failure (%)", min=0, max=100),
    ],
    "direct_shear": [
        F("c", "number", "Cohesion c (kPa)", min=0, max=5000),
        F("phi", "number", "Friction angle φ (°)", min=0, max=60),
    ],
    "triaxial": [
        F("test", "select", "Test type", options=[("UU", "UU"), ("CU", "CU"), ("CD", "CD")]),
        F("c", "number", "Cohesion c (kPa)", min=0, max=5000),
        F("phi", "number", "Friction angle φ (°)", min=0, max=60),
    ],
    "consolidation": [
        F("cc", "number", "Compression index Cc", min=0, max=10),
        F("cr", "number", "Recompression index Cr", min=0, max=5),
        F("e0", "number", "Initial void ratio e0", min=0, max=20),
        F("pc", "number", "Preconsolidation pressure σ'p (kPa)", min=0, max=100000),
        F("cv", "number", "Coefficient of consolidation cv (m²/year)", min=0, max=10000),
    ],
}

LAB_TESTS: List[Option] = [
    ("moisture", "Moisture content"),
    ("density", "Unit weight"),
    ("specific_gravity", "Specific gravity"),
    ("atterberg", "Atterberg limits"),
    ("grain_size", "Grain size"),
    ("ucs", "Unconfined compression (UCS)"),
    ("direct_shear", "Direct shear"),
    ("triaxial", "Triaxial"),
    ("consolidation", "Consolidation"),
]

FIELD_METHODS: List[Tuple[str, str, str]] = [
    ("seismic_refraction", "Seismic refraction", "geophysics"),
    ("masw", "MASW (surface waves)", "geophysics"),
    ("resistivity", "Resistivity (geolistrik)", "geophysics"),
    ("gpr", "Ground penetrating radar", "geophysics"),
    ("downhole", "Downhole seismic", "geophysics"),
    ("outcrop", "Outcrop description", "geology"),
    ("mapping", "Geological mapping", "geology"),
    ("structure", "Structural measurement (strike/dip)", "geology"),
    ("test_pit", "Test pit", "geology"),
    ("topographic", "Topographic survey", "survey"),
    ("benchmark", "Benchmark / control point", "survey"),
    ("stakeout", "Stake-out of test points", "survey"),
    ("drone", "Drone / photogrammetry", "survey"),
    ("other", "Other", "geophysics"),
    ("other_geology", "Other", "geology"),
    ("other_survey", "Other", "survey"),
]

ITEM_FIELDS = [
    F("rate_id", "ref", "From price list", ref="rates"),
    F("description", "text", "Description", required=True),
    F("unit", "text", "Unit", maxlen=20),
    F("qty", "number", "Quantity", required=True, min=0, max=1e9),
    F("unit_price", "money", "Unit price", required=True, min=0, max=1e13),
]

ENTITIES: Dict[str, Entity] = {}


def _add(entity: Entity) -> None:
    ENTITIES[entity.name] = entity


_add(Entity(
    name="clients", label="Clients", label_one="Client", title="name", group="commercial", sort="name",
    fields=[
        F("name", "text", "Name", required=True, list=True),
        F("type", "select", "Type", required=True, list=True, options=[
            ("contractor", "Contractor"), ("bumn", "State-owned (BUMN)"), ("private", "Private company"),
            ("government", "Government"), ("other", "Other")]),
        F("contact_person", "text", "Contact person", list=True),
        F("phone", "text", "Phone", maxlen=40, list=True),
        F("email", "email", "Email"),
        F("npwp", "text", "Tax number (NPWP)", maxlen=30),
        F("address", "longtext", "Address", maxlen=500),
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
        F("services", "multiselect", "Services", options=SERVICE_LINES),
        F("start_date", "date", "Start date", list=True),
        F("end_date", "date", "End date"),
        F("contract_value", "money", "Contract value (IDR)", min=0, max=1e14, private=True),
        F("notes", "longtext", "Notes", maxlen=4000),
    ],
))

_add(Entity(
    name="rates", label="Price list", label_one="Rate", title="description", group="finance", sort="code",
    read=COMMERCIAL, write=("admin", "manager", "finance"),
    fields=[
        F("code", "text", "Code", required=True, maxlen=20, list=True),
        F("description", "text", "Description", required=True, list=True),
        F("line", "select", "Service", options=SERVICE_LINES, list=True),
        F("unit", "text", "Unit", required=True, maxlen=20, list=True, help="e.g. m, point, sample, day, lump sum"),
        F("price", "money", "Unit price (IDR)", required=True, min=0, max=1e13, list=True),
    ],
))

_add(Entity(
    name="quotes", label="Quotations", label_one="Quotation", title="number", group="commercial",
    read=COMMERCIAL, number_prefix="QUO", number_field="number", sort="-date",
    fields=[
        F("number", "text", "Number", maxlen=40, list=True, help="Left empty: assigned automatically."),
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("date", "date", "Date", required=True, list=True),
        F("valid_until", "date", "Valid until"),
        F("status", "select", "Status", required=True, default="draft", list=True, options=[
            ("draft", "Draft"), ("sent", "Sent"), ("won", "Won"), ("lost", "Lost")]),
        F("items", "items", "Items", fields=ITEM_FIELDS),
        F("discount_pct", "percent", "Discount (%)", min=0, max=100, default=0),
        F("tax_pct", "percent", "VAT / PPN (%)", min=0, max=100, default=11),
        F("subtotal", "money", "Subtotal", readonly=True),
        F("tax", "money", "VAT", readonly=True),
        F("total", "money", "Total", readonly=True, list=True),
        F("notes", "longtext", "Terms and notes", maxlen=4000),
    ],
))

_add(Entity(
    name="contracts", label="Contracts", label_one="Contract", title="number", group="commercial",
    read=COMMERCIAL, sort="-date",
    fields=[
        F("number", "text", "Contract number", required=True, maxlen=60, list=True),
        F("project_id", "ref", "Project", required=True, ref="projects", list=True),
        F("date", "date", "Signed on", required=True, list=True),
        F("value", "money", "Contract value (IDR, incl. VAT)", required=True, min=0, max=1e14, list=True),
        F("status", "select", "Status", required=True, default="draft", list=True, options=[
            ("draft", "Draft"), ("signed", "Signed"), ("amended", "Amended"), ("closed", "Closed")]),
        F("start_date", "date", "Work starts"),
        F("end_date", "date", "Work ends"),
        F("client_signatory", "text", "Signed for the client"),
        F("our_signatory", "text", "Signed for us"),
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
        F("readings", "items", "Readings", max_items=3000, fields=[
            F("depth", "number", "Depth (m)", required=True, min=0, max=200),
            F("qc", "number", "qc (kg/cm²)", required=True, min=0, max=2000),
            F("fs", "number", "fs (kg/cm²)", min=0, max=100),
            F("u2", "number", "u2 (kPa)", min=-500, max=10000),
        ]),
        F("files", "files", "Files"),
        F("remarks", "longtext", "Remarks", maxlen=2000),
    ],
))

_add(Entity(
    name="field_activities", label="Other field work", label_one="Field activity", title="code", group="field",
    sort="-date", write=("admin", "manager"), own_write=("general",),
    fields=[
        F("code", "text", "Line / point ID", required=True, maxlen=40, list=True),
        F("type", "select", "Discipline", required=True, list=True, options=[
            ("geophysics", "Geophysics"), ("geology", "Geology"), ("survey", "Geodesy & mapping")]),
        F("method", "select", "Method", required=True, list=True, options=FIELD_METHODS, options_filter="type"),
        F("project_id", "ref", "Project", ref="projects", list=True),
        F("date", "date", "Date", required=True, list=True),
        F("latitude", "number", "Latitude", min=-90, max=90),
        F("longitude", "number", "Longitude", min=-180, max=180),
        F("elevation", "number", "Elevation (mRL)", min=-1000, max=9000),
        F("length", "number", "Line length (m)", min=0, max=100000),
        F("crew", "text", "Crew"),
        F("results", "longtext", "Results", maxlen=6000,
          help="e.g. layers and velocities, resistivity zones, lithology, strike/dip, coordinates and accuracy."),
        F("values", "items", "Measurements", max_items=500, fields=[
            F("name", "text", "Parameter", required=True, maxlen=60),
            F("value", "text", "Value", required=True, maxlen=60),
            F("unit", "text", "Unit", maxlen=20),
        ]),
        F("files", "files", "Files"),
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
            ("received", "Received"), ("testing", "Testing"), ("done", "Done")]),
        F("received", "date", "Received on", list=True),
        F("tested", "date", "Tested on"),
        F("technician", "text", "Technician"),
        F("standard", "text", "Standard", help="e.g. SNI 1965:2008, ASTM D2216"),
        F("results", "json", "Results", variants_by="test_type", variants=LAB_RESULTS),
        F("files", "files", "Lab sheets"),
        F("remarks", "longtext", "Remarks", maxlen=2000),
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
            ("liquefaction", "Liquefaction (SPT, Idriss & Boulanger)")]),
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
    ],
))


def public_schema() -> Dict[str, Any]:
    """Definitions for the browser."""
    out: Dict[str, Any] = {}
    for name, entity in ENTITIES.items():
        data = asdict(entity)
        out[name] = data
    return out
