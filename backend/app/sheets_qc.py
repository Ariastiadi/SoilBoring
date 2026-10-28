"""Compaction control and site safety worksheets: pre-drilling checklist / permit to work (01.05),
sand cone field density (03.09) and dynamic cone penetrometer (03.10), plus the catalogue entry of
the monitoring instruments page (03.11). Calculations are in calc_qc.py. Imported at the end of
sheets_field.py, so they register with the other field worksheets.
"""
from __future__ import annotations

from typing import Any, List

from . import calc_qc as cq
from .fields import F
from .sheets import Sheet, register


def n(name: str, label: str, **kw: Any) -> F:
    return F(name, "number", label, **kw)


def t(name: str, label: str, **kw: Any) -> F:
    return F(name, "text", label, **kw)


def sel(name: str, label: str, options: List[Any], **kw: Any) -> F:
    return F(name, "select", label, options=options, **kw)


def items(name: str, label: str, fields: List[F], **kw: Any) -> F:
    return F(name, "items", label, fields=fields, **kw)


PROCTOR_STANDARDS = [("SNI 1742:2008", "Test method for standard compaction of soil"),
                     ("SNI 1743:2008", "Test method for modified compaction of soil")]

# --------------------------------------------------------------------------- #
# 01.05 Pre-drilling checklist / permit to work
# --------------------------------------------------------------------------- #

_CHECKS: List[F] = []
for _key, _label, _group, _critical in cq.CHECK_ITEMS:
    _CHECKS.append(sel(_key, _label, cq.YNA, section=_group,
                       help="Critical: a No stops the work." if _critical else ""))

PREDRILL = Sheet(
    key="predrill_checklist", kind="field", group="general", code="01.05", label="Pre-drilling checklist / permit to work",
    help="Checks before a rig starts on a point: utilities, ground, rig, PPE, emergency, barricade, height, weather and excavation, with the job safety analysis. Fit to start only when no critical item is answered No.",
    fields=[
        t("permit_no", "Permit no.", maxlen=40, section="Permit"),
        F("valid_from", "date", "Valid from", section="Permit"),
        F("valid_to", "date", "Valid until", section="Permit"),
        t("rig", "Rig / equipment", maxlen=80, section="Permit"),
        t("work", "Work to be done", maxlen=200, section="Permit", help="e.g. rotary drilling with SPT to 30 m, CPT, test pit."),
        t("prepared_by", "Prepared by (driller / foreman)", maxlen=80, section="Permit"),
        t("approved_by", "Approved by (site manager / HSE)", maxlen=80, section="Permit"),
        *_CHECKS,
        n("excavation_depth", "Pit or trench depth (m)", min=0, max=30, section="Excavation",
          help="Inspection pit, test pit or mud pit; empty when there is none."),
        sel("soil_type", "Soil type (OSHA)", cq.SOIL_TYPES, section="Excavation",
            help="Classified by a competent person (29 CFR 1926 Subpart P, Appendix A)."),
        items("other_checks", "Other checks", max_items=30, section="Other checks", fields=[
            t("item", "Item", required=True, maxlen=160), sel("answer", "Answer", cq.YNA), F("critical", "bool", "Critical"),
            t("remark", "Remark", maxlen=120)]),
        items("jsa", "Job safety analysis (JSA)", max_items=40, section="Job safety analysis", fields=[
            t("step", "Job step", required=True, maxlen=120), t("hazard", "Hazard", maxlen=200), sel("risk", "Risk", cq.RISK),
            t("control", "Control", maxlen=240), t("ppe", "PPE", maxlen=120), t("responsible", "Responsible", maxlen=80)]),
        F("notes", "longtext", "Notes", maxlen=2000, section="Notes"),
    ],
    calc=cq.predrill_checklist,
    standards=[("29 CFR 1926 Subpart P", "Excavations (soil classification and protective systems)"),
               ("OSHA 3071", "Job hazard analysis"),
               ("ISO 45001:2018", "Occupational health and safety management systems"),
               ("Permenaker 5/2018", "Occupational safety and health of the working environment")],
    example={
        "permit_no": "PTW-BH-03", "valid_from": "2026-10-20", "valid_to": "2026-10-24", "rig": "Rotary rig YBM-01",
        "work": "Rotary drilling with SPT every 2 m to 30 m", "prepared_by": "Foreman", "approved_by": "Site manager",
        **{key: "yes" for key, _, _, _ in cq.CHECK_ITEMS},
        "water_work": "na", "traffic": "na", "hand_dig": "no", "excavation_protection": "na",
        "excavation_depth": 1.0, "soil_type": "B",
        "jsa": [
            {"step": "Move and set up the rig", "hazard": "Rig overturning on soft ground", "risk": "high",
             "control": "Check the ground, use timber mats, banksman guides the rig", "ppe": "Helmet, boots, vest",
             "responsible": "Driller"},
            {"step": "Drilling and SPT", "hazard": "Entanglement in the rotating rods, hammer drop", "risk": "high",
             "control": "Guards in place, emergency stop tested, no loose clothing, keep out of the hammer zone",
             "ppe": "Helmet, gloves, glasses, ear plugs", "responsible": "Driller"},
            {"step": "Handling rods and casing", "hazard": "Hand injuries, manual lifting", "risk": "medium",
             "control": "Two-person lift, rod holder, gloves", "ppe": "Gloves, boots", "responsible": "Helper"},
        ],
    },
)

# --------------------------------------------------------------------------- #
# 03.09 Sand cone
# --------------------------------------------------------------------------- #

SAND_CONE = Sheet(
    key="sand_cone", kind="field", group="geotechnical", code="03.09", label="Sand cone field density",
    help="Field density of compacted fill or subgrade with the sand cone: hole volume from calibrated sand, dry density and relative compaction against the Proctor maximum, pass or fail per point.",
    fields=[
        n("sand_density", "Bulk density of the sand ρ sand (g/cm³)", min=1, max=2, section="Sand and cone calibration",
          help="Empty: worked out from the calibration container below."),
        items("calibration", "Calibration container", max_items=5, section="Sand and cone calibration", fields=[
            n("mass", "Sand filling the container (g)", required=True, min=0), n("volume", "Container volume (cm³)", required=True, min=0)]),
        n("cone_mass", "Sand filling the cone and base plate (g)", min=0, max=10000, section="Sand and cone calibration",
          help="Empty: the average of the cone trials below."),
        items("cone_trials", "Cone correction trials", max_items=5, section="Sand and cone calibration", fields=[
            n("before", "Jar + sand before (g)", required=True, min=0), n("after", "Jar + sand after (g)", required=True, min=0)]),
        n("mdd", "Maximum dry density γd,max (g/cm³)", min=0.3, max=3.5, section="Specification",
          help="From the Proctor test of the same material; use Pick a Proctor test to copy it from the laboratory."),
        n("omc", "Optimum water content OMC (%)", min=0, max=200, section="Specification"),
        t("proctor_ref", "Proctor test", maxlen=80, section="Specification", help="Laboratory test or report the γd,max comes from."),
        n("spec_min", "Required relative compaction (%)", min=50, max=110, default=95, section="Specification",
          help="e.g. 95 % of standard Proctor for subgrade, 90 % for common fill."),
        n("moisture_tolerance", "Allowed water content deviation from OMC (± %)", min=0, max=20, section="Specification",
          help="Empty: the water content is not checked."),
        n("gs", "Specific gravity Gs (for the zero air voids line)", min=2, max=3.2, section="Specification"),
        sel("max_particle", "Largest particle size", [("4.75", "4.75 mm"), ("12.5", "12.5 mm"), ("25", "25 mm"), ("50", "50 mm")],
            section="Specification", help="Checks the hole volume against the ASTM D1556 minimum."),
        items("points", "Test points", max_items=60, section="Test points",
              help="Water content from the oven masses, or typed in, or a speedy reading (% of wet mass).", fields=[
                  t("point", "Point", required=True, maxlen=40), t("location", "Location / layer", maxlen=80),
                  n("mass_before", "Jar + sand before (g)", min=0), n("mass_after", "Jar + sand after (g)", min=0),
                  n("wet_soil", "Wet soil from the hole (g)", min=0),
                  n("w_tin", "Container (g)", min=0), n("w_wet", "Container + wet soil (g)", min=0),
                  n("w_dry", "Container + dry soil (g)", min=0), n("w", "Water content (%)", min=0, max=300),
                  n("speedy", "Speedy reading (%)", min=0, max=99)]),
    ],
    calc=cq.sand_cone,
    standards=[("SNI 2828:2011", "Test method for field density with the sand cone"),
               ("ASTM D1556/D1556M", "Density and unit weight of soil in place by sand-cone method"),
               ("ASTM D4944", "Field determination of water content of soil by calcium carbide gas pressure tester"),
               *PROCTOR_STANDARDS],
    example={
        "calibration": [{"mass": 3962, "volume": 2830}, {"mass": 3968, "volume": 2830}, {"mass": 3956, "volume": 2830}],
        "cone_trials": [{"before": 6500, "after": 4905}, {"before": 6480, "after": 4875}],
        "mdd": 1.85, "omc": 14.0, "proctor_ref": "Standard Proctor, borrow area B", "spec_min": 95, "moisture_tolerance": 3,
        "gs": 2.65, "max_particle": "12.5",
        "points": [
            {"point": "SC-01", "location": "STA 0+100, layer 3", "mass_before": 6000, "mass_after": 2400, "wet_soil": 2850,
             "w_tin": 20, "w_wet": 132, "w_dry": 120},
            {"point": "SC-02", "location": "STA 0+150, layer 3", "mass_before": 6000, "mass_after": 2450, "wet_soil": 2830, "w": 15.2},
            {"point": "SC-03", "location": "STA 0+200, layer 3", "mass_before": 6000, "mass_after": 2250, "wet_soil": 2780, "speedy": 12},
        ],
    },
)

# --------------------------------------------------------------------------- #
# 03.10 DCP
# --------------------------------------------------------------------------- #

DCP = Sheet(
    key="dcp", kind="field", group="geotechnical", code="03.10", label="Dynamic cone penetrometer (DCP)",
    help="Blows and penetration of the DCP: DCP index per interval and per layer, CBR by correlation, cumulative blows and CBR against depth.",
    fields=[
        sel("hammer", "Hammer", [("8", "8 kg (standard)"), ("4.6", "4.6 kg (factor 2)")], default="8", section="Test"),
        sel("correlation", "CBR correlation", [
            ("astm", "ASTM D6951: all soils except CL < 10 and CH"), ("cl", "ASTM D6951: CL soils, CBR < 10"),
            ("ch", "ASTM D6951: CH soils"), ("binamarga", "Indonesian DCP guideline (60° cone)")], default="astm", section="Test"),
        sel("blows_mode", "Blows column", [("set", "Blows in each set"), ("cumulative", "Cumulative blows")], default="set", section="Test"),
        n("zero_reading", "Scale reading before the first blow (mm)", min=0, max=2000, section="Test",
          help="Only when the readings do not start with a row of 0 blows."),
        n("start_depth", "Depth of the test surface (mm)", min=0, max=3000, section="Test",
          help="Below the reference level, e.g. after removing the surface layer; empty = 0."),
        t("surface", "Surface / layer tested", maxlen=120, section="Test"),
        items("readings", "Readings", max_items=300, section="Readings",
              help="One row per set of blows; the first row is usually 0 blows with the zero reading.", fields=[
                  n("blows", "Blows", required=True, min=0, max=500), n("reading", "Penetration reading (mm)", required=True, min=0, max=3000)]),
        items("layers", "Layers", max_items=20, section="Layers",
              help="Layer boundaries from the change of slope on the cumulative blows chart; empty = one layer.", fields=[
                  n("top", "From (mm)", required=True, min=0, max=3000), n("bottom", "To (mm)", required=True, min=0, max=3000),
                  t("description", "Description", maxlen=80)]),
    ],
    calc=cq.dcp,
    standards=[("ASTM D6951/D6951M", "Use of the dynamic cone penetrometer in shallow pavement applications"),
               ("SE Menteri PU 04/SE/M/2010", "Guideline: CBR test method with the dynamic cone penetrometer (DCP)")],
    example={
        "hammer": "8", "correlation": "astm", "blows_mode": "set", "surface": "Subgrade, STA 1+250",
        "readings": [{"blows": 0, "reading": 100}, {"blows": 10, "reading": 125}, {"blows": 10, "reading": 148},
                     {"blows": 10, "reading": 170}, {"blows": 5, "reading": 200}, {"blows": 5, "reading": 232},
                     {"blows": 3, "reading": 270}, {"blows": 3, "reading": 312}, {"blows": 3, "reading": 355},
                     {"blows": 3, "reading": 400}],
        "layers": [{"top": 0, "bottom": 70, "description": "Base course"}, {"top": 70, "bottom": 132, "description": "Subbase"},
                   {"top": 132, "bottom": 300, "description": "Subgrade"}],
    },
)

MONITORING_PAGE = Sheet(
    key="monitoring_page", kind="page", group="geotechnical", code="03.11", label="Monitoring instruments", link="monitoring",
    help="Piezometers, groundwater wells, inclinometers, settlement plates and extensometers with their readings and alarm levels.",
    standards=[("ISO 18674-1:2015", "Geotechnical monitoring by field instrumentation – General rules"),
               ("ASTM D6230", "Monitoring ground movement using probe-type inclinometers"),
               ("ASTM D5092/D5092M", "Design and installation of groundwater monitoring wells"),
               ("Dunnicliff (1993)", "Geotechnical instrumentation for monitoring field performance")],
)

register(PREDRILL, SAND_CONE, DCP, MONITORING_PAGE)
