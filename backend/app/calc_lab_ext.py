"""Laboratory calculations 05.19 to 05.23: chemistry of soil and groundwater for concrete and
steel, laboratory permeability, point load index, relative density of sands and dispersivity.

Same conventions as calc_lab.py: one pure function per test, cleaned worksheet data in,
``calcbase.result(...)`` out, with a ``lab`` dict whose keys are the result fields of the test.
Every limit and formula names its source in the method line or the notes.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .calc_lab import _choice, _mean, _need, _opt, _r, _rows, water_viscosity
from .calcbase import CalcError, axis, chart, num, result, rnd, series, table

PRELIMINARY = "Preliminary interpretation; to be checked by a geotechnical engineer."

# --------------------------------------------------------------------------- #
# 05.19 Chemistry of soil and groundwater (concrete and steel)
# --------------------------------------------------------------------------- #

SO4_PER_BASO4 = 96.06 / 233.39  # mass ratio SO4 / BaSO4 = 0.4116 (gravimetric sulfate)
CL_MG_PER_MEQ = 35450.0  # mg Cl per equivalent, Standard Methods 4500-Cl⁻ B (argentometric)

# ACI 318-19 Table 19.3.2.1 (the same classes as SNI 2847:2019, which adopts ACI 318-14).
SULFATE_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "S0": {"wcm": None, "fc": 17.0, "cement": "No restriction on the cement type (e.g. Type I, SNI 2049)",
           "cacl2": "No restriction"},
    "S1": {"wcm": 0.50, "fc": 28.0, "cement": "Type II (SNI 2049 / ASTM C150) or blended cement with moderate sulfate resistance (MS)",
           "cacl2": "No restriction"},
    "S2": {"wcm": 0.45, "fc": 31.0, "cement": "Type V (SNI 2049 / ASTM C150) or blended cement with high sulfate resistance (HS)",
           "cacl2": "Not permitted"},
    "S3": {"wcm": 0.45, "fc": 31.0, "cement": "Type V plus pozzolan or slag cement; or Type V with w/cm ≤ 0.40 and f'c ≥ 35 MPa (ACI 318-19 option 2)",
           "cacl2": "Not permitted"},
}
CHLORIDE_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "C1": {"wcm": None, "fc": 17.0, "limit": "Water-soluble chloride in the concrete ≤ 0.30 % of cement (non-prestressed)"},
    "C2": {"wcm": 0.40, "fc": 35.0, "limit": "Water-soluble chloride in the concrete ≤ 0.15 % of cement (non-prestressed); cover per SNI 2847 / ACI 318 20.5"},
}
# FHWA-NHI-16-009 (driven piles) and AASHTO LRFD Art. 10.7.5: indicators of a corrosive site for steel.
STEEL_PH = 5.5
STEEL_RESISTIVITY = 2000.0  # Ω·cm
STEEL_CHLORIDE = 500.0  # ppm (mg/kg in soil, mg/L in water)
STEEL_SULFATE = 2000.0  # ppm


def sulfate_class_soil(pct: float) -> str:
    """ACI 318-19 Table 19.3.1.1: water-soluble SO4 in soil, percent by mass."""
    if pct < 0.10:
        return "S0"
    if pct < 0.20:
        return "S1"
    if pct <= 2.00:
        return "S2"
    return "S3"


def sulfate_class_water(mg_l: float) -> str:
    """ACI 318-19 Table 19.3.1.1: dissolved SO4 in water, ppm (mg/L)."""
    if mg_l < 150:
        return "S0"
    if mg_l < 1500:
        return "S1"
    if mg_l <= 10000:
        return "S2"
    return "S3"


def organic_class(pct: float) -> str:
    """After Edil (2003) and ASTM D4427: peat above 75 % organic content."""
    if pct < 2:
        return "Inorganic soil"
    if pct < 25:
        return "Soil with organic content"
    if pct <= 75:
        return "Organic soil"
    return "Peat"


def _ph(value: Optional[float]) -> Optional[float]:
    if value is not None and not 0 <= value <= 14:
        raise CalcError("pH must be between 0 and 14")
    return value


def chemistry(data: Dict[str, Any]) -> Dict[str, Any]:
    soil_rows: List[Dict[str, Any]] = []
    for i, row in enumerate(_rows(data, "soil"), start=1):
        so4 = num(row.get("so4_pct"))
        baso4, aliquot = num(row.get("baso4")), num(row.get("aliquot"))
        if so4 is None and baso4 is not None:
            if not aliquot or aliquot <= 0:
                raise CalcError("Enter the dry soil mass of the sulfate aliquot")
            so4 = baso4 * SO4_PER_BASO4 / aliquot * 100
        entry = {"id": row.get("specimen") or str(i), "ph": _ph(num(row.get("ph"))), "so4": so4,
                 "cl": num(row.get("cl")), "res": num(row.get("resistivity"))}
        if all(entry[k] is None for k in ("ph", "so4", "cl", "res")):
            continue
        soil_rows.append(entry)
    water_rows: List[Dict[str, Any]] = []
    for i, row in enumerate(_rows(data, "water"), start=1):
        cl = num(row.get("cl"))
        titrant, sample = num(row.get("titrant")), num(row.get("sample_ml"))
        if cl is None and titrant is not None:
            normality = num(row.get("normality"))
            if not normality or normality <= 0 or not sample or sample <= 0:
                raise CalcError("Enter the normality of the silver nitrate and the sample volume")
            blank = num(row.get("blank")) or 0.0
            if titrant < blank:
                raise CalcError("The titrant volume must not be less than the blank")
            cl = (titrant - blank) * normality * CL_MG_PER_MEQ / sample
        entry = {"id": row.get("specimen") or str(i), "ph": _ph(num(row.get("ph"))), "so4": num(row.get("so4")), "cl": cl}
        if all(entry[k] is None for k in ("ph", "so4", "cl")):
            continue
        water_rows.append(entry)
    loi_rows: List[Tuple[str, float, float, float]] = []
    for i, row in enumerate(_rows(data, "loi"), start=1):
        a, b, c = num(row.get("m_dish")), num(row.get("m_dry")), num(row.get("m_ash"))
        if b is None and c is None:
            continue
        if a is None or b is None or c is None:
            raise CalcError("Enter the dish, the dish with oven-dry soil and the dish with ash")
        if b <= a:
            raise CalcError("The dish with oven-dry soil must weigh more than the dish")
        if not a <= c <= b:
            raise CalcError("The dish with ash must weigh between the dish and the dish with oven-dry soil")
        loi_rows.append((str(row.get("dish") or i), b - a, c - a, (b - c) / (b - a) * 100))
    if not soil_rows and not water_rows and not loi_rows:
        raise CalcError("Enter at least one soil or water determination")

    def worst(rows: List[Dict[str, Any]], key: str, low: bool = False) -> Optional[float]:
        vals = [r[key] for r in rows if r.get(key) is not None]
        if not vals:
            return None
        return min(vals) if low else max(vals)

    ph_soil, ph_water = worst(soil_rows, "ph", low=True), worst(water_rows, "ph", low=True)
    so4_soil, so4_water = worst(soil_rows, "so4"), worst(water_rows, "so4")
    cl_soil, cl_water = worst(soil_rows, "cl"), worst(water_rows, "cl")
    res = worst(soil_rows, "res", low=True)
    if any(v is not None and v < 0 for v in (so4_soil, cl_soil, so4_water, cl_water)):
        raise CalcError("Sulfate and chloride values must not be negative")
    if so4_soil is not None and so4_soil > 100:
        raise CalcError("Sulfate in soil is a percentage by mass (at most 100)")
    if res is not None and res <= 0:
        raise CalcError("Resistivity must be greater than zero")
    seawater = bool(data.get("seawater"))
    notes: List[str] = []

    # Sulfate exposure: the more severe of soil and water governs (ACI 318-19 19.3.1).
    classes = []
    if so4_soil is not None:
        classes.append(sulfate_class_soil(so4_soil))
    if so4_water is not None:
        classes.append(sulfate_class_water(so4_water))
    if seawater:
        classes.append("S1")
        notes.append("Seawater counts as sulfate class S1 at least (ACI 318-19 Table 19.3.1.1).")
    s_class = max(classes) if classes else None
    # Chloride: exposure class C2 when the ground or water carries more than the FHWA/AASHTO limit.
    cl_max = max([v for v in (cl_soil, cl_water) if v is not None], default=None)
    c_class = "C2" if seawater or (cl_max is not None and cl_max > STEEL_CHLORIDE) else ("C1" if cl_max is not None else None)

    values: List[Tuple[str, Any, str]] = []
    if ph_soil is not None:
        values.append(("Soil pH (lowest)", _r(ph_soil, 1), ""))
    if ph_water is not None:
        values.append(("Groundwater pH (lowest)", _r(ph_water, 1), ""))
    if so4_soil is not None:
        values.append(("Sulfate in soil SO₄ (highest)", _r(so4_soil, 3), "%"))
    if so4_water is not None:
        values.append(("Sulfate in water SO₄ (highest)", _r(so4_water, 0), "mg/L"))
    if cl_soil is not None:
        values.append(("Chloride in soil Cl (highest)", _r(cl_soil, 0), "mg/kg"))
    if cl_water is not None:
        values.append(("Chloride in water Cl (highest)", _r(cl_water, 0), "mg/L"))
    if res is not None:
        values.append(("Resistivity (lowest)", _r(res, 0), "Ω·cm"))

    req_rows: List[List[Any]] = []
    wcm: Optional[float] = None
    fc: Optional[float] = None
    if s_class is not None:
        req = SULFATE_REQUIREMENTS[s_class]
        values += [("Sulfate exposure class (ACI 318-19)", s_class, ""),
                   ("Sulfate exposure class (SNI 2847:2019)", s_class, ""),
                   ("Cement", req["cement"], ""),
                   ("Calcium chloride admixture", req["cacl2"], "")]
        wcm, fc = req["wcm"], req["fc"]
        req_rows.append(["Sulfate", s_class, req["wcm"] if req["wcm"] is not None else "–", req["fc"], req["cement"]])
        if s_class == "S3":
            notes.append("SNI 2847:2019 (ACI 318-14) gives only the first S3 option: Type V plus pozzolan or slag, w/cm ≤ 0.45, f'c ≥ 31 MPa.")
    if c_class is not None:
        creq = CHLORIDE_REQUIREMENTS[c_class]
        values.append(("Chloride exposure class (reinforced concrete)", c_class, ""))
        req_rows.append(["Chloride", c_class, creq["wcm"] if creq["wcm"] is not None else "–", creq["fc"], creq["limit"]])
        if creq["wcm"] is not None:
            wcm = creq["wcm"] if wcm is None else min(wcm, creq["wcm"])
        fc = creq["fc"] if fc is None else max(fc, creq["fc"])
        if c_class == "C2":
            notes.append("Chloride above 500 ppm or seawater: treat reinforced concrete in contact with the ground as exposure class C2 "
                         "(ACI 318-19 Table 19.3.2.1); engineer's judgement on the source of chlorides.")
    if s_class is not None or c_class is not None:
        values += [("Maximum w/cm (governing)", wcm if wcm is not None else "No limit", ""),
                   ("Minimum f'c (governing)", fc, "MPa")]

    # Steel piles: FHWA / AASHTO indicators.
    ph_min = min([v for v in (ph_soil, ph_water) if v is not None], default=None)
    so4_ppm = [v * 10000 for v in (so4_soil,) if v is not None] + [v for v in (so4_water,) if v is not None]
    so4_max_ppm = max(so4_ppm) if so4_ppm else None
    criteria: List[Tuple[str, str, Optional[float], bool]] = []
    if ph_min is not None:
        criteria.append(("pH", "< 5.5", ph_min, ph_min < STEEL_PH))
    if res is not None:
        criteria.append(("Resistivity (Ω·cm)", "< 2000", res, res < STEEL_RESISTIVITY))
    if cl_max is not None:
        criteria.append(("Chloride (ppm)", "> 500", cl_max, cl_max > STEEL_CHLORIDE))
    if so4_max_ppm is not None:
        criteria.append(("Sulfate (ppm)", "> 2000", so4_max_ppm, so4_max_ppm > STEEL_SULFATE))
    steel: Optional[str] = None
    tables = []
    if criteria:
        hits = sum(1 for c in criteria if c[3])
        steel = "aggressive" if hits else "not_aggressive"
        values += [("Steel piles", "Aggressive" if hits else "Not aggressive", ""),
                   ("Corrosion criteria met", f"{hits} / {len(criteria)}", "")]
        if hits:
            notes.append("Ground aggressive to steel: allow for corrosion of steel piles (sacrificial thickness, coating or "
                         "cathodic protection) per FHWA-NHI-16-009 and AASHTO LRFD 10.7.5.")
        if len(criteria) < 4:
            notes.append("Not every corrosion indicator was measured; test pH, resistivity, chloride and sulfate for a full check.")
    organic = _mean([r[3] for r in loi_rows]) if loi_rows else None
    if organic is not None:
        values += [("Organic content (loss on ignition)", _r(organic, 1), "%"), ("Organic class", organic_class(organic), "")]
        if ph_min is not None and STEEL_PH <= ph_min <= 8.5 and organic >= 25:
            notes.append("pH 5.5–8.5 in soil with high organic content is also a corrosion indicator (AASHTO LRFD 10.7.5).")
    if ph_min is not None and ph_min < STEEL_PH:
        notes.append("pH below 5.5: acidic ground attacks concrete and steel; consider protection of buried concrete (ACI 201.2R).")

    if soil_rows:
        tables.append(table("Soil determinations", ["Specimen", "pH", "SO₄ (%)", "SO₄ (mg/kg)", "Cl (mg/kg)", "Resistivity (Ω·cm)"],
                            [[r["id"], _r(r["ph"], 1), _r(r["so4"], 3), _r(r["so4"] * 10000, 0) if r["so4"] is not None else None,
                              _r(r["cl"], 0), _r(r["res"], 0)] for r in soil_rows],
                            key=["Specimen", "pH", "SO₄ (%)", "Cl (mg/kg)"]))
    if water_rows:
        tables.append(table("Water determinations", ["Specimen", "pH", "SO₄ (mg/L)", "Cl (mg/L)"],
                            [[r["id"], _r(r["ph"], 1), _r(r["so4"], 0), _r(r["cl"], 1)] for r in water_rows]))
    if loi_rows:
        tables.append(table("Loss on ignition", ["Dish", "Oven-dry soil (g)", "Ash (g)", "Organic content (%)"],
                            [[d, _r(m, 2), _r(a, 2), _r(o, 1)] for d, m, a, o in loi_rows], key=["Dish", "Organic content (%)"]))
    if req_rows:
        tables.append(table("Concrete requirements", ["Exposure", "Class", "Maximum w/cm", "Minimum f'c (MPa)", "Cement or limit"],
                            req_rows, key=["Exposure", "Class", "Maximum w/cm", "Minimum f'c (MPa)"]))
    if criteria:
        tables.append(table("Steel corrosion indicators (FHWA / AASHTO)", ["Indicator", "Aggressive when", "Measured", "Aggressive"],
                            [[name, limit, rnd(value, 4), "Yes" if hit else "No"] for name, limit, value, hit in criteria],
                            key=["Indicator", "Measured", "Aggressive"]))
    notes += ["The most severe soil or water value governs the exposure class (ACI 318-19 19.3.1).",
              "Water-soluble sulfate as SO₄ in percent of dry soil (ASTM C1580); 1 % = 10 000 mg/kg.", PRELIMINARY]
    summary: List[Tuple[str, Any, str]] = [("Class", s_class, ""), ("pH", _r(ph_min, 1), "")]
    if steel:
        summary.append(("Steel", "Aggressive" if steel == "aggressive" else "Not aggressive", ""))
    if organic is not None and s_class is None:
        summary.append(("Organic", _r(organic, 1), "%"))
    method = ("ACI 318-19 / SNI 2847:2019 exposure classes; FHWA-NHI-16-009 / AASHTO LRFD corrosion indicators; "
              "ASTM D2974 loss on ignition" if loi_rows else
              "ACI 318-19 / SNI 2847:2019 exposure classes; FHWA-NHI-16-009 / AASHTO LRFD corrosion indicators")
    return result(summary, values, tables, [], notes, method=method, lab={
        "ph_soil": _r(ph_soil, 1), "ph_water": _r(ph_water, 1), "so4_soil": _r(so4_soil, 3), "so4_water": _r(so4_water, 0),
        "cl_soil": _r(cl_soil, 0), "cl_water": _r(cl_water, 1), "resistivity": _r(res, 0), "organic": _r(organic, 1),
        "exposure": s_class, "steel": steel})


# --------------------------------------------------------------------------- #
# 05.20 Laboratory permeability (constant head, falling head)
# --------------------------------------------------------------------------- #

def permeability_class(k_cm_s: float) -> str:
    """Degree of permeability after Terzaghi & Peck (1967)."""
    if k_cm_s > 1e-1:
        return "High"
    if k_cm_s > 1e-3:
        return "Medium"
    if k_cm_s > 1e-5:
        return "Low"
    if k_cm_s > 1e-7:
        return "Very low"
    return "Practically impermeable"


def _sci(value: Optional[float]) -> Optional[str]:
    return None if value is None else f"{value:.2e}"


def permeability_lab(data: Dict[str, Any]) -> Dict[str, Any]:
    method = _choice(data, "method", "constant")
    diameter = _need(data, "diameter", "Specimen diameter")
    length = _need(data, "length", "Specimen length")
    area = math.pi * diameter ** 2 / 4
    eta20 = water_viscosity(20.0)
    trials: List[Dict[str, Any]] = []
    if method == "constant":
        for i, row in enumerate(_rows(data, "constant_trials"), start=1):
            h, q, t = num(row.get("head")), num(row.get("volume")), num(row.get("time"))
            if h is None and q is None and t is None:
                continue
            if not h or not q or not t or h <= 0 or q <= 0 or t <= 0:
                raise CalcError("Each constant-head trial needs a head, a volume and a time greater than zero")
            temp = num(row.get("temp"))
            temp = 20.0 if temp is None else temp
            k_t = q * length / (area * h * t)
            trials.append({"n": i, "k_t": k_t, "temp": temp, "k20": k_t * water_viscosity(temp) / eta20, "i": h / length,
                           "cols": [_r(h, 1), _r(q, 1), _r(t, 0)]})
        columns = ["Trial", "Head h (cm)", "Volume Q (cm³)", "Time t (s)", "Temperature (°C)", "Gradient i", "k at T (cm/s)", "k20 (cm/s)"]
        formula = "k = Q·L / (A·h·t)."
    elif method == "falling":
        d_pipe = _need(data, "standpipe", "Standpipe diameter")
        a = math.pi * d_pipe ** 2 / 4
        for i, row in enumerate(_rows(data, "falling_trials"), start=1):
            h1, h2, t = num(row.get("h1")), num(row.get("h2")), num(row.get("time"))
            if h1 is None and h2 is None and t is None:
                continue
            if h1 is None or h2 is None or not t or t <= 0:
                raise CalcError("Each falling-head trial needs the initial head, the final head and a time greater than zero")
            if not h1 > h2 > 0:
                raise CalcError("The final head must be lower than the initial head and above zero")
            temp = num(row.get("temp"))
            temp = 20.0 if temp is None else temp
            k_t = a * length / (area * t) * math.log(h1 / h2)
            trials.append({"n": i, "k_t": k_t, "temp": temp, "k20": k_t * water_viscosity(temp) / eta20,
                           "i": (h1 + h2) / 2 / length, "cols": [_r(h1, 1), _r(h2, 1), _r(t, 0)]})
        columns = ["Trial", "Initial head h1 (cm)", "Final head h2 (cm)", "Time t (s)", "Temperature (°C)", "Gradient i",
                   "k at T (cm/s)", "k20 (cm/s)"]
        formula = "k = a·L / (A·t) · ln(h1/h2)."
    else:
        raise CalcError("Choose the test method")
    if not trials:
        raise CalcError("Enter at least one trial")
    k20 = sum(t["k20"] for t in trials) / len(trials)
    notes = [formula, "k20 = kT · ηT/η20, with the viscosity of water at the test temperature (ASTM D2434 / D5084).",
             "Degree of permeability after Terzaghi & Peck (1967)."]
    if len(trials) > 1 and any(abs(t["k20"] - k20) > 0.25 * k20 for t in trials):
        notes.append("A trial differs from the mean by more than 25 %; ASTM D5084 asks for consistent trials before reporting.")
    if len(trials) < 3:
        notes.append("Run at least three trials (four for ASTM D5084) and report their mean.")
    if method == "constant":
        notes.append("Constant head suits coarse soils with less than 10 % fines (ASTM D2434); use falling head for fine soils.")
    values: List[Tuple[str, Any, str]] = [
        ("Coefficient of permeability k20", _sci(k20), "cm/s"),
        ("k20", _sci(k20 / 100), "m/s"),
        ("Degree of permeability", permeability_class(k20), ""),
        ("Specimen area A", _r(area, 2), "cm²"),
        ("Trials", len(trials), ""),
    ]
    e = None
    dry, gs = _opt(data, "dry_mass"), _opt(data, "gs")
    if dry is not None and dry > 0:
        rho_d = dry / (area * length)
        values.append(("Dry density ρd", _r(rho_d, 3), "g/cm³"))
        if gs is not None:
            e = gs / rho_d - 1
            if e <= 0:
                raise CalcError("The dry mass is too large for the specimen volume and Gs")
            values.append(("Void ratio e", _r(e, 3), ""))
    rows = [[t["n"], *t["cols"], _r(t["temp"], 1), _r(t["i"], 2), _sci(t["k_t"]), _sci(t["k20"])] for t in trials]
    tbl = table("Trials", columns, rows, key=["Trial", "Temperature (°C)", "k20 (cm/s)"])
    ch = chart("Coefficient of permeability per trial", axis("Trial"), axis("k20 (cm/s)", log=True),
               series("k20", [(t["n"], t["k20"]) for t in trials], "points"),
               series("Mean", [(trials[0]["n"], k20), (trials[-1]["n"], k20)], "line", dash=True))
    std = "ASTM D2434 constant head" if method == "constant" else "Falling head, rigid or flexible wall (ASTM D5856 / D5084 method C)"
    return result([("k20", _sci(k20), "cm/s")], values, [tbl], [ch], notes, method=std,
                  lab={"k": float(f"{k20:.3e}"), "e": _r(e, 3), "method": method})


# --------------------------------------------------------------------------- #
# 05.21 Point load strength index
# --------------------------------------------------------------------------- #

def is50_class(is50: float) -> str:
    """Point load strength classification, ISRM (1985) after Broch & Franklin (1972)."""
    for limit, name in ((0.03, "Extremely low"), (0.1, "Very low"), (0.3, "Low"), (1.0, "Medium"), (3.0, "High"), (10.0, "Very high")):
        if is50 < limit:
            return name
    return "Extremely high"


def ucs_class(ucs_mpa: float) -> str:
    """ISRM (1981) grades R0 to R6 by uniaxial compressive strength."""
    for limit, name in ((1, "R0 – Extremely weak"), (5, "R1 – Very weak"), (25, "R2 – Weak"), (50, "R3 – Medium strong"),
                        (100, "R4 – Strong"), (250, "R5 – Very strong")):
        if ucs_mpa < limit:
            return name
    return "R6 – Extremely strong"


def trimmed_mean(values: List[float]) -> Tuple[float, int]:
    """ASTM D5731 / ISRM (1985): drop the two highest and two lowest of 10 or more valid tests,
    the highest and lowest of fewer (5 or more), then average. Returns (mean, values dropped)."""
    ordered = sorted(values)
    n = len(ordered)
    drop = 2 if n >= 10 else 1 if n >= 5 else 0
    kept = ordered[drop:n - drop] if drop else ordered
    return sum(kept) / len(kept), 2 * drop


def point_load(data: Dict[str, Any]) -> Dict[str, Any]:
    k = _opt(data, "k_factor", 22.0) or 22.0
    if not 5 <= k <= 60:
        raise CalcError("The conversion factor K must be between 5 and 60")
    rows_out: List[List[Any]] = []
    valid: List[float] = []
    points: List[Tuple[float, float]] = []
    notes: List[str] = []
    for i, row in enumerate(_rows(data, "specimens"), start=1):
        p = num(row.get("load"))
        d = num(row.get("d_failure")) or num(row.get("d"))
        if p is None and d is None:
            continue
        if p is None or d is None or p <= 0 or d <= 0:
            raise CalcError("Each specimen needs the distance D and the failure load P")
        kind = str(row.get("type") or "diametral")
        w = num(row.get("w"))
        if kind == "diametral":
            de2 = d * d
        else:
            if not w or w <= 0:
                raise CalcError("Axial, block and lump tests need the width W")
            de2 = 4 * w * d / math.pi
            if not 0.3 <= d / w <= 1.0:
                notes.append("D/W outside 0.3–1.0 for an axial, block or lump test (ASTM D5731); treat that result with care.")
        de = math.sqrt(de2)
        i_s = p * 1000 / de2  # MPa: N / mm²
        f = (de / 50) ** 0.45
        is50 = f * i_s
        ok = str(row.get("valid") or "valid") == "valid"
        if ok:
            valid.append(is50)
            points.append((de, is50))
        rows_out.append([row.get("specimen") or i, kind.capitalize(), _r(d, 1), _r(w, 1), _r(de, 1), _r(p, 2), _r(i_s, 3),
                         _r(f, 3), _r(is50, 3), "Yes" if ok else "No"])
    if not rows_out:
        raise CalcError("Enter at least one specimen")
    if not valid:
        raise CalcError("No valid test: at least one specimen must fail through both loading points")
    mean, dropped = trimmed_mean(valid)
    ucs = k * mean
    values: List[Tuple[str, Any, str]] = [
        ("Point load index Is(50)", _r(mean, 2), "MPa"),
        ("Valid tests", len(valid), ""),
        ("Values left out of the mean", dropped, ""),
        ("Strength (ISRM 1985)", is50_class(mean), ""),
        ("Conversion factor K", _r(k, 1), ""),
        ("Estimated UCS = K · Is(50)", _r(ucs, 1), "MPa"),
        ("Rock strength grade (ISRM 1981)", ucs_class(ucs), ""),
    ]
    notes = list(dict.fromkeys(notes)) + [
        "Is = P / De²; De² = D² (diametral) or 4·W·D/π (axial, block, lump); Is(50) = (De/50)^0.45 · Is (ASTM D5731).",
        "UCS from Is(50) is an estimate: K is about 20–25 for many rocks (ASTM D5731, ISRM 1985; 24 after Broch & Franklin 1972) "
        "and should be calibrated with UCS tests on the same rock.",
    ]
    if len(valid) < 10:
        notes.append("ASTM D5731 asks for at least 10 valid tests per sample (more for anisotropic or variable rock).")
    if any(abs(de - 50) > 35 for de, _ in points):
        notes.append("Size correction is most reliable for De between about 30 and 85 mm.")
    tbl = table("Specimens", ["Specimen", "Test", "D (mm)", "W (mm)", "De (mm)", "P (kN)", "Is (MPa)", "F", "Is(50) (MPa)", "Valid"],
                rows_out, key=["Specimen", "Test", "Is(50) (MPa)", "Valid"])
    xs = [de for de, _ in points]
    ch = chart("Point load index", axis("Equivalent diameter De (mm)"), axis("Is(50) (MPa)"),
               series("Is(50)", points, "points"),
               series("Mean", [(min(xs), mean), (max(xs), mean)] if len(xs) > 1 and max(xs) > min(xs) else [], "line", dash=True))
    return result([("Is(50)", _r(mean, 2), "MPa"), ("UCS", _r(ucs, 1), "MPa")], values, [tbl], [ch], notes,
                  method="ASTM D5731 point load strength index with size correction",
                  lab={"is50": _r(mean, 2), "ucs": _r(ucs, 1), "k_factor": _r(k, 1), "n": len(valid)})


# --------------------------------------------------------------------------- #
# 05.22 Relative density of cohesionless soils
# --------------------------------------------------------------------------- #

def density_class(dr: float) -> str:
    """After Lambe & Whitman (1969), as in Das, Principles of Geotechnical Engineering."""
    for limit, name in ((15, "Very loose"), (35, "Loose"), (65, "Medium dense"), (85, "Dense")):
        if dr < limit:
            return name
    return "Very dense"


def relative_density_value(rho: float, rho_min: float, rho_max: float) -> float:
    """ASTM D4254 eq.: Dr = ρd,max (ρd − ρd,min) / (ρd (ρd,max − ρd,min)) × 100."""
    return rho_max * (rho - rho_min) / (rho * (rho_max - rho_min)) * 100


def relative_density(data: Dict[str, Any]) -> Dict[str, Any]:
    notes: List[str] = []
    vol = _opt(data, "mold_volume")
    mold = _opt(data, "mold_mass", 0.0) or 0.0
    mins: List[float] = []
    for row in _rows(data, "min_trials"):
        m = num(row.get("m_total"))
        if m is None:
            continue
        if not vol or vol <= 0:
            raise CalcError("Mold volume is required")
        if m <= mold:
            raise CalcError("The mold with soil must weigh more than the mold")
        mins.append((m - mold) / vol)
    maxs: List[float] = []
    vol_max = _opt(data, "max_volume") or vol
    area = _opt(data, "mold_area")
    for row in _rows(data, "max_trials"):
        m = num(row.get("m_total"))
        if m is None:
            continue
        if not vol_max or vol_max <= 0:
            raise CalcError("Mold volume is required")
        settle = num(row.get("settlement")) or 0.0
        if settle and not area:
            raise CalcError("Enter the mold area to use the settlement of the surcharge plate")
        v = vol_max - (area or 0) * settle / 10
        if v <= 0 or m <= mold:
            raise CalcError("Check the mold mass, volume and settlement of the maximum density trials")
        maxs.append((m - mold) / v)
    for trials in (mins, maxs):
        if len(trials) > 1 and (max(trials) - min(trials)) > 0.02 * (sum(trials) / len(trials)):
            notes.append("The density trials differ by more than 2 %; check the procedure.")
    rho_min = _opt(data, "rho_min_manual") or (_mean(mins) if mins else None)
    rho_max = _opt(data, "rho_max_manual") or (_mean(maxs) if maxs else None)
    if rho_min is None or rho_max is None:
        raise CalcError("Enter the minimum and maximum density trials, or the two densities directly")
    if rho_max <= rho_min:
        raise CalcError("The maximum index density must be greater than the minimum")
    gs = _opt(data, "gs")
    points: List[Tuple[str, float]] = []
    for i, row in enumerate(_rows(data, "field"), start=1):
        rho = num(row.get("rho_d"))
        gamma = num(row.get("gamma_d"))
        if rho is None and gamma is not None:
            rho = gamma / 9.81
        if rho is None:
            continue
        if rho <= 0:
            raise CalcError("The dry density must be greater than zero")
        points.append((str(row.get("point") or i), rho))
    values: List[Tuple[str, Any, str]] = [("Minimum index density ρd,min", _r(rho_min, 3), "g/cm³"),
                                          ("Maximum index density ρd,max", _r(rho_max, 3), "g/cm³")]
    e_min = e_max = None
    if gs is not None:
        e_max, e_min = gs / rho_min - 1, gs / rho_max - 1
        values += [("Maximum void ratio emax", _r(e_max, 3), ""), ("Minimum void ratio emin", _r(e_min, 3), "")]
    rows: List[List[Any]] = []
    drs: List[float] = []
    for name, rho in points:
        dr = relative_density_value(rho, rho_min, rho_max)
        drs.append(dr)
        e = gs / rho - 1 if gs is not None else None
        rows.append([name, _r(rho, 3), _r(e, 3), _r(dr, 1), density_class(min(max(dr, 0), 100))])
        if dr < 0 or dr > 100:
            notes.append("A dry density lies outside the index density range; check the field density or the index tests.")
    tables = []
    dr_mean = None
    if drs:
        dr_mean = sum(drs) / len(drs)
        phi = 28 + 0.15 * min(max(dr_mean, 0), 100)
        values += [("Relative density Dr", _r(dr_mean, 1), "%"), ("Density", density_class(min(max(dr_mean, 0), 100)), ""),
                   ("Friction angle φ' estimate (Meyerhof 1956)", _r(phi, 1), "°")]
        tables.append(table("Dry densities", ["Point", "ρd (g/cm³)", "e", "Dr (%)", "Density"], rows,
                            key=["Point", "ρd (g/cm³)", "Dr (%)", "Density"]))
    else:
        notes.append("Enter a field or specimen dry density to get the relative density.")
    trial_rows = [["Minimum", i + 1, _r(v, 3)] for i, v in enumerate(mins)] + [["Maximum", i + 1, _r(v, 3)] for i, v in enumerate(maxs)]
    if trial_rows:
        tables.insert(0, table("Index density trials", ["Index density", "Trial", "ρd (g/cm³)"], trial_rows))
    notes = list(dict.fromkeys(notes)) + [
        "Dr = ρd,max (ρd − ρd,min) / (ρd (ρd,max − ρd,min)) = (emax − e) / (emax − emin) (ASTM D4254).",
        "Index densities apply to free-draining cohesionless soils with at most 15 % fines (ASTM D4253).",
        "Density classes after Lambe & Whitman (1969); φ' = 28° + 0.15 Dr after Meyerhof (1956), an estimate.",
        PRELIMINARY,
    ]
    summary = [("Dr", _r(dr_mean, 1), "%"), ("ρd,max", _r(rho_max, 3), "g/cm³")]
    return result(summary, values, tables, [], notes, method="ASTM D4253 / D4254 minimum and maximum index density",
                  lab={"dr": _r(dr_mean, 1), "rho_min": _r(rho_min, 3), "rho_max": _r(rho_max, 3), "e_min": _r(e_min, 3),
                       "e_max": _r(e_max, 3)})


# --------------------------------------------------------------------------- #
# 05.23 Dispersivity: crumb, pinhole and double hydrometer
# --------------------------------------------------------------------------- #

VERDICT_ORDER = {"non_dispersive": 0, "intermediate": 1, "dispersive": 2}
VERDICT_LABEL = {"non_dispersive": "Non-dispersive", "intermediate": "Intermediate", "dispersive": "Dispersive"}
CRUMB_VERDICT = {1: "non_dispersive", 2: "intermediate", 3: "dispersive", 4: "dispersive"}
CRUMB_LABEL = {1: "Grade 1 – non-dispersive", 2: "Grade 2 – intermediate", 3: "Grade 3 – dispersive", 4: "Grade 4 – highly dispersive"}
CLOUD_LABEL = {"very_dark": "Very dark", "dark": "Dark", "moderately_dark": "Moderately dark", "slightly_dark": "Slightly dark",
               "barely_visible": "Barely visible", "clear": "Perfectly clear"}
PINHOLE_VERDICT = {"D1": "dispersive", "D2": "dispersive", "ND4": "intermediate", "ND3": "intermediate",
                   "ND2": "non_dispersive", "ND1": "non_dispersive"}


def dispersion_verdict(pct: float) -> str:
    """Double hydrometer percent dispersion after Sherard, Dunnigan & Decker (1976)."""
    if pct > 50:
        return "dispersive"
    if pct >= 30:
        return "intermediate"
    return "non_dispersive"


def dispersivity(data: Dict[str, Any]) -> Dict[str, Any]:
    indicators: List[Tuple[str, str, str]] = []  # test, result, verdict
    tables = []
    charts = []
    notes: List[str] = []
    crumb_rows: List[List[Any]] = []
    grades: List[int] = []
    for i, row in enumerate(_rows(data, "crumbs"), start=1):
        readings = [num(row.get(k)) for k in ("g_2min", "g_1h", "g_6h")]
        given = [int(v) for v in readings if v is not None]
        if not given:
            continue
        if any(not 1 <= g <= 4 for g in given):
            raise CalcError("Crumb grades are 1 to 4")
        grade = max(given)
        grades.append(grade)
        crumb_rows.append([row.get("specimen") or i, *[int(v) if v is not None else None for v in readings], grade])
    crumb_grade = max(grades) if grades else None
    if crumb_grade is not None:
        indicators.append(("Crumb test (ASTM D6572)", CRUMB_LABEL[crumb_grade], CRUMB_VERDICT[crumb_grade]))
        tables.append(table("Crumb test", ["Specimen", "2 min", "1 h", "6 h", "Grade"], crumb_rows))
        notes.append("Crumb test: the highest grade observed governs (conservative).")
    flow_pts: List[Tuple[float, float]] = []
    pin_rows: List[List[Any]] = []
    for row in _rows(data, "pinhole"):
        head, vol, secs = num(row.get("head")), num(row.get("volume")), num(row.get("time"))
        if head is None:
            continue
        rate = vol / secs if vol is not None and secs else None
        if rate is not None:
            flow_pts.append((head, rate))
        pin_rows.append([_r(head, 0), _r(vol, 1), _r(secs, 0), _r(rate, 2), CLOUD_LABEL.get(str(row.get("cloudiness") or ""), "")])
    if pin_rows:
        tables.append(table("Pinhole readings", ["Head (mm)", "Volume (mL)", "Time (s)", "Flow rate (mL/s)", "Effluent"], pin_rows,
                            key=["Head (mm)", "Flow rate (mL/s)", "Effluent"]))
    if len(flow_pts) > 1:
        charts.append(chart("Pinhole flow rate", axis("Head (mm)"), axis("Flow rate (mL/s)"), series("Flow rate", flow_pts, "both")))
    pin_class = str(data.get("pinhole_class") or "")
    if pin_class:
        if pin_class not in PINHOLE_VERDICT:
            raise CalcError("Choose a pinhole class D1, D2, ND4, ND3, ND2 or ND1")
        indicators.append(("Pinhole test (ASTM D4647)", pin_class, PINHOLE_VERDICT[pin_class]))
    elif pin_rows:
        notes.append("Choose the pinhole class from the ASTM D4647 criteria (flow rate, effluent and final hole size).")
    without, with_disp = _opt(data, "finer_without"), _opt(data, "finer_with")
    pct = None
    if without is not None and with_disp is not None:
        if with_disp <= 0:
            raise CalcError("Percent finer with dispersant must be greater than zero")
        pct = without / with_disp * 100
        indicators.append(("Double hydrometer (ASTM D4221)", f"{_r(pct, 0):g} %", dispersion_verdict(pct)))
    if not indicators:
        raise CalcError("Enter crumb grades, the pinhole class or the double hydrometer results")
    verdict = max((v for _, _, v in indicators), key=lambda v: VERDICT_ORDER[v])
    tables.insert(0, table("Indicators", ["Test", "Result", "Classification"],
                           [[a, b, VERDICT_LABEL[v]] for a, b, v in indicators]))
    values: List[Tuple[str, Any, str]] = [("Dispersivity", VERDICT_LABEL[verdict], "")]
    if crumb_grade is not None:
        values.append(("Crumb grade", crumb_grade, ""))
    if pin_class:
        values.append(("Pinhole class", pin_class, ""))
        hole = _opt(data, "hole_mm")
        if hole is not None:
            values.append(("Final pinhole diameter", _r(hole, 1), "mm"))
    if pct is not None:
        values.append(("Percent dispersion", _r(pct, 0), "%"))
    notes += ["The most dispersive indicator governs: one dispersive result is enough to treat the soil as dispersive "
              "(Sherard et al. 1976; USBR practice).",
              "Pinhole classes: D1, D2 dispersive; ND4, ND3 slightly to moderately dispersive; ND2, ND1 non-dispersive (ASTM D4647).",
              "Percent dispersion: above 50 % dispersive, 30–50 % intermediate, below 30 % non-dispersive (Sherard et al. 1976)."]
    if verdict != "non_dispersive":
        notes.append("Dispersive or intermediate soil erodes in still water: protect embankments, dam cores and culverts "
                     "(filters, lime or gypsum treatment) and have the design checked by a geotechnical engineer.")
    return result([("Dispersivity", VERDICT_LABEL[verdict], "")], values, tables, charts, notes,
                  method="ASTM D6572 crumb, ASTM D4647 pinhole and ASTM D4221 double hydrometer",
                  lab={"crumb_grade": crumb_grade, "pinhole_class": pin_class or None, "dispersion_pct": _r(pct, 0),
                       "verdict": verdict})


# --------------------------------------------------------------------------- #
# Hooks for the engineering analyses ("use field and lab data")
# --------------------------------------------------------------------------- #

PILE_SULFATE_NOTES = {
    "S1": "Laboratory chemistry: sulfate exposure class S1 for concrete piles: Type II cement, w/cm ≤ 0.50, f'c ≥ 28 MPa "
          "(ACI 318-19 / SNI 2847:2019).",
    "S2": "Laboratory chemistry: sulfate exposure class S2 for concrete piles: Type V cement, w/cm ≤ 0.45, f'c ≥ 31 MPa "
          "(ACI 318-19 / SNI 2847:2019).",
    "S3": "Laboratory chemistry: sulfate exposure class S3 for concrete piles: Type V cement with pozzolan or slag, w/cm ≤ 0.45, "
          "f'c ≥ 31 MPa (ACI 318-19 / SNI 2847:2019).",
}
PILE_STEEL_NOTE = ("Laboratory chemistry: the ground is aggressive to steel; allow for corrosion of steel piles "
                   "(FHWA-NHI-16-009, AASHTO LRFD 10.7.5).")


def pile_notes(tests: List[Dict[str, Any]]) -> List[str]:
    """Notes for a pile analysis from the finished chemistry tests of its borehole (worst class governs)."""
    chem = [t.get("results") or {} for t in tests if t.get("test_type") == "chemistry"]
    classes = sorted({str(r.get("exposure")) for r in chem if r.get("exposure") in PILE_SULFATE_NOTES})
    out = [PILE_SULFATE_NOTES[classes[-1]]] if classes else []
    if any(r.get("steel") == "aggressive" for r in chem):
        out.append(PILE_STEEL_NOTE)
    return out
