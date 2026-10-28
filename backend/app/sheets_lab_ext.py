"""Laboratory worksheets 05.19 to 05.23 (see calc_lab_ext.py for the calculations).

Imported at the end of sheets_lab.py: adds the tests to LAB_TESTS, their result fields to
LAB_RESULTS and their examples to EXAMPLES, then registers the sheets after 05.18.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from . import calc_lab_ext
from .fields import F, Option
from .sheets import Sheet, register
from .sheets_lab import EXAMPLES, LAB_RESULTS, LAB_TESTS, _bounded, _i, _items, _mass, _n, _s, _t

NEW_TESTS: List[Tuple[str, str]] = [
    ("chemistry", "Soil and water chemistry (concrete and steel)"),
    ("permeability_lab", "Permeability (laboratory)"),
    ("point_load", "Point load index"),
    ("relative_density", "Relative density (sands)"),
    ("dispersivity", "Dispersivity (crumb, pinhole)"),
]

EXPOSURE: List[Option] = [("S0", "S0"), ("S1", "S1"), ("S2", "S2"), ("S3", "S3")]
VERDICTS: List[Option] = [("dispersive", "Dispersive"), ("intermediate", "Intermediate"), ("non_dispersive", "Non-dispersive")]
PINHOLE: List[Option] = [("D1", "D1"), ("D2", "D2"), ("ND4", "ND4"), ("ND3", "ND3"), ("ND2", "ND2"), ("ND1", "ND1")]
PERM_METHODS: List[Option] = [("constant", "Constant head"), ("falling", "Falling head")]

NEW_RESULTS: Dict[str, List[F]] = {
    "chemistry": [
        F("ph_soil", "number", "Soil pH", min=0, max=14),
        F("ph_water", "number", "Groundwater pH", min=0, max=14),
        F("so4_soil", "number", "Sulfate in soil SO₄ (%)", min=0, max=100),
        F("so4_water", "number", "Sulfate in water SO₄ (mg/L)", min=0, max=1e6),
        F("cl_soil", "number", "Chloride in soil Cl (mg/kg)", min=0, max=1e6),
        F("cl_water", "number", "Chloride in water Cl (mg/L)", min=0, max=1e6),
        F("resistivity", "number", "Minimum resistivity (Ω·cm)", min=0, max=1e8),
        F("organic", "number", "Organic content (%)", min=0, max=100),
        F("exposure", "select", "Sulfate exposure class", options=EXPOSURE),
        F("steel", "select", "Steel corrosion", options=[("aggressive", "Aggressive"), ("not_aggressive", "Not aggressive")]),
    ],
    "permeability_lab": [
        F("k", "number", "Coefficient of permeability k20 (cm/s)", min=0, max=100),
        F("e", "number", "Void ratio e", min=0, max=20),
        F("method", "select", "Method", options=PERM_METHODS),
    ],
    "point_load": [
        F("is50", "number", "Point load index Is(50) (MPa)", min=0, max=100),
        F("ucs", "number", "Estimated UCS (MPa)", min=0, max=1000),
        F("k_factor", "number", "Conversion factor K", min=5, max=60),
        F("n", "int", "Valid tests", min=0, max=1000),
    ],
    "relative_density": [
        F("dr", "number", "Relative density Dr (%)", min=0, max=100),
        F("rho_min", "number", "Minimum index density (g/cm³)", min=0.3, max=3.5),
        F("rho_max", "number", "Maximum index density (g/cm³)", min=0.3, max=3.5),
        F("e_min", "number", "Minimum void ratio emin", min=0, max=10),
        F("e_max", "number", "Maximum void ratio emax", min=0, max=10),
    ],
    "dispersivity": [
        F("crumb_grade", "int", "Crumb grade", min=1, max=4),
        F("pinhole_class", "select", "Pinhole class", options=PINHOLE),
        F("dispersion_pct", "number", "Percent dispersion (%)", min=0, max=1000),
        F("verdict", "select", "Dispersivity", options=VERDICTS),
    ],
}

# --------------------------------------------------------------------------- #
# Standards
# --------------------------------------------------------------------------- #

S_CHEM = [
    ("ACI 318-19", "Building code requirements for structural concrete, Tables 19.3.1.1 and 19.3.2.1 (exposure classes S and C)"),
    ("SNI 2847:2019", "Structural concrete requirements for buildings (exposure classes S0–S3, C0–C2)"),
    ("SNI 2049:2015", "Portland cement (types I to V)"),
    ("ASTM C1580", "Water-soluble sulfate in soil"),
    ("ASTM D516", "Sulfate ion in water"),
    ("ASTM D512", "Chloride ion in water"),
    ("ASTM D4972", "pH of soils"),
    ("ASTM G187", "Measurement of soil resistivity using the two-electrode soil box method"),
    ("ASTM D2974", "Moisture, ash, and organic matter of peat and other organic soils (loss on ignition)"),
    ("AASHTO LRFD Bridge Design Specifications, Art. 10.7.5", "Corrosion and deterioration of piles"),
    ("FHWA-NHI-16-009", "Design and construction of driven pile foundations (corrosion indicators)"),
]
S_PERM = [
    ("ASTM D2434", "Permeability of granular soils (constant head)"),
    ("ASTM D5856", "Hydraulic conductivity of porous material using a rigid-wall, compaction-mold permeameter"),
    ("ASTM D5084", "Hydraulic conductivity of saturated porous materials using a flexible wall permeameter"),
    ("ISO 17892-11", "Laboratory testing of soil, part 11: permeability tests"),
]
S_PLT = [
    ("ASTM D5731-16", "Determination of the point load strength index of rock and application to rock strength classifications"),
    ("ISRM (1985)", "Suggested method for determining point load strength"),
    ("ISRM (1981)", "Rock characterization, testing and monitoring: strength grades R0–R6"),
]
S_RD = [
    ("ASTM D4253", "Maximum index density and unit weight of soils using a vibratory table"),
    ("ASTM D4254", "Minimum index density and unit weight of soils and calculation of relative density"),
]
S_DISP = [
    ("ASTM D6572", "Determining dispersive characteristics of clayey soils by the crumb test"),
    ("ASTM D4647", "Identification and classification of dispersive clay soils by the pinhole test"),
    ("ASTM D4221", "Dispersive characteristics of clay soil by double hydrometer"),
]

# --------------------------------------------------------------------------- #
# Worksheet fields
# --------------------------------------------------------------------------- #

CHEMISTRY_FIELDS = [
    _items("soil", "Soil determinations", [
        _t("specimen", "Specimen"),
        _n("ph", "pH (1:1 soil:water)", min=0, max=14),
        _n("so4_pct", "Water-soluble SO₄ (% of dry soil)", min=0, max=100),
        _mass("baso4", "BaSO₄ precipitate (g)"),
        _mass("aliquot", "Dry soil in the aliquot (g)"),
        _n("cl", "Water-soluble Cl (mg/kg)", min=0, max=1e6),
        _n("resistivity", "Resistivity, saturated (Ω·cm)", min=0, max=1e8),
    ], 6, "Soil", help="Sulfate as % directly, or the BaSO₄ precipitate with the dry soil mass of the aliquot (SO₄ = 0.4116 × BaSO₄)."),
    _items("water", "Water determinations", [
        _t("specimen", "Specimen"),
        _n("ph", "pH", min=0, max=14),
        _n("so4", "SO₄ (mg/L)", min=0, max=1e6),
        _n("cl", "Cl (mg/L)", min=0, max=1e6),
        _n("titrant", "AgNO₃ titrant (mL)", min=0, max=1000),
        _n("blank", "Blank (mL)", min=0, max=1000),
        _n("normality", "AgNO₃ normality (N)", min=0, max=10),
        _n("sample_ml", "Sample volume (mL)", min=0, max=10000),
    ], 6, "Groundwater", help="Chloride in mg/L directly, or the argentometric titration: Cl = (A − B) × N × 35 450 / sample volume."),
    F("seawater", "bool", "Groundwater is seawater or brackish", section="Groundwater"),
    _items("loi", "Loss on ignition", [
        _t("dish", "Dish No."),
        _mass("m_dish", "Dish (g)"),
        _mass("m_dry", "Dish + oven-dry soil (g)"),
        _mass("m_ash", "Dish + ash (g)"),
    ], 4, "Organic content", help="ASTM D2974 method C (440 °C)."),
]

PERMEABILITY_FIELDS = [
    _s("method", "Method", PERM_METHODS, "Specimen", default="constant"),
    _n("diameter", "Specimen diameter D (cm)", "Specimen", min=0, max=100),
    _n("length", "Specimen length L (cm)", "Specimen", min=0, max=200),
    _mass("dry_mass", "Dry mass of the specimen (g)", "Specimen"),
    _n("gs", "Specific gravity Gs (for void ratio)", "Specimen", min=1.5, max=4),
    _items("constant_trials", "Constant-head trials", [
        _n("head", "Head difference h (cm)", min=0, max=10000),
        _n("volume", "Volume Q (cm³)", min=0, max=1e6),
        _n("time", "Time t (s)", min=0, max=1e7),
        _n("temp", "Temperature (°C)", min=0, max=60),
    ], 10, "Constant head"),
    _n("standpipe", "Standpipe inside diameter d (cm)", "Falling head", min=0, max=50),
    _items("falling_trials", "Falling-head trials", [
        _n("h1", "Initial head h1 (cm)", min=0, max=10000),
        _n("h2", "Final head h2 (cm)", min=0, max=10000),
        _n("time", "Time t (s)", min=0, max=1e7),
        _n("temp", "Temperature (°C)", min=0, max=60),
    ], 10, "Falling head"),
]

PLT_TYPES: List[Option] = [("diametral", "Diametral"), ("axial", "Axial"), ("block", "Block"), ("lump", "Irregular lump")]

POINT_LOAD_FIELDS = [
    _t("rock", "Rock type", "Test", maxlen=80),
    _n("k_factor", "Conversion factor K (UCS = K · Is(50))", "Test", min=5, max=60, default=22,
       help="Left empty: 22. ASTM D5731 and ISRM give about 20–25 for many rocks; calibrate with UCS tests where possible."),
    _items("specimens", "Specimens", [
        _t("specimen", "Specimen"),
        _s("type", "Test", PLT_TYPES, default="diametral"),
        _n("d", "Distance between platens D (mm)", min=0, max=500),
        _n("w", "Width W (mm)", min=0, max=500),
        _n("d_failure", "D at failure D′ (mm)", min=0, max=500),
        _n("load", "Failure load P (kN)", min=0, max=1000),
        _s("valid", "Failure", [("valid", "Valid: through both platens"), ("invalid", "Invalid")], default="valid"),
    ], 40, "Specimens", help="Width W only for axial, block and lump tests (mean of the two widths for a lump). "
                              "D′ when the platens sink in before failure."),
]

RELATIVE_DENSITY_FIELDS = [
    _n("gs", "Specific gravity Gs (for void ratios)", "Specimen", min=1.5, max=4),
    _n("mold_volume", "Mold volume (cm³)", "Minimum index density", min=0, max=1e5),
    _mass("mold_mass", "Mold (g)", "Minimum index density"),
    _items("min_trials", "Minimum density trials", [_mass("m_total", "Mold + loose dry soil (g)")], 6, "Minimum index density",
           help="ASTM D4254 method A: soil poured loosely from a funnel."),
    _n("max_volume", "Mold volume for the maximum density (cm³)", "Maximum index density", min=0, max=1e5,
       help="Left empty: the same mold."),
    _n("mold_area", "Mold inside area (cm²)", "Maximum index density", min=0, max=1e4),
    _items("max_trials", "Maximum density trials", [
        _mass("m_total", "Mold + dry soil after vibration (g)"),
        _n("settlement", "Settlement of the surcharge plate (mm)", min=0, max=500),
    ], 6, "Maximum index density", help="ASTM D4253: vibratory table with surcharge. The settlement reduces the volume by area × settlement."),
    _n("rho_min_manual", "Minimum index density entered directly (g/cm³)", "Entered directly", min=0.3, max=3.5),
    _n("rho_max_manual", "Maximum index density entered directly (g/cm³)", "Entered directly", min=0.3, max=3.5),
    _items("field", "Field or specimen dry densities", [
        _t("point", "Point"),
        _n("rho_d", "Dry density ρd (g/cm³)", min=0.3, max=3.5),
        _n("gamma_d", "or dry unit weight γd (kN/m³)", min=3, max=35),
    ], 10, "Dry density"),
]

GRADES: List[Option] = [("1", "1"), ("2", "2"), ("3", "3"), ("4", "4")]
CLOUD: List[Option] = [("very_dark", "Very dark"), ("dark", "Dark"), ("moderately_dark", "Moderately dark"),
                       ("slightly_dark", "Slightly dark"), ("barely_visible", "Barely visible"), ("clear", "Perfectly clear")]

DISPERSIVITY_FIELDS = [
    _items("crumbs", "Crumb specimens", [
        _t("specimen", "Specimen"),
        _i("g_2min", "Grade at 2 min", min=1, max=4),
        _i("g_1h", "Grade at 1 h", min=1, max=4),
        _i("g_6h", "Grade at 6 h", min=1, max=4),
    ], 6, "Crumb test", help="Grade 1 no reaction, 2 slight reaction (faint colloid cloud), 3 moderate reaction, 4 strong reaction."),
    _items("pinhole", "Pinhole readings", [
        _n("head", "Head (mm)", min=0, max=2000),
        _n("volume", "Volume collected (mL)", min=0, max=10000),
        _n("time", "Time (s)", min=0, max=100000),
        _s("cloudiness", "Effluent", CLOUD),
    ], 20, "Pinhole test", help="Heads of 50, 180, 380 and 1020 mm (ASTM D4647 method A)."),
    _n("hole_mm", "Final pinhole diameter (mm)", "Pinhole test", min=0, max=20),
    _s("pinhole_class", "Pinhole class", PINHOLE, "Pinhole test", help="From the ASTM D4647 criteria for flow rate, effluent and final hole size."),
    _n("finer_without", "Finer than 5 µm without dispersant (%)", "Double hydrometer", min=0, max=100),
    _n("finer_with", "Finer than 5 µm with dispersant (%)", "Double hydrometer", min=0, max=100),
]

# --------------------------------------------------------------------------- #
# Examples
# --------------------------------------------------------------------------- #

NEW_EXAMPLES: Dict[str, Dict[str, Any]] = {
    "chemistry": {
        "soil": [{"specimen": "UDS-1", "ph": 6.8, "baso4": 0.0365, "aliquot": 10.0, "cl": 120.0, "resistivity": 2600.0},
                 {"specimen": "UDS-2", "ph": 6.6, "so4_pct": 0.12, "cl": 180.0, "resistivity": 1800.0}],
        "water": [{"specimen": "GW-1", "ph": 6.9, "so4": 420.0, "titrant": 2.85, "blank": 0.15, "normality": 0.0141, "sample_ml": 50.0}],
        "loi": [{"dish": "A1", "m_dish": 20.0, "m_dry": 45.0, "m_ash": 43.6}],
    },
    "permeability_lab": {
        "method": "constant", "diameter": 10.0, "length": 15.0, "dry_mass": 1885.0, "gs": 2.65,
        "constant_trials": [{"head": 60.0, "volume": 250.0, "time": 120.0, "temp": 25.0},
                            {"head": 60.0, "volume": 245.0, "time": 120.0, "temp": 25.0},
                            {"head": 80.0, "volume": 330.0, "time": 120.0, "temp": 25.0}],
    },
    "point_load": {
        "rock": "Batupasir", "k_factor": 22.0,
        "specimens": [{"specimen": str(i + 1), "type": "diametral", "d": d, "load": p, "valid": "valid"} for i, (d, p) in enumerate([
            (47.6, 3.9), (47.6, 4.4), (47.6, 4.1), (47.6, 3.2), (47.6, 4.8), (47.6, 4.0), (47.6, 4.3), (47.6, 3.7),
            (47.6, 4.6), (47.6, 4.2)])] + [{"specimen": "11", "type": "axial", "d": 40.0, "w": 50.0, "load": 6.0, "valid": "valid"}],
    },
    "relative_density": {
        "gs": 2.65, "mold_volume": 2830.0, "mold_mass": 4500.0,
        "min_trials": [{"m_total": 8459.0}, {"m_total": 8465.0}],
        "mold_area": 182.4,
        "max_trials": [{"m_total": 9450.0, "settlement": 2.0}],
        "field": [{"point": "TP-1", "rho_d": 1.6}],
    },
    "dispersivity": {
        "crumbs": [{"specimen": "UDS-1", "g_2min": 1, "g_1h": 2, "g_6h": 2}],
        "pinhole": [{"head": 50.0, "volume": 25.0, "time": 300.0, "cloudiness": "slightly_dark"},
                    {"head": 180.0, "volume": 120.0, "time": 300.0, "cloudiness": "barely_visible"},
                    {"head": 380.0, "volume": 210.0, "time": 300.0, "cloudiness": "clear"}],
        "hole_mm": 1.2, "pinhole_class": "ND3", "finer_without": 9.0, "finer_with": 36.0,
    },
}

# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

_SHEETS: List[Tuple[str, str, List[F], Callable[[Dict[str, Any]], Dict[str, Any]], List[Tuple[str, str]], str]] = [
    ("chemistry", "05.19", CHEMISTRY_FIELDS, calc_lab_ext.chemistry, S_CHEM,
     "pH, sulfate, chloride, resistivity and organic content: sulfate exposure class, cement and w/cm for concrete, corrosion of steel piles."),
    ("permeability_lab", "05.20", PERMEABILITY_FIELDS, calc_lab_ext.permeability_lab, S_PERM,
     "Constant- or falling-head permeability, corrected to 20 °C, mean of the trials."),
    ("point_load", "05.21", POINT_LOAD_FIELDS, calc_lab_ext.point_load, S_PLT,
     "Point load index Is(50) with size correction, estimated UCS and strength class of rock."),
    ("relative_density", "05.22", RELATIVE_DENSITY_FIELDS, calc_lab_ext.relative_density, S_RD,
     "Minimum and maximum index density of sand and the relative density of a field or specimen density."),
    ("dispersivity", "05.23", DISPERSIVITY_FIELDS, calc_lab_ext.dispersivity, S_DISP,
     "Crumb, pinhole and double hydrometer results: dispersive, intermediate or non-dispersive clay."),
]

_known = {k for k, _ in LAB_TESTS}
LAB_TESTS.extend(t for t in NEW_TESTS if t[0] not in _known)
LAB_RESULTS.update(NEW_RESULTS)
EXAMPLES.update(NEW_EXAMPLES)
_LABELS = dict(NEW_TESTS)
for _key, _code, _fields, _fn, _std, _help in _SHEETS:
    register(Sheet(key=_key, kind="lab", group="lab", code=_code, label=_LABELS[_key], fields=_fields,
                   calc=_bounded(_key, _fn), standards=list(_std), example=NEW_EXAMPLES[_key], help=_help))
