"""Laboratory worksheets: raw data and calculation per test (document group 05).

Each lab test record has a ``test_type``; its ``raw`` data follow the fields of the sheet
with that key, and the calculation's ``lab`` values are copied into the record's results
(whose fields are ``LAB_RESULTS[test_type]``).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from . import calc_lab
from .fields import F, Option
from .sheets import Sheet, register

# --------------------------------------------------------------------------- #
# Tests and their result fields
# --------------------------------------------------------------------------- #

LAB_TESTS: List[Tuple[str, str]] = [
    ("moisture", "Water content & density"),
    ("density", "Unit weight"),
    ("specific_gravity", "Specific gravity"),
    ("grain_size", "Grain size (sieve & hydrometer)"),
    ("atterberg", "Atterberg limits"),
    ("compaction", "Compaction (Proctor)"),
    ("cbr_lab", "CBR (laboratory)"),
    ("ucs", "Unconfined compression (UCS)"),
    ("triaxial", "Triaxial UU"),
    ("triaxial_cu", "Triaxial CU"),
    ("direct_shear", "Direct shear"),
    ("consolidation", "Consolidation"),
    ("swelling", "Swelling (one-dimensional)"),
    ("la_abrasion", "Los Angeles abrasion"),
    ("soundness", "Sulfate soundness"),
    ("slake_durability", "Slake durability"),
]

_GAMMA_BULK = F("gamma_bulk", "number", "Bulk unit weight γ (kN/m³)", min=5, max=30)
_GAMMA_DRY = F("gamma_dry", "number", "Dry unit weight γd (kN/m³)", min=3, max=30)
_C = F("c", "number", "Cohesion c (kPa)", min=0, max=5000)
_PHI = F("phi", "number", "Friction angle φ (°)", min=0, max=60)
_MDD = F("mdd", "number", "Maximum dry density MDD (g/cm³)", min=0.3, max=3.5)
_OMC = F("omc", "number", "Optimum water content OMC (%)", min=0, max=200)

LAB_RESULTS: Dict[str, List[F]] = {
    "moisture": [F("w", "number", "Moisture content w (%)", min=0, max=1000), _GAMMA_BULK, _GAMMA_DRY],
    "density": [_GAMMA_BULK, _GAMMA_DRY],
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
        F("d10", "number", "D10 (mm)", min=0, max=1000),
        F("d30", "number", "D30 (mm)", min=0, max=1000),
        F("d60", "number", "D60 (mm)", min=0, max=1000),
        F("cu", "number", "Coefficient of uniformity Cu", min=0, max=1e6),
        F("cc", "number", "Coefficient of curvature Cc", min=0, max=1e4),
        F("uscs", "text", "USCS group symbol", maxlen=12),
    ],
    "compaction": [_MDD, _OMC],
    "cbr_lab": [
        F("cbr", "number", "CBR (%)", min=0, max=500),
        F("swell", "number", "Swell (%)", min=-100, max=100),
        F("condition", "select", "Condition", options=[("soaked", "Soaked"), ("unsoaked", "Unsoaked")]),
        _MDD, _OMC,
    ],
    "ucs": [
        F("qu", "number", "Unconfined strength qu (kPa)", min=0, max=200000),
        F("strain", "number", "Strain at failure (%)", min=0, max=100),
        F("su", "number", "Undrained shear strength su (kPa)", min=0, max=100000),
        F("st", "number", "Sensitivity St", min=0, max=1000),
    ],
    "triaxial": [
        F("test", "select", "Test type", options=[("UU", "UU"), ("CU", "CU"), ("CD", "CD")]),
        _C, _PHI,
        F("cu", "number", "Undrained shear strength cu (kPa)", min=0, max=100000),
    ],
    "triaxial_cu": [
        F("c", "number", "Total cohesion c (kPa)", min=0, max=5000),
        F("phi", "number", "Total friction angle φ (°)", min=0, max=60),
        F("c_eff", "number", "Effective cohesion c' (kPa)", min=0, max=5000),
        F("phi_eff", "number", "Effective friction angle φ' (°)", min=0, max=60),
    ],
    "direct_shear": [_C, _PHI],
    "consolidation": [
        F("cc", "number", "Compression index Cc", min=0, max=10),
        F("cr", "number", "Recompression index Cr", min=0, max=5),
        F("e0", "number", "Initial void ratio e0", min=0, max=20),
        F("pc", "number", "Preconsolidation pressure σ'p (kPa)", min=0, max=100000),
        F("cv", "number", "Coefficient of consolidation cv (m²/year)", min=0, max=10000),
    ],
    "swelling": [
        F("swell", "number", "Swell (%)", min=-100, max=100),
        F("swell_pressure", "number", "Swell pressure (kPa)", min=0, max=100000),
    ],
    "la_abrasion": [F("loss", "number", "Abrasion loss (%)", min=0, max=100)],
    "soundness": [F("loss", "number", "Weighted loss (%)", min=0, max=100)],
    "slake_durability": [
        F("id1", "number", "Slake durability index Id1 (%)", min=0, max=100),
        F("id2", "number", "Slake durability index Id2 (%)", min=0, max=100),
        F("w", "number", "Natural water content (%)", min=0, max=1000),
    ],
}


def _bounded(key: str, fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Keep only calculated lab values the result fields accept, so the record can be saved again."""
    def run(data: Dict[str, Any]) -> Dict[str, Any]:
        out = fn(data)
        lab = out.get("lab")
        if isinstance(lab, dict):
            spec = {f.name: f for f in LAB_RESULTS.get(key, [])}
            kept: Dict[str, Any] = {}
            for name, value in lab.items():
                f = spec.get(name)
                if f is None:
                    continue
                if f.type == "number" and isinstance(value, (int, float)):
                    if (f.min is not None and value < f.min) or (f.max is not None and value > f.max):
                        continue
                if f.type == "select" and value not in [o[0] for o in f.options or []]:
                    continue
                kept[name] = value
            out["lab"] = kept
        return out
    return run


# --------------------------------------------------------------------------- #
# Field helpers
# --------------------------------------------------------------------------- #

def _n(name: str, label: str, section: str = "", min: Optional[float] = None, max: Optional[float] = None,
       help: str = "", default: Any = None) -> F:
    return F(name, "number", label, section=section, min=min, max=max, help=help, default=default)


def _i(name: str, label: str, section: str = "", min: Optional[float] = 0, max: Optional[float] = 100000,
       default: Any = None) -> F:
    return F(name, "int", label, section=section, min=min, max=max, default=default)


def _t(name: str, label: str, section: str = "", maxlen: int = 40) -> F:
    return F(name, "text", label, section=section, maxlen=maxlen)


def _s(name: str, label: str, options: List[Option], section: str = "", default: Any = None, help: str = "") -> F:
    return F(name, "select", label, options=options, section=section, default=default, help=help)


def _items(name: str, label: str, fields: List[F], max_items: int, section: str = "", help: str = "") -> F:
    return F(name, "items", label, fields=fields, max_items=max_items, section=section, help=help)


MASS = 1e6  # upper bound for masses in g


def _mass(name: str, label: str, section: str = "") -> F:
    return _n(name, label, section, min=0, max=MASS)


RING_UNITS: List[Option] = [("kN", "kN/div"), ("kgf", "kgf/div"), ("lbf", "lbf/div")]
STRESS_UNITS: List[Option] = [("kgcm2", "kg/cm²"), ("kpa", "kPa")]
AXIAL_UNITS: List[Option] = [("0.01mm", "Dial divisions of 0.01 mm"), ("mm", "mm")]


def _ring(default_factor: Optional[float], default_unit: str) -> List[F]:
    sec = "Proving ring"
    help_text = "Load per dial division from the ring's calibration certificate. " + (
        f"Left empty: {default_factor:g} {dict(RING_UNITS)[default_unit]}." if default_factor else "Enter the calibration of your ring.")
    return [
        _t("ring_no", "Proving ring No.", sec),
        _n("ring_factor", "Proving ring factor", sec, min=0, max=1e5, help=help_text, default=default_factor),
        _s("ring_unit", "Unit of the ring factor", RING_UNITS, sec, default=default_unit),
    ]


def _container(suffix: str = "", section: str = "", label_suffix: str = "") -> List[F]:
    return [
        _mass("m_wet" + suffix, "Container + wet soil (g)" + label_suffix, section),
        _mass("m_dry" + suffix, "Container + dry soil (g)" + label_suffix, section),
        _mass("m_tare" + suffix, "Container (g)" + label_suffix, section),
    ]


def _stress_unit(default: str = "kgcm2") -> F:
    return _s("stress_unit", "Unit of pressures", STRESS_UNITS, "Options", default=default)


# --------------------------------------------------------------------------- #
# Standards (SNI ↔ ASTM)
# --------------------------------------------------------------------------- #

S_WC = [("SNI 1965:2008", "Test method for water content of soil and rock in the laboratory"),
        ("ASTM D2216-19", "Laboratory determination of water (moisture) content of soil and rock by mass"),
        ("ASTM D7263", "Laboratory determination of density and unit weight of soil specimens")]
S_SG = [("SNI 1964:2008", "Test method for specific gravity of soil"),
        ("ASTM D854-23", "Specific gravity of soil solids by water pycnometer")]
S_GS = [("SNI 3423:2008", "Test method for particle-size analysis of soil"),
        ("SNI 2435:2008", "Hydrometer analysis of soil"),
        ("ASTM D6913-17", "Particle-size distribution (gradation) of soils using sieve analysis"),
        ("ASTM D7928-17", "Particle-size distribution of fine-grained soils using the sedimentation (hydrometer) analysis"),
        ("ASTM D422", "Particle-size analysis of soils (withdrawn)"),
        ("SNI 6371:2015", "Classification of soils for engineering purposes (unified soil classification system)"),
        ("ASTM D2487", "Classification of soils for engineering purposes (unified soil classification system)")]
S_AL = [("SNI 1967:2008", "Test method for liquid limit of soil"),
        ("SNI 1966:2008", "Test method for plastic limit and plasticity index of soil"),
        ("ASTM D4318-17", "Liquid limit, plastic limit, and plasticity index of soils"),
        ("SNI 6371:2015", "Classification of soils for engineering purposes (unified soil classification system)")]
S_PR = [("SNI 1742:2008", "Test method for standard compaction of soil"),
        ("SNI 1743:2008", "Test method for modified compaction of soil"),
        ("ASTM D698", "Laboratory compaction characteristics of soil using standard effort"),
        ("ASTM D1557", "Laboratory compaction characteristics of soil using modified effort")]
S_CBR = [("SNI 1744:2012", "Test method for laboratory CBR"),
         ("ASTM D1883", "California Bearing Ratio (CBR) of laboratory-compacted soils")] + S_PR
S_UCS = [("SNI 3638:2012", "Test method for unconfined compressive strength of cohesive soil"),
         ("ASTM D2166-16", "Unconfined compressive strength of cohesive soil")]
S_UU = [("SNI 4813:2015", "Test method for unconsolidated-undrained triaxial compression of cohesive soils"),
        ("ASTM D2850-15", "Unconsolidated-undrained triaxial compression test on cohesive soils")]
S_CU = [("ASTM D4767", "Consolidated undrained triaxial compression test for cohesive soils"),
        ("SNI 2455:2015", "Consolidated undrained triaxial test (number to be verified)")]
S_DS = [("SNI 2813:2008", "Test method for consolidated drained direct shear of soil"),
        ("ASTM D3080", "Direct shear test of soils under consolidated drained conditions")]
S_CO = [("SNI 2475:2008", "Test method for one-dimensional consolidation of soil"),
        ("ASTM D2435/D2435M-11", "One-dimensional consolidation properties of soils using incremental loading")]
S_SW = [("ASTM D4546-14", "One-dimensional swell or collapse of soils")]
S_LA = [("ASTM C131", "Resistance to degradation of small-size coarse aggregate by abrasion and impact in the Los Angeles machine"),
        ("ASTM C535", "Resistance to degradation of large-size coarse aggregate by abrasion and impact in the Los Angeles machine"),
        ("SNI 2417:2008", "Test method for abrasion of aggregate with the Los Angeles machine (number to be verified)")]
S_SO = [("ASTM C88", "Soundness of aggregates by use of sodium sulfate or magnesium sulfate"),
        ("SNI 3407:2008", "Test method for soundness of aggregate with sodium sulfate or magnesium sulfate (number to be verified)")]
S_SD = [("ASTM D4644", "Slake durability of shales and other similar weak rocks")]


# --------------------------------------------------------------------------- #
# Worksheet fields
# --------------------------------------------------------------------------- #

MOISTURE_FIELDS = [
    _items("specimens", "Specimens", [
        _t("ring_no", "Ring / container No."),
        _mass("m_wet", "Ring + wet soil (g)"),
        _mass("m_dry", "Ring + dry soil (g)"),
        _mass("m_tare", "Ring (g)"),
        _n("volume", "Ring volume (cm³)", min=0, max=1e5),
    ], 10, "Specimens", help="Leave the volume empty for water content only."),
    _n("gs", "Specific gravity Gs (for void ratio)", "Options", min=1.5, max=4),
]

SG_FIELDS = [
    _items("determinations", "Determinations", [
        _t("pycnometer_no", "Pycnometer No."),
        _n("temp", "Temperature (°C)", min=0, max=60),
        _mass("m_ps", "Pycnometer + dry soil (g)"),
        _mass("m_p", "Pycnometer (g)"),
        _mass("m_pw", "Pycnometer + water (g)"),
        _mass("m_pws", "Pycnometer + water + soil (g)"),
    ], 6, "Determinations", help="Pycnometer + water may be left empty when that pycnometer is calibrated below."),
    _items("calibration", "Pycnometer calibration", [
        _t("pycnometer_no", "Pycnometer No."),
        _n("temp", "Temperature (°C)", min=0, max=60),
        _mass("m_p", "Pycnometer (g)"),
        _mass("m_pw", "Pycnometer + water (g)"),
    ], 30, "Pycnometer calibration"),
]

GRAIN_FIELDS = [
    _mass("m_dry_total", "Dry mass of the whole sample (g)", "Specimen"),
    _mass("m_hydro", "Dry mass of the fine specimen (g)", "Specimen"),
    _s("split_sieve", "Fine specimen passes sieve", [("2.00", "#10 (2.00 mm)"), ("0.425", "#40 (0.425 mm)")], "Specimen", default="2.00"),
    _n("gs", "Specific gravity Gs", "Specimen", min=1.5, max=4),
    _items("sieves", "Sieves", [
        _t("sieve", "Sieve", maxlen=12),
        _n("opening", "Opening (mm)", min=0, max=500),
        _mass("retained", "Mass retained (g)"),
    ], 25, "Sieve analysis", help="Sieves finer than the split sieve are on the washed fine specimen."),
    _s("hydrometer_type", "Hydrometer", [("151H", "151H"), ("152H", "152H")], "Hydrometer", default="151H"),
    _s("hydro_method", "Hydrometer calculation", [
        ("astm", "ASTM D422: percent finer from the corrected reading"),
        ("template", "Template: percent finer from the uncorrected reading")], "Hydrometer", default="astm"),
    _n("zero_corr", "Correction subtracted from each reading", "Hydrometer", min=-100, max=100,
       help="Zero and meniscus correction. 0 when the readings are already reduced."),
    _items("hydrometer", "Hydrometer readings", [
        _n("t_min", "Time (min)", min=0, max=100000),
        _n("temp", "Temperature (°C)", min=0, max=60),
        _n("reading", "Reading", min=-100, max=100),
        _n("k", "Temperature correction", min=-100, max=100),
    ], 25, "Hydrometer"),
    _n("ll", "Liquid limit LL (%)", "Classification (optional)", min=0, max=500),
    _n("pi", "Plasticity index PI (%)", "Classification (optional)", min=0, max=500),
]

ATTERBERG_FIELDS = [
    _items("ll_trials", "Liquid limit trials", [
        _i("blows", "Blows N", min=1, max=200),
        _t("container", "Container No."),
        *_container(),
    ], 6, "Liquid limit"),
    _items("pl_trials", "Plastic limit trials", [_t("container", "Container No."), *_container()], 4, "Plastic limit"),
    F("non_plastic", "bool", "Non-plastic (plastic limit cannot be determined)", section="Plastic limit"),
    _n("w_natural", "Natural water content (%)", "Options", min=0, max=1000, help="For the liquidity and consistency index."),
]

PROCTOR_POINT = [
    _mass("m_mold_soil", "Mold + compacted soil (g)"),
    _mass("m_mold", "Mold (g)"),
    _n("volume", "Mold volume (cm³)", min=0, max=1e5),
    *_container(),
    *_container("_2", label_suffix=", 2nd container"),
]

FIT_OPTIONS: List[Option] = [("poly", "Polynomial fit (cubic for five or more points)"),
                             ("parabola", "Parabola through the highest point and its neighbours")]

COMPACTION_FIELDS = [
    _s("method", "Compaction effort", [("standard", "Standard Proctor"), ("modified", "Modified Proctor")], "Method", default="standard"),
    _s("procedure", "Procedure", [("A", "A"), ("B", "B"), ("C", "C")], "Method"),
    _n("mold_volume", "Mold volume (cm³)", "Method", min=0, max=1e5, help="Used for points without their own volume."),
    _i("layers", "Layers", "Method", min=1, max=10),
    _i("blows_per_layer", "Blows per layer", "Method", min=1, max=200),
    _n("gs", "Specific gravity Gs (zero air voids line)", "Method", min=1.5, max=4),
    _n("w_natural", "Natural water content (%)", "Method", min=0, max=1000),
    _items("points", "Compaction points", PROCTOR_POINT, 12, "Compaction points"),
    _s("curve_fit", "Curve fit", FIT_OPTIONS, "Options", default="poly"),
    _n("mdd_manual", "MDD entered manually (g/cm³)", "Options", min=0.3, max=3.5),
    _n("omc_manual", "OMC entered manually (%)", "Options", min=0, max=200),
]

CBR_FIELDS = [
    _s("soaked", "Condition", [("soaked", "Soaked"), ("unsoaked", "Unsoaked")], "Test", default="soaked"),
    _s("cbr_rule", "CBR value", [
        ("astm", "ASTM: 2.54 mm value (5.08 mm if higher on retest)"),
        ("average", "Average of 2.54 and 5.08 mm"),
        ("min", "Lower of the two")], "Test", default="astm"),
    _s("pen_unit", "Unit of penetration", [("in", "inch"), ("mm", "mm")], "Test", default="in"),
    _n("piston_area", "Piston area (cm²)", "Test", min=0, max=1000, help="Left empty: 19.35 cm² (3 in²).", default=19.3548),
    _n("height", "Initial specimen height (mm)", "Test", min=0, max=1000, help="Left empty: 116.43 mm.", default=116.43),
    _n("swell_factor", "Swell dial (mm per division)", "Test", min=0, max=10, help="Left empty: 0.0254 mm (0.001 in).", default=0.0254),
    *_ring(3.38, "lbf"),
    _items("specimens", "Specimens", [
        _i("blows", "Blows per layer", min=1, max=200),
        _mass("m_mold_soil", "Mold + soil (g)"),
        _mass("m_mold", "Mold (g)"),
        _n("volume", "Mold volume (cm³)", min=0, max=1e5),
        *_container(),
        _n("zero_corr", "Origin correction (same unit as penetration)", min=0, max=100),
    ], 3, "Specimens", help="Water content from the soil after the test. Leave the origin correction empty for the automatic tangent."),
    _items("penetration", "Penetration readings", [
        _n("pen", "Penetration", min=0, max=1000),
        _n("load_1", "Load dial, specimen 1", min=-1e6, max=1e6),
        _n("load_2", "Load dial, specimen 2", min=-1e6, max=1e6),
        _n("load_3", "Load dial, specimen 3", min=-1e6, max=1e6),
    ], 40, "Penetration"),
    _items("swell", "Swell readings", [
        _n("day", "Day", min=0, max=60),
        _n("swell_1", "Swell dial, specimen 1", min=-1e6, max=1e6),
        _n("swell_2", "Swell dial, specimen 2", min=-1e6, max=1e6),
        _n("swell_3", "Swell dial, specimen 3", min=-1e6, max=1e6),
    ], 15, "Swell"),
    _s("design_pct", "Design density", [("95", "95 % of MDD"), ("90", "90 % of MDD"), ("100", "100 % of MDD")], "Design CBR", default="95"),
    _n("compaction_volume", "Proctor mold volume (cm³)", "Design CBR", min=0, max=1e5),
    _n("gs", "Specific gravity Gs (zero air voids line)", "Design CBR", min=1.5, max=4),
    _items("compaction", "Compaction points", PROCTOR_POINT, 12, "Design CBR", help="Or enter MDD and OMC below."),
    _n("mdd_manual", "MDD entered manually (g/cm³)", "Design CBR", min=0.3, max=3.5),
    _n("omc_manual", "OMC entered manually (%)", "Design CBR", min=0, max=200),
]

UCS_FIELDS = [
    _n("diameter", "Diameter (cm)", "Specimen", min=0, max=100),
    _n("height", "Height (cm)", "Specimen", min=0, max=200),
    _mass("mass", "Specimen mass (g)", "Specimen"),
    *_container(section="Water content"),
    *_ring(0.35, "kgf"),
    _s("axial_unit", "Unit of deformation", AXIAL_UNITS, "Readings", default="mm"),
    _items("readings", "Readings", [
        _n("deformation", "Deformation", min=0, max=100000),
        _n("dial_undisturbed", "Load dial, undisturbed", min=-1e6, max=1e6),
        _n("dial_remolded", "Load dial, remolded", min=-1e6, max=1e6),
        _n("time", "Time", min=0, max=1e6),
    ], 200, "Readings"),
]

UU_FIELDS = [
    _items("specimens", "Specimens", [
        _n("cell_pressure", "Cell pressure σ3", min=0, max=100000),
        _n("height", "Height (cm)", min=0, max=200),
        _n("diameter", "Diameter (cm)", min=0, max=100),
        _mass("m_wet", "Wet mass (g)"),
        _mass("m_dry", "Dry mass (g)"),
    ], 3, "Specimens", help="Row 1 belongs to the load column of specimen 1, and so on."),
    _stress_unit(),
    *_ring(0.35, "kgf"),
    _s("axial_unit", "Unit of axial deformation", AXIAL_UNITS, "Readings", default="0.01mm"),
    _items("readings", "Readings", [
        _n("axial", "Axial dial", min=0, max=100000),
        _n("load_1", "Load dial, specimen 1", min=-1e6, max=1e6),
        _n("load_2", "Load dial, specimen 2", min=-1e6, max=1e6),
        _n("load_3", "Load dial, specimen 3", min=-1e6, max=1e6),
    ], 200, "Readings"),
]

CU_FIELDS = [
    _items("specimens", "Specimens", [
        _n("cell_pressure", "Cell pressure", min=0, max=100000),
        _n("back_pressure", "Back pressure", min=0, max=100000),
        _n("b_value", "B-value", min=0, max=1.5),
        _n("height", "Height (cm)", min=0, max=200),
        _n("diameter", "Diameter (cm)", min=0, max=100),
        _n("dv_consolidation", "Volume change in consolidation (cm³)", min=-1e4, max=1e4),
        _mass("m_wet_before", "Wet mass before test (g)"),
        _mass("m_wet_after", "Wet mass after test (g)"),
        _mass("m_dry", "Dry mass (g)"),
    ], 3, "Specimens", help="Row 1 belongs to the columns of specimen 1, and so on."),
    _stress_unit(),
    _s("failure", "Failure criterion", [("max_dev", "Maximum deviator stress"),
                                        ("max_ratio", "Maximum effective stress ratio σ1'/σ3'")], "Options", default="max_dev"),
    _n("membrane_e", "Membrane modulus (kPa)", "Options", min=0, max=1e5, help="With the thickness: membrane correction."),
    _n("membrane_t", "Membrane thickness (mm)", "Options", min=0, max=10),
    *_ring(None, "kgf"),
    _s("axial_unit", "Unit of axial deformation", AXIAL_UNITS, "Readings", default="0.01mm"),
    _items("readings", "Readings", [
        _n("axial", "Axial dial", min=0, max=100000),
        _n("load_1", "Load dial, specimen 1", min=-1e6, max=1e6),
        _n("u_1", "Pore pressure, specimen 1", min=-1e5, max=1e5),
        _n("load_2", "Load dial, specimen 2", min=-1e6, max=1e6),
        _n("u_2", "Pore pressure, specimen 2", min=-1e5, max=1e5),
        _n("load_3", "Load dial, specimen 3", min=-1e6, max=1e6),
        _n("u_3", "Pore pressure, specimen 3", min=-1e5, max=1e5),
    ], 200, "Readings", help="Pore pressure as measured (absolute), in the unit of pressures."),
]

DS_FIELDS = [
    _items("specimens", "Specimens", [
        _n("normal_stress", "Normal stress", min=0, max=100000),
        _n("area", "Area (cm²)", min=0, max=10000),
        _n("volume", "Volume (cm³)", min=0, max=1e5),
        *_container(),
    ], 4, "Specimens", help="Masses with the ring as container. Left empty, the area is 28.27 cm² (60 mm diameter)."),
    _n("gs", "Specific gravity Gs", "Specimens", min=1.5, max=4),
    _stress_unit(),
    _s("conversion", "Stress conversion", [("standard", "Standard: 1 kg/cm² = 98.0665 kPa"),
                                           ("template", "Template: shear stress × 102, normal stress × 98.1")], "Options", default="standard"),
    *_ring(0.12, "kgf"),
    _items("readings", "Readings", [
        _n("displacement", "Horizontal displacement (mm)", min=0, max=1000),
        _n("dial_1", "Load dial, specimen 1", min=-1e6, max=1e6),
        _n("dial_2", "Load dial, specimen 2", min=-1e6, max=1e6),
        _n("dial_3", "Load dial, specimen 3", min=-1e6, max=1e6),
        _n("dial_4", "Load dial, specimen 4", min=-1e6, max=1e6),
    ], 200, "Readings"),
]

CONSOLIDATION_FIELDS = [
    _t("ring_no", "Ring No.", "Specimen"),
    _n("h0", "Initial height (mm)", "Specimen", min=0, max=1000),
    _n("diameter", "Diameter (mm)", "Specimen", min=0, max=1000),
    _mass("m_ring", "Ring (g)", "Specimen"),
    _mass("m_ring_soil", "Ring + specimen (g)", "Specimen"),
    _n("gs", "Specific gravity Gs", "Specimen", min=1.5, max=4),
    _n("dial_zero", "Initial dial reading (mm)", "Specimen", min=-1000, max=1000),
    _mass("m_tare", "Container (g)", "After test"),
    _mass("m_wet_after", "Container + wet soil after test (g)", "After test"),
    _mass("m_dry_after", "Container + dry soil after test (g)", "After test"),
    _stress_unit(),
    _n("sigma_v0", "In-situ effective vertical stress σ'v0", "Options", min=0, max=1e5, help="For the overconsolidation ratio."),
    _s("cc_points", "Compression index from", [("last2", "Last two loading points"), ("last3", "Regression over the last three loading points")],
       "Options", default="last2"),
    _s("cv_method", "cv from time readings", [("taylor", "Square root of time (Taylor)"), ("casagrande", "Log time (Casagrande)")],
       "Options", default="taylor"),
    _n("pc_manual", "Preconsolidation pressure entered manually", "Options", min=0, max=1e5),
    _items("increments", "Load increments", [
        _n("pressure", "Pressure", min=0, max=1e5),
        _n("dial", "Final dial reading (mm)", min=-1000, max=1000),
        _n("t90", "t90 (min)", min=0, max=1e5),
        _n("cv", "cv (cm²/s)", min=0, max=100),
    ], 25, "Load increments", help="In loading order, then unloading. cv or t90 may be entered from your own time curves."),
    _items("time_readings", "Time readings", [
        _n("pressure", "Pressure", min=0, max=1e5),
        _n("t_min", "Time (min)", min=0, max=1e5),
        _n("dial", "Dial reading (mm)", min=-1000, max=1000),
    ], 400, "Time readings", help="The pressure links each reading to its load increment."),
]

SWELL_PHASES: List[Option] = [("seating", "Seating"), ("load", "Loading"), ("before_wetting", "Before wetting"),
                              ("after_wetting", "After wetting"), ("unload", "Unloading")]

SWELL_FIELDS = [
    _n("h0", "Initial height (mm)", "Specimen", min=0, max=1000),
    _n("diameter", "Diameter (mm)", "Specimen", min=0, max=1000),
    _mass("m_ring", "Ring (g)", "Specimen"),
    _mass("m_ring_soil", "Ring + specimen (g)", "Specimen"),
    _n("gs", "Specific gravity Gs", "Specimen", min=1.5, max=4),
    _n("dial_zero", "Initial dial reading (mm)", "Specimen", min=-1000, max=1000),
    _mass("m_tare", "Container (g)", "After test"),
    _mass("m_wet_after", "Container + wet soil after test (g)", "After test"),
    _mass("m_dry_after", "Container + dry soil after test (g)", "After test"),
    _items("steps", "Load steps", [
        _n("stress", "Vertical stress (kPa)", min=0, max=1e5),
        _n("dial", "Final dial reading (mm)", min=-1000, max=1000),
        _s("phase", "Step", SWELL_PHASES),
    ], 25, "Load steps", help="Mark the step before wetting and the step after wetting at the same stress."),
    _items("time_readings", "Readings after wetting", [
        _n("t_min", "Time (min)", min=0, max=1e6),
        _n("dial", "Dial reading (mm)", min=-1000, max=1000),
    ], 60, "Readings after wetting"),
]

LA_GRADINGS: List[Option] = [("A", "A (ASTM C131)"), ("B", "B (ASTM C131)"), ("C", "C (ASTM C131)"), ("D", "D (ASTM C131)"),
                             ("1", "1 (ASTM C535)"), ("2", "2 (ASTM C535)"), ("3", "3 (ASTM C535)")]

LA_FIELDS = [
    _s("grading", "Grading", LA_GRADINGS, "Test", default="A"),
    _i("revolutions", "Revolutions", "Test", min=1, max=10000),
    _items("fractions", "Size fractions", [
        _n("passing", "Passing (mm)", min=0, max=200),
        _n("retained", "Retained (mm)", min=0, max=200),
        _mass("mass_1", "Mass, trial 1 (g)"),
        _mass("mass_2", "Mass, trial 2 (g)"),
    ], 12, "Size fractions"),
    _mass("retained_1", "Retained on 1.70 mm after test, trial 1 (g)", "After test"),
    _mass("retained_2", "Retained on 1.70 mm after test, trial 2 (g)", "After test"),
]

SOUNDNESS_FIELDS = [
    _s("solution", "Solution", [("sodium", "Sodium sulfate"), ("magnesium", "Magnesium sulfate")], "Test", default="sodium"),
    _s("aggregate", "Aggregate", [("fine", "Fine aggregate"), ("coarse", "Coarse aggregate")], "Test", default="fine"),
    _i("cycles", "Cycles", "Test", min=1, max=50, default=5),
    _items("fractions", "Size fractions", [
        _t("size", "Size fraction", maxlen=40),
        _n("grading", "Grading of the original sample (%)", min=0, max=100),
        _mass("mass_before", "Mass before test (g)"),
        _mass("mass_after", "Mass after test (g)"),
    ], 12, "Size fractions", help="Leave the masses empty for a fraction that was not tested."),
]

SLAKE_FIELDS = [
    _mass("m_natural", "Drum + sample at natural water content (g)", "Masses"),
    _mass("m_dry_before", "Drum + oven-dried sample before the first cycle (g)", "Masses"),
    _mass("m_drum", "Drum (g)", "Masses"),
    _s("fragment_type", "Fragment type", [("I", "I: pieces virtually unchanged"), ("II", "II: large and small pieces"),
                                          ("III", "III: only small fragments")], "Masses"),
    _items("cycles", "Cycles", [
        _i("cycle", "Cycle", min=1, max=10),
        _mass("m_after", "Drum + oven-dried retained sample (g)"),
    ], 5, "Cycles"),
]


# --------------------------------------------------------------------------- #
# Examples (cleaned shape), from the laboratory's example worksheets
# --------------------------------------------------------------------------- #

def _pen_rows() -> List[Dict[str, Any]]:
    pens = [0, 0.025, 0.05, 0.075, 0.1, 0.125, 0.15, 0.175, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5]
    d1 = [0, 3, 4, 5, 6, 6.5, 7, 7.5, 8, 10, 11, 12, 14, 15, 16]
    d2 = [0, 13.824, 20.736, 25.92, 31.104, 34.56, 38.016, 41.472, 44.928, 50.112, 55.296, 62.208, 67.392, 72.576, 77.76]
    d3 = [0, 19, 39, 57, 73, 90, 105, 120, 135, 161, 184, 205, 225, 244, 260]
    return [{"pen": p, "load_1": a, "load_2": b, "load_3": c} for p, a, b, c in zip(pens, d1, d2, d3)]


def _uu_rows() -> List[Dict[str, Any]]:
    axial = [0, 20, 40, 60, 80, 100, 120, 140, 160, 180, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750,
             800, 850, 900, 950, 1000, 1100, 1200, 1300, 1400, 1500]
    l1 = [0, 26, 43, 56, 63, 69, 75, 79, 83, 87, 90, 96, 102, 107, 112, 116, 120, 124, 128, 132, 136, 139, 142, 144,
          144, 145, 147, 149, 150, 151, 152, 153]
    l2 = [0, 32, 50, 63, 72, 80, 87, 92, 97, 102, 105, 113, 120, 127, 132, 137, 142, 146, 151, 156, 160, 164, 167, 170,
          172, 174, 175, 177, 179, 179, 180, 181]
    l3 = [0, 40, 58, 72, 86, 96, 104, 111, 118, 123, 128, 138, 147, 155, 163, 169, 175, 182, 188, 192, 197, 201, 204,
          207, 209, 211, 213, 213, 211, 209, 203, 199]
    return [{"axial": a, "load_1": x, "load_2": y, "load_3": z} for a, x, y, z in zip(axial, l1, l2, l3)]


def _cu_rows() -> List[Dict[str, Any]]:
    axial = [0, 20, 40, 60, 80, 100, 120, 140, 160, 180, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750,
             800, 850, 900, 950, 1000, 1100, 1200, 1300, 1400, 1500]
    l1: List[Optional[float]] = [0, 25, 37, 38, 42, 45, 48, 51, 53, 55, 57, 59, 64, 66, 68, 70, 71, 72, 73, 74, 74.5, 75,
                                 75, 75, 75, 75, 74.5, 74, 74, None, None, None]
    u1: List[Optional[float]] = [2, 2.08, 2.11, 2.14, 2.15, 2.16, 2.18, 2.19, 2.19, 2.2, 2.21, 2.22, 2.23, 2.23, 2.23, 2.23,
                                 2.23, 2.23, 2.23, 2.23, 2.23, 2.23, 2.23, 2.23, 2.23, 2.23, 2.23, 2.23, 2.23, None, None, None]
    l2 = [0, 40, 51, 58, 63, 67, 70, 72, 74, 76, 78, 81, 84, 87, 90, 93, 96, 98, 100, 102, 104, 106, 108, 109, 110, 111,
          111, 111, 111, 111, 111, 111]
    u2 = [2.25, 2.4, 2.5, 2.55, 2.58, 2.6, 2.62, 2.64, 2.65, 2.66, 2.67, 2.68, 2.7, 2.71, 2.72, 2.73, 2.73, 2.73, 2.74,
          2.74, 2.74, 2.74, 2.74, 2.74, 2.74, 2.74, 2.74, 2.74, 2.74, 2.74, 2.74, 2.74]
    l3 = [0, 45, 61, 72, 85, 88, 94, 99, 105, 111, 116, 121, 125, 132, 136, 140, 144, 148, 151, 154, 157, 160, 162, 164,
          165, 166, 167, 168, 169, 169, 169, 169]
    u3 = [2.5, 2.78, 2.99, 3.05, 3.11, 3.18, 3.23, 3.27, 3.31, 3.35, 3.39, 3.42, 3.44, 3.47, 3.5, 3.52, 3.53, 3.54, 3.55,
          3.55, 3.55, 3.55, 3.55, 3.55, 3.55, 3.55, 3.55, 3.55, 3.55, 3.55, 3.55, 3.55]
    return [{"axial": a, "load_1": p1, "u_1": q1, "load_2": p2, "u_2": q2, "load_3": p3, "u_3": q3}
            for a, p1, q1, p2, q2, p3, q3 in zip(axial, l1, u1, l2, u2, l3, u3)]


def _ds_rows() -> List[Dict[str, Any]]:
    disp = [0, 0.3, 0.6, 0.9, 1.2, 1.5, 1.8, 2.1, 2.4, 2.7, 3, 3.3, 3.3, 3.6, 3.9, 4.2, 4.5, 4.8, 5.1, 5.4, 5.7, 6, 6.3, 6.6]
    d1: List[Optional[float]] = [0, 41, 50, 55, 61, 67, 71, 72, 73, 77, 78, 79, 81, 83, 85, 86, 86.5, 87, 87, 87, 85, 83, 81, None]
    d2 = [0, 47, 53, 60, 68, 72, 77, 82, 85, 89, 93, 99, 104, 109, 114, 118, 121, 123, 125, 125, 127, 125, 123, 119]
    return [{"displacement": x, "dial_1": a, "dial_2": b} for x, a, b in zip(disp, d1, d2)]


EXAMPLES: Dict[str, Dict[str, Any]] = {
    "moisture": {"specimens": [{"ring_no": "F21", "m_wet": 100.27, "m_dry": 82.18, "m_tare": 34.15, "volume": 36.89}]},
    "specific_gravity": {
        "determinations": [
            {"pycnometer_no": "43", "temp": 26.0, "m_ps": 69.327, "m_p": 58.886, "m_pw": 108.963, "m_pws": 115.448},
            {"pycnometer_no": "44", "temp": 26.0, "m_ps": 53.369, "m_p": 42.592, "m_pw": 97.831, "m_pws": 104.524}],
        "calibration": [{"pycnometer_no": "1", "temp": 25.0, "m_p": 45.68, "m_pw": m} for m in (103.1, 103.1, 103.0, 103.0, 103.0)],
    },
    "grain_size": {
        "m_dry_total": 50.0, "m_hydro": 50.0, "split_sieve": "2.00", "gs": 2.63,
        "sieves": [{"sieve": s, "opening": o, "retained": m} for s, o, m in [
            ('2"', 50.8, 0.0), ('1.5"', 38.1, 0.0), ('1"', 25.4, 0.0), ('3/4"', 19.0, 0.0), ('3/8"', 9.51, 0.0),
            ("#4", 4.76, 0.0), ("#10", 2.0, 0.0), ("#16", 1.19, 0.0), ("#30", 0.595, 0.0), ("#50", 0.297, 0.08),
            ("#100", 0.149, 0.53), ("#200", 0.074, 1.26)]],
        "hydrometer_type": "151H", "hydro_method": "astm", "zero_corr": 0.0,
        "hydrometer": [{"t_min": t, "temp": tc, "reading": r, "k": k} for t, tc, r, k in [
            (0.5, 26.0, 1.026, 0.0009), (1.0, 26.0, 1.0235, 0.0009), (2.0, 26.0, 1.021, 0.0009), (5.0, 26.0, 1.018, 0.0009),
            (15.0, 26.0, 1.015, 0.0009), (30.0, 26.0, 1.013, 0.0009), (60.0, 26.0, 1.011, 0.0009), (120.0, 26.0, 1.009, 0.0009),
            (250.0, 26.0, 1.0075, 0.0009), (1440.0, 25.0, 1.005, 0.0007)]],
    },
    "atterberg": {
        "ll_trials": [{"blows": 8.0, "m_wet": 33.67, "m_dry": 28.59, "m_tare": 11.19},
                      {"blows": 19.0, "m_wet": 38.71, "m_dry": 32.2, "m_tare": 8.57},
                      {"blows": 34.0, "m_wet": 36.66, "m_dry": 31.34, "m_tare": 11.14},
                      {"blows": 43.0, "m_wet": 34.21, "m_dry": 28.85, "m_tare": 8.24}],
        "pl_trials": [{"m_wet": 16.45, "m_dry": 15.41, "m_tare": 8.8}, {"m_wet": 16.28, "m_dry": 15.59, "m_tare": 11.24}],
        "w_natural": 28.6,
    },
    "compaction": {
        "method": "standard", "mold_volume": 943.0, "layers": 3.0, "blows_per_layer": 25.0, "gs": 2.63, "w_natural": 28.6,
        "curve_fit": "poly",
        "points": [{"m_mold_soil": a, "m_mold": b, "m_wet": c, "m_dry": d, "m_tare": e} for a, b, c, d, e in [
            (3437.0, 1678.0, 389.56, 356.07, 35.44), (3593.0, 1704.0, 363.5, 325.46, 35.76), (3665.0, 1706.0, 310.18, 272.12, 30.09),
            (3642.0, 1716.0, 453.92, 390.66, 45.29), (3523.0, 1696.0, 459.12, 386.58, 35.92)]],
    },
    "cbr_lab": {
        "soaked": "soaked", "cbr_rule": "astm", "pen_unit": "in", "piston_area": 19.3548, "height": 114.3,
        "swell_factor": 0.0254, "ring_no": "4156", "ring_factor": 3.38, "ring_unit": "lbf",
        "specimens": [
            {"blows": 10.0, "m_mold_soil": 6307.0, "m_mold": 2600.0, "volume": 2123.0, "m_wet": 569.32, "m_dry": 471.65, "m_tare": 36.04},
            {"blows": 25.0, "m_mold_soil": 6899.0, "m_mold": 2720.0, "volume": 2112.0, "m_wet": 526.58, "m_dry": 439.44, "m_tare": 36.74},
            {"blows": 56.0, "m_mold_soil": 6976.0, "m_mold": 2589.0, "volume": 2120.0, "m_wet": 437.14, "m_dry": 371.94, "m_tare": 36.63}],
        "penetration": _pen_rows(),
        "swell": [{"day": float(d), "swell_1": a, "swell_2": b, "swell_3": c} for d, a, b, c in
                  zip(range(1, 6), [168, 175, 180, 180, 180], [245, 260, 271, 271, 271], [52, 60, 63, 63, 63])],
        "design_pct": "95", "compaction_volume": 945.0, "gs": 2.68,
        "compaction": [{"m_mold_soil": a, "m_mold": b, "m_wet": c, "m_dry": d, "m_tare": e} for a, b, c, d, e in [
            (3467.0, 1698.0, 378.95, 342.35, 36.54), (3585.0, 1696.0, 265.3, 236.29, 35.63), (3660.0, 1687.0, 184.4, 162.83, 35.85),
            (3654.0, 1706.0, 247.7, 212.12, 29.37), (3530.0, 1662.0, 320.61, 269.16, 36.08)]],
    },
    "ucs": {
        "diameter": 5.0, "height": 10.0, "mass": 290.01, "m_wet": 290.01, "m_dry": 152.48, "m_tare": 0.0,
        "ring_no": "5022", "ring_factor": 0.35, "ring_unit": "kgf", "axial_unit": "mm",
        "readings": [{"deformation": d, "dial_undisturbed": u, "dial_remolded": r} for d, u, r in [
            (0.0, 0, 0), (0.2, 8, 5), (0.4, 19, 10), (0.6, 26, 14), (0.8, 31, 17), (1.0, 36, 20), (1.2, 39, 22), (1.4, 43, 23),
            (1.6, 47, 25), (1.8, 50, 27), (2.0, 53, 29), (2.5, 58, 32), (3.0, 62, 34), (3.5, 63, 35), (4.0, 63, 36), (4.5, 54, 37),
            (5.0, 46, 37), (5.5, 40, 30), (6.0, None, 25), (6.5, None, 21)]],
    },
    "triaxial": {
        "specimens": [{"cell_pressure": s, "height": 10.0, "diameter": 5.0, "m_wet": w, "m_dry": d}
                      for s, w, d in [(0.8, 333.78, 225.52), (1.6, 334.02, 224.65), (3.2, 335.13, 221.14)]],
        "stress_unit": "kgcm2", "ring_no": "5022", "ring_factor": 0.35, "ring_unit": "kgf", "axial_unit": "0.01mm",
        "readings": _uu_rows(),
    },
    "triaxial_cu": {
        "specimens": [{"cell_pressure": c, "back_pressure": 1.9, "b_value": b, "height": 10.0, "diameter": 5.0, "dv_consolidation": dv,
                       "m_wet_before": w0, "m_wet_after": w1, "m_dry": d}
                      for c, b, dv, w0, w1, d in [(2.4, 0.985, 8.0, 288.78, 263.71, 160.71), (2.9, 0.98, 14.0, 288.99, 261.23, 160.37),
                                                  (3.9, 0.98, 19.7, 289.77, 259.17, 161.83)]],
        "stress_unit": "kgcm2", "failure": "max_dev", "ring_unit": "kgf", "axial_unit": "0.01mm",
        "readings": _cu_rows(),
    },
    "direct_shear": {
        "specimens": [{"normal_stress": 0.5, "area": 28.27, "volume": 56.548, "m_wet": 95.11, "m_dry": 62.86, "m_tare": 0.0},
                      {"normal_stress": 1.0, "area": 28.27, "volume": 56.548, "m_wet": 97.37, "m_dry": 63.79, "m_tare": 0.0}],
        "gs": 2.62, "stress_unit": "kgcm2", "conversion": "standard", "ring_no": "7711", "ring_factor": 0.12, "ring_unit": "kgf",
        "readings": _ds_rows(),
    },
    "consolidation": {
        "ring_no": "00", "h0": 19.81, "diameter": 60.11, "m_ring": 72.82, "m_ring_soil": 164.55, "gs": 2.68, "dial_zero": 0.0,
        "m_tare": 17.61, "m_wet_after": 110.22, "m_dry_after": 73.48, "stress_unit": "kgcm2", "cc_points": "last2",
        "cv_method": "taylor",
        "increments": [{"pressure": p, "dial": d, "cv": round(cv, 6) if cv else None} for p, d, cv in [
            (0.05, 0.029, 0.0076925), (0.1, 0.137, 0.0008595), (0.2, 0.428, 0.000499), (0.4, 0.997, 0.0004157),
            (0.8, 1.807, 0.0003742), (1.6, 2.817, 0.0003182), (3.2, 3.899, 0.000255), (6.4, 5.04, 0.0002329),
            (1.6, 4.551, None), (0.4, 4.025, None), (0.1, 3.488, None), (0.0, 3.288, None)]],
        "time_readings": [{"pressure": 0.8, "t_min": t, "dial": d} for t, d in zip(
            [0, 0.1, 0.1667, 0.25, 0.5, 1, 2.25, 4, 6.25, 9, 12.25, 16, 20.25, 25, 36, 64, 100, 196, 400],
            [1.163, 1.216, 1.223, 1.23, 1.245, 1.265, 1.296, 1.343, 1.383, 1.418, 1.45, 1.475, 1.498, 1.518, 1.549, 1.597,
             1.634, 1.69, 1.737])],
    },
    "swelling": {
        "h0": 20.1, "diameter": 60.01, "m_ring": 274.6, "m_ring_soil": 383.25, "gs": 2.49, "dial_zero": 5.0,
        "m_tare": 18.85, "m_wet_after": 127.86, "m_dry_after": 102.04,
        "steps": [{"stress": s, "dial": d, "phase": p} for s, d, p in [
            (0.0, 5.0, "seating"), (5.0, 5.01, "load"), (10.0, 5.024, "before_wetting"), (10.0, 4.768, "after_wetting"),
            (20.0, 4.787, "load"), (40.0, 4.871, "load"), (80.0, 5.045, "load"), (160.0, 5.323, "load")]],
        "time_readings": [{"t_min": t, "dial": d} for t, d in zip(
            [0.1, 0.2, 0.5, 1, 2, 4, 8, 15, 30, 60, 120, 240, 480, 1440, 2880, 4320, 5760, 7200, 8640, 10080],
            [5.024, 5.023, 5.022, 5.02, 5.014, 5.008, 4.998, 4.99, 4.974, 4.95, 4.913, 4.875, 4.825, 4.783, 4.775, 4.769,
             4.768, 4.768, 4.768, 4.768])],
    },
    "la_abrasion": {
        "grading": "A", "revolutions": 500.0,
        "fractions": [{"passing": 37.5, "retained": 25.4, "mass_1": 1285.0}, {"passing": 25.4, "retained": 19.0, "mass_1": 1268.5},
                      {"passing": 19.0, "retained": 12.5, "mass_1": 1262.5}, {"passing": 12.5, "retained": 9.5, "mass_1": 1257.0}],
        "retained_1": 3594.0,
    },
    "soundness": {
        "solution": "magnesium", "aggregate": "fine", "cycles": 5.0,
        "fractions": [{"size": s, "grading": g, "mass_before": b, "mass_after": a} for s, g, b, a in [
            ("9.5-4.75 mm", 20.02, 100.45, 90.36), ("4.75-2.36 mm", 20.01, 100.52, 89.69), ("2.36-1.18 mm", 20.0, 100.35, 67.08),
            ("1.18-0.600 mm", 19.95, 100.19, 77.04), ("0.600-0.300 mm", 20.02, 100.48, 75.22)]],
    },
    "slake_durability": {
        "m_natural": 2794.61, "m_dry_before": 2756.42, "m_drum": 2517.08, "fragment_type": "II",
        "cycles": [{"cycle": 3.0, "m_after": 2681.5}],
    },
}


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

_SHEETS: List[Tuple[str, str, List[F], Callable[[Dict[str, Any]], Dict[str, Any]], List[Tuple[str, str]], str]] = [
    ("moisture", "05.04", MOISTURE_FIELDS, calc_lab.moisture, S_WC,
     "Water content by oven drying, with bulk and dry density when the ring volume is given."),
    ("specific_gravity", "05.05", SG_FIELDS, calc_lab.specific_gravity, S_SG,
     "Specific gravity of soil solids with the water pycnometer, reported at 20 °C."),
    ("grain_size", "05.06", GRAIN_FIELDS, calc_lab.grain_size, S_GS,
     "Sieve and hydrometer analysis with the grading curve, fractions and USCS symbol."),
    ("atterberg", "05.07", ATTERBERG_FIELDS, calc_lab.atterberg, S_AL,
     "Liquid limit from the flow curve, plastic limit and plasticity index."),
    ("compaction", "05.08", COMPACTION_FIELDS, calc_lab.compaction, S_PR,
     "Proctor compaction curve with maximum dry density and optimum water content."),
    ("cbr_lab", "05.09", CBR_FIELDS, calc_lab.cbr_lab, S_CBR,
     "Laboratory CBR with load–penetration curves, swell and design CBR at the target density."),
    ("ucs", "05.10", UCS_FIELDS, calc_lab.ucs, S_UCS,
     "Unconfined compressive strength, strain at failure and sensitivity."),
    ("triaxial", "05.11", UU_FIELDS, calc_lab.triaxial, S_UU,
     "Unconsolidated-undrained triaxial test with Mohr circles and undrained strength."),
    ("triaxial_cu", "05.12", CU_FIELDS, calc_lab.triaxial_cu, S_CU,
     "Consolidated-undrained triaxial test with pore pressure: total and effective strength."),
    ("direct_shear", "05.13", DS_FIELDS, calc_lab.direct_shear, S_DS,
     "Direct shear test with peak and residual strength envelopes."),
    ("consolidation", "05.14", CONSOLIDATION_FIELDS, calc_lab.consolidation, S_CO,
     "Oedometer test: e–log p curve, Cc, Cr, preconsolidation pressure and cv."),
    ("swelling", "05.15", SWELL_FIELDS, calc_lab.swelling, S_SW,
     "One-dimensional swell (method C): swell on wetting and swell pressure."),
    ("la_abrasion", "05.16", LA_FIELDS, calc_lab.la_abrasion, S_LA,
     "Los Angeles abrasion loss of coarse aggregate."),
    ("soundness", "05.17", SOUNDNESS_FIELDS, calc_lab.soundness, S_SO,
     "Weighted loss of aggregate after sulfate soundness cycles."),
    ("slake_durability", "05.18", SLAKE_FIELDS, calc_lab.slake_durability, S_SD,
     "Slake durability index of weak rock after each cycle."),
]

_LABELS = dict(LAB_TESTS)

register(
    Sheet(key="sample_register", kind="page", group="lab", code="05.01", label="Sample register", link="samples",
          help="Every sample taken in the boreholes with the tests asked for."),
    Sheet(key="lab_instruction", kind="page", group="lab", code="05.02", label="Laboratory instruction", link="samples",
          help="The tests requested for each sample."),
    Sheet(key="lab_summary", kind="page", group="lab", code="05.03", label="Summary of laboratory results", link="labsummary",
          help="All laboratory results of a project, one row per sample."),
)
for _key, _code, _fields, _fn, _std, _help in _SHEETS:
    register(Sheet(key=_key, kind="lab", group="lab", code=_code, label=_LABELS[_key], fields=_fields,
                   calc=_bounded(_key, _fn), standards=list(_std), example=EXAMPLES[_key], help=_help))
