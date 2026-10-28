"""Client report templates by project type: the ordered section outline of each, where each
section's content comes from, the annex kinds and the extra references offered besides the
worksheet standards.

A section is (key, title, source). The source says what the print fills in from the project's
data next to the engineer's own text:

* ``text``: only the text written in the report;
* ``project``: project, client, location and the extent of the boreholes;
* ``scope``: quantities of work (boreholes, metres, SPT, samples, CPT, field and lab tests);
* ``field``: the boreholes, CPT and other field work done;
* ``cpt``: CPT results;
* ``lab``: laboratory results per sample;
* ``subsurface``: strata, SPT and groundwater per borehole;
* ``parameters``: statistics of SPT N per soil class and of the laboratory results per test;
* ``analyses:<type,...>``: engineering analyses of those types (``*`` = all);
* ``tests:<key,...>``: field worksheets and laboratory tests of those kinds (e.g. CBR, permeability).

The outlines follow the usual content of a geotechnical investigation and design report
(SNI 8460:2017 geotechnical design requirements; EN 1997-2 ground investigation report;
FHWA-NHI-16-072, GEC 5); the company adapts titles and text per report.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

Section = Tuple[str, str, str]  # key, title, source

_EXEC = ("summary", "Executive summary", "text")
_PROJECT = ("project", "Project and site description", "project")
_SCOPE = ("scope", "Scope of work and standards", "scope")
_FIELD = ("field", "Field investigation", "field")
_CPT = ("cpt", "Cone penetration tests (sondir)", "cpt")
_LAB = ("lab", "Laboratory testing", "lab")
_SUBSURFACE = ("subsurface", "Subsurface profile and groundwater", "subsurface")
_PARAMS = ("parameters", "Design parameters", "parameters")
_BEARING = ("bearing", "Bearing capacity", "analyses:bearing,bearing_table")
_SETTLEMENT = ("settlement", "Settlement", "analyses:settlement")
_SEISMIC = ("seismic", "Seismic site class and design spectrum", "analyses:site_class")
_LIQ = ("liquefaction", "Liquefaction potential", "analyses:liquefaction")
_PILE = ("pile", "Pile design", "analyses:pile")
_SLOPE = ("slope", "Slope stability", "analyses:slope,slope_stability")
_RETAINING = ("retaining", "Retaining structures", "analyses:retaining_wall,retaining")
_CBR = ("subgrade", "Subgrade evaluation (CBR and compaction)", "tests:cbr_field,cbr_lab,compaction,dcp,sand_cone")
_PERM = ("permeability", "Permeability and seepage", "tests:perm_falling,perm_constant,perm_rising,lugeon,permeability,permeability_lab")
_CHEM = ("aggressiveness", "Soil and groundwater aggressiveness", "tests:chemical,ph,sulfate,chloride,organic_content,soil_chemistry,water_chemistry")
_LIMITS = ("limitations", "Limitations", "text")


def _text(key: str, title: str) -> Section:
    return (key, title, "text")


TEMPLATES: Dict[str, Tuple[str, List[Section]]] = {
    "building": ("Building / high-rise", [
        _EXEC, _PROJECT, _SCOPE, _FIELD, _LAB, _SUBSURFACE, _PARAMS, _BEARING, _SETTLEMENT, _SEISMIC, _LIQ,
        _text("foundation", "Foundation recommendation"), _text("excavation", "Excavation and dewatering"), _PILE,
        _text("monitoring", "Monitoring during construction"), _LIMITS,
    ]),
    "bridge": ("Bridge", [
        _EXEC, _PROJECT, _SCOPE, _FIELD, _LAB, _SUBSURFACE, _PARAMS, _SEISMIC, _LIQ,
        _text("scour", "River conditions and scour"), _PILE,
        _text("lateral", "Lateral pile capacity and negative skin friction"), _BEARING,
        ("approach", "Approach embankment settlement", "analyses:settlement"),
        _text("foundation", "Foundation recommendation"), _text("construction", "Construction considerations"), _LIMITS,
    ]),
    "road": ("Road / toll road", [
        _EXEC, _PROJECT, _SCOPE, _FIELD, _LAB, _SUBSURFACE, _CBR, _PARAMS,
        ("embankment", "Embankment settlement", "analyses:settlement"), _SLOPE,
        _text("soft_soil", "Soft soil treatment"), _text("drainage", "Drainage"),
        _text("pavement", "Pavement and subgrade recommendation"), _LIMITS,
    ]),
    "port": ("Port / marine structure", [
        _EXEC, _PROJECT, _SCOPE, _FIELD, _LAB, ("subsurface", "Seabed profile, tides and groundwater", "subsurface"),
        _PARAMS, _SEISMIC, _LIQ, _PILE, _text("lateral", "Lateral pile capacity and berthing loads"),
        _RETAINING, _SLOPE, ("reclamation", "Reclamation settlement", "analyses:settlement"), _CHEM,
        _text("foundation", "Foundation recommendation"), _LIMITS,
    ]),
    "dam": ("Dam / embankment", [
        _EXEC, _PROJECT, _SCOPE, _FIELD, _LAB, _SUBSURFACE, _PERM, _PARAMS, _SLOPE,
        _text("seepage", "Seepage control"), _SETTLEMENT, _SEISMIC, _LIQ,
        _text("treatment", "Foundation treatment (grouting, cut-off)"), _text("monitoring", "Instrumentation and monitoring"), _LIMITS,
    ]),
    "railway": ("Railway", [
        _EXEC, _PROJECT, _SCOPE, _FIELD, _LAB, _SUBSURFACE, _PARAMS, _CBR, _SLOPE,
        ("embankment", "Embankment settlement", "analyses:settlement"), _SEISMIC, _LIQ,
        ("structures", "Foundations of bridges and stations", "analyses:pile,bearing,bearing_table"),
        _text("drainage", "Drainage"), _text("recommendation", "Recommendations"), _LIMITS,
    ]),
    "industrial": ("Industrial plant", [
        _EXEC, _PROJECT, _SCOPE, _FIELD, _LAB, _SUBSURFACE, _PARAMS, _BEARING, _SETTLEMENT,
        _text("tanks", "Tank and heavy equipment foundations"), _PILE, _SEISMIC, _LIQ,
        _text("improvement", "Ground improvement"), _CHEM, _text("slab", "Floor slabs and subgrade modulus"), _LIMITS,
    ]),
    "slope": ("Slope / landslide", [
        _EXEC, _PROJECT, _SCOPE, _FIELD, _LAB, _SUBSURFACE, _text("groundwater", "Groundwater and piezometers"), _PARAMS,
        ("stability", "Slope stability and back-analysis", "analyses:slope,slope_stability"),
        _text("stabilisation", "Stabilisation options"), _text("drainage", "Surface and subsurface drainage"),
        _text("monitoring", "Monitoring (inclinometers, piezometers, survey points)"), _LIMITS,
    ]),
    "general": ("General soil investigation", [
        _EXEC, _PROJECT, _SCOPE, _FIELD, _CPT, _LAB, _SUBSURFACE, _PARAMS,
        ("analyses", "Engineering analyses", "analyses:*"), _text("recommendations", "Recommendations"), _LIMITS,
    ]),
}

TEMPLATE_OPTIONS = [(key, label) for key, (label, _) in TEMPLATES.items()]

# Text put into the limitations section when the outline is applied (the engineer edits it).
DEFAULT_TEXT: Dict[str, str] = {
    "limitations": (
        "The findings apply to the test locations and the dates of the investigation. Ground conditions between "
        "and beyond the test points can differ. The analyses are preliminary, are based on the parameters stated in "
        "this report and must be checked by the design engineer of record. Groundwater levels vary with season and "
        "construction. The company should be informed if conditions differ from those described."
    ),
}

SOURCES = ("text", "project", "scope", "field", "cpt", "lab", "subsurface", "parameters")


def valid_source(source: str) -> bool:
    if source in SOURCES:
        return True
    kind, _, keys = source.partition(":")
    return kind in ("analyses", "tests") and bool(keys) and all(k.replace("_", "").isalnum() or k == "*" for k in keys.split(","))


def outline(template: str) -> List[Dict[str, object]]:
    """The template's sections as report rows (title in English; the interface translates it)."""
    _, sections = TEMPLATES.get(template) or TEMPLATES["general"]
    return [{"key": key, "title": title, "source": source, "include": True, "text": DEFAULT_TEXT.get(key, "")}
            for key, title, source in sections]


ANNEX_KINDS = [
    ("borehole_log", "Borehole log"), ("cpt_plot", "CPT plot"), ("lab_sheet", "Laboratory test sheet"),
    ("field_sheet", "Field worksheet"), ("photos", "Photographs"), ("calibration", "Calibration certificate"),
    ("site_plan", "Site plan / test location map"), ("other", "Other document"),
]

# References offered besides the standards of the worksheets (see sheets.py).
EXTRA_REFERENCES: List[Tuple[str, str]] = [
    ("SNI 8460:2017", "Geotechnical design requirements"),
    ("SNI 2827:2008", "Field penetration test with the cone penetrometer (sondir)"),
    ("SNI 2847:2019", "Structural concrete requirements for buildings"),
    ("SNI 2833:2016", "Seismic design of bridges"),
    ("SNI 8064:2016", "Static slope stability analysis of embankment dams"),
    ("ASTM D420", "Site characterization for engineering design and construction purposes"),
    ("EN 1997-1:2004", "Eurocode 7: Geotechnical design – Part 1: General rules"),
    ("EN 1997-2:2007", "Eurocode 7: Geotechnical design – Part 2: Ground investigation and testing"),
    ("FHWA-NHI-16-072", "Geotechnical site characterization (GEC 5)"),
    ("FHWA-NHI-16-009", "Drilled shafts: construction procedures and design methods (GEC 10)"),
    ("FHWA-NHI-16-064", "Design and construction of driven pile foundations (GEC 12)"),
]


def reference_catalog() -> List[Tuple[str, str]]:
    """Every standard of the worksheets plus the extra references, sorted by code."""
    from . import sheets

    seen: Dict[str, str] = {}
    for sheet in sheets.all_sheets():
        for std in sheet.standards:
            seen.setdefault(std[0], std[1] if len(std) > 1 else "")
    for code, title in EXTRA_REFERENCES:
        seen.setdefault(code, title)
    return sorted(seen.items(), key=lambda x: x[0])
