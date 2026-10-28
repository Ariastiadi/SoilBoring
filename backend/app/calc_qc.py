"""Calculations of the compaction-control and site-safety worksheets: sand cone field density
(03.09), dynamic cone penetrometer (03.10) and the pre-drilling checklist / permit to work (01.05).

Each function takes the cleaned worksheet data (see sheets_qc.py) and returns a
:func:`calcbase.result`. Sources:

- Sand cone: SNI 2828:2011 and ASTM D1556/D1556M (volume of the hole from the mass of calibrated
  sand, wet and dry density); relative compaction against the Proctor test (SNI 1742:2008 /
  ASTM D698, SNI 1743:2008 / ASTM D1557); speedy moisture after ASTM D4944.
- DCP: ASTM D6951/D6951M (DCP index, hammer factor 2 for the 4.6 kg hammer, the CBR
  correlations of its appendix after Webster et al. 1992, USACE) and the Indonesian guideline
  "Cara uji CBR dengan Dynamic Cone Penetrometer (DCP)" put in force by SE Menteri PU
  04/SE/M/2010 (60° cone, log CBR = 2.8135 − 1.313 log DCP).
- Checklist: 29 CFR 1926 Subpart P (OSHA excavations, Appendix A soil classification and
  Appendix B maximum slopes), ISO 45001:2018 hazard identification and Permenaker 5/2018 for the
  working environment; the job safety analysis follows OSHA 3071 (Job Hazard Analysis).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .calcbase import CalcError, axis, chart, interpolate, num, result, rnd, series, table

Row = Dict[str, Any]
Value = Tuple[str, Any, str]

G = 9.80665  # m/s², unit weight in kN/m³ = density in g/cm³ × g


def _rows(data: Dict[str, Any], key: str) -> List[Row]:
    return [r for r in data.get(key) or [] if isinstance(r, dict)]


def _txt(value: Any) -> str:
    return str(value or "").strip()


def _mean(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


# --------------------------------------------------------------------------- #
# 03.09 Sand cone field density and relative compaction
# --------------------------------------------------------------------------- #

# ASTM D1556 Table 1: minimum test hole volume and moisture sample by maximum particle size.
HOLE_MINIMUM = {"4.75": (710.0, 100.0), "12.5": (1415.0, 250.0), "25": (2125.0, 500.0), "50": (2830.0, 1000.0)}


def speedy_to_dry_basis(reading: float) -> float:
    """Speedy (calcium carbide) gauges read the water content on the wet mass; w = R / (100 − R) × 100."""
    if reading >= 100:
        raise CalcError("A speedy reading must be below 100 %")
    return reading / (100.0 - reading) * 100.0


def _sand_density(data: Dict[str, Any]) -> Tuple[float, str, List[List[Any]]]:
    direct = num(data.get("sand_density"))
    rows: List[List[Any]] = []
    found: List[float] = []
    for i, r in enumerate(_rows(data, "calibration"), start=1):
        m, v = num(r.get("mass")), num(r.get("volume"))
        if m is None or v is None:
            continue
        if v <= 0:
            raise CalcError("The calibration container volume must be above zero")
        found.append(m / v)
        rows.append([i, m, v, m / v])
    if direct is not None:
        return direct, "entered", rows
    if not found:
        raise CalcError("Enter the bulk density of the sand, or the calibration container mass and volume")
    return sum(found) / len(found), "calibration", rows


def _cone_mass(data: Dict[str, Any]) -> Tuple[float, List[List[Any]]]:
    direct = num(data.get("cone_mass"))
    rows: List[List[Any]] = []
    found: List[float] = []
    for i, r in enumerate(_rows(data, "cone_trials"), start=1):
        a, b = num(r.get("before")), num(r.get("after"))
        if a is None or b is None:
            continue
        found.append(a - b)
        rows.append([i, a, b, a - b])
    if direct is not None:
        return direct, rows
    if not found:
        raise CalcError("Enter the mass of sand that fills the cone and base plate")
    return sum(found) / len(found), rows


def _moisture(r: Row) -> Tuple[Optional[float], str]:
    tin, wet, dry = num(r.get("w_tin")), num(r.get("w_wet")), num(r.get("w_dry"))
    if tin is not None and wet is not None and dry is not None:
        if dry <= tin or wet < dry:
            return None, "Oven masses not valid"
        return (wet - dry) / (dry - tin) * 100.0, "Oven"
    w = num(r.get("w"))
    if w is not None:
        return w, "Entered"
    speedy = num(r.get("speedy"))
    if speedy is not None:
        return speedy_to_dry_basis(speedy), "Speedy"
    return None, ""


def sand_cone(data: Dict[str, Any]) -> Dict[str, Any]:
    """03.09 sand cone: hole volume from calibrated sand, wet and dry density, relative compaction."""
    rho_sand, sand_from, calib_rows = _sand_density(data)
    if not 1.0 <= rho_sand <= 2.0:
        raise CalcError("The bulk density of the sand should be between 1.0 and 2.0 g/cm³; check the calibration")
    cone, cone_rows = _cone_mass(data)
    mdd = num(data.get("mdd"))
    omc = num(data.get("omc"))
    spec = num(data.get("spec_min"))
    spec = 95.0 if spec is None else spec
    tolerance = num(data.get("moisture_tolerance"))
    gs = num(data.get("gs"))
    minimum = HOLE_MINIMUM.get(_txt(data.get("max_particle")))
    notes = ["Sand in the hole = (jar + sand before − jar + sand after) − sand in the cone; hole volume V = sand in the hole / ρ sand.",
             "Wet density ρ = wet soil from the hole / V; dry density ρd = ρ / (1 + w/100); relative compaction RC = ρd / ρd,max × 100."]
    out_rows: List[List[Any]] = []
    plot: List[Tuple[float, float]] = []
    rcs: List[float] = []
    passed = failed = 0
    small_holes: List[str] = []
    bad_rows = 0
    for r in _rows(data, "points"):
        name = _txt(r.get("point"))
        before, after, wet_soil = num(r.get("mass_before")), num(r.get("mass_after")), num(r.get("wet_soil"))
        if not name or before is None or after is None or wet_soil is None:
            continue
        used = before - after
        in_hole = used - cone
        if in_hole <= 0:
            bad_rows += 1
            out_rows.append([name, _txt(r.get("location")), rnd(used, 5), rnd(in_hole, 5), None, None, None, "", None, None,
                             None, None, "", "No sand left in the hole: check the masses"])
            continue
        volume = in_hole / rho_sand
        rho_wet = wet_soil / volume
        w, w_from = _moisture(r)
        rho_dry = rho_wet / (1 + w / 100.0) if w is not None else None
        rc = rho_dry / mdd * 100.0 if rho_dry is not None and mdd else None
        dw = w - omc if w is not None and omc is not None else None
        verdict = ""
        if rc is not None:
            ok = rc >= spec - 1e-9
            if ok and tolerance is not None and dw is not None and abs(dw) > tolerance + 1e-9:
                ok = False
            verdict = "Pass" if ok else "Fail"
            passed += ok
            failed += not ok
            rcs.append(rc)
        remark = "Oven masses not valid: wet ≥ dry > container" if w_from == "Oven masses not valid" else ""
        if w_from == "Oven masses not valid":
            w_from = ""
        if minimum and volume < minimum[0]:
            small_holes.append(name)
            remark = "Hole below the minimum volume"
        if rho_dry is not None and w is not None:
            plot.append((w, rho_dry))
        out_rows.append([name, _txt(r.get("location")), rnd(used, 5), rnd(in_hole, 5), rnd(volume, 5), rnd(rho_wet, 4),
                         rnd(w, 3), w_from, rnd(rho_dry, 4), rnd(rho_dry * G, 4) if rho_dry is not None else None,
                         rnd(rc, 4), rnd(dw, 3), verdict, remark])
    if not out_rows:
        raise CalcError("Enter at least one test point with the jar masses and the wet soil mass")
    if bad_rows == len(out_rows):
        raise CalcError("The sand used is not more than the sand in the cone; check the jar masses and the cone correction")
    if bad_rows:
        notes.append("At some points the sand used is not more than the sand in the cone; those points are not calculated.")
    if not mdd:
        notes.append("Enter the maximum dry density of the Proctor test to get the relative compaction.")
    else:
        notes.append("A point passes when its relative compaction reaches the specification.")
        if tolerance is not None:
            notes.append("A point also fails when its water content is further from the OMC than the allowed deviation.")
    if any(row[7] == "Speedy" for row in out_rows):
        notes.append("Speedy readings are converted from the wet-mass basis with w = R / (100 − R) × 100; check them against oven water contents (ASTM D4944).")
    if small_holes:
        notes.append("Some holes are smaller than the ASTM D1556 minimum volume for the largest particle size; see the remark column.")
    if sand_from == "calibration" and len(calib_rows) < 3:
        notes.append("ASTM D1556 asks for at least three determinations of the sand bulk density; their average is used.")
    if any(row[5] is not None and not 1.2 <= row[5] <= 2.6 for row in out_rows):
        notes.append("A wet density outside 1.2–2.6 g/cm³ is unusual for compacted soil; check the masses.")
    tables = [table("Field density", ["Point", "Location / layer", "Sand used (g)", "Sand in the hole (g)", "Hole volume (cm³)",
                                      "Wet density (g/cm³)", "Water content (%)", "Moisture from", "Dry density (g/cm³)",
                                      "Dry unit weight (kN/m³)", "Relative compaction (%)", "w − OMC (%)", "Result", "Remark"],
                    out_rows, key=["Point", "Dry density (g/cm³)", "Water content (%)", "Relative compaction (%)", "Result"],
                    note="Remark")]
    if calib_rows:
        tables.append(table("Sand calibration", ["Trial", "Sand in the container (g)", "Container volume (cm³)", "Bulk density (g/cm³)"],
                            calib_rows))
    if cone_rows:
        tables.append(table("Cone correction", ["Trial", "Jar + sand before (g)", "Jar + sand after (g)", "Sand in the cone (g)"], cone_rows))
    charts = []
    if plot:
        ws = [p[0] for p in plot]
        lo, hi = max(0.0, min(ws) - 3), max(ws) + 3
        lines = []
        if mdd:
            lines.append(series("γd,max", [(lo, mdd), (hi, mdd)], style="line", dash=True))
            lines.append(series("Specified minimum", [(lo, mdd * spec / 100), (hi, mdd * spec / 100)], style="line", dash=True))
        if gs:
            steps = 12
            lines.append(series("Zero air voids", [(lo + (hi - lo) * i / steps, gs / (1 + (lo + (hi - lo) * i / steps) * gs / 100))
                                                   for i in range(steps + 1)], style="line"))
        charts.append(chart("Dry density against water content", axis("Water content (%)"), axis("Dry density (g/cm³)"),
                            series("Test points", plot, style="points"), *lines))
    mean_rc = _mean(rcs)
    values: List[Value] = [("Bulk density of the sand", rnd(rho_sand, 4), "g/cm³"), ("Sand in the cone", rnd(cone, 5), "g"),
                           ("Test points", len(out_rows), "")]
    if mdd:
        values += [("Maximum dry density", mdd, "g/cm³"), ("Specification", spec, "%"),
                   ("Points passed", passed, ""), ("Points failed", failed, ""),
                   ("Mean relative compaction", rnd(mean_rc, 4), "%"), ("Lowest relative compaction", rnd(min(rcs), 4) if rcs else None, "%")]
    if omc is not None:
        values.append(("Optimum water content", omc, "%"))
    ref = _txt(data.get("proctor_ref"))
    if ref:
        values.append(("Proctor test", ref, ""))
    return result(
        summary=[("Mean relative compaction", rnd(mean_rc, 4), "%"), ("Passed", f"{passed}/{passed + failed}" if rcs else None, ""),
                 ("Lowest RC", rnd(min(rcs), 4) if rcs else None, "%")],
        values=values, tables=tables, charts=charts, notes=notes,
        method="Sand cone field density (SNI 2828:2011, ASTM D1556) and relative compaction against the Proctor test")


# --------------------------------------------------------------------------- #
# 03.10 Dynamic cone penetrometer (DCP)
# --------------------------------------------------------------------------- #

def cbr_from_dpi(dpi: float, method: str) -> float:
    """CBR (%) from the DCP index (mm/blow, 8 kg hammer)."""
    if dpi <= 0:
        raise CalcError("The DCP index must be above zero")
    if method == "cl":  # ASTM D6951 appendix: CL soils with CBR < 10
        return 1.0 / (0.017019 * dpi) ** 2
    if method == "ch":  # ASTM D6951 appendix: CH soils
        return 1.0 / (0.002871 * dpi)
    if method == "binamarga":  # Indonesian DCP guideline, 60° cone
        return 10 ** (2.8135 - 1.313 * math.log10(dpi))
    return 10 ** (2.465 - 1.12 * math.log10(dpi))  # ASTM D6951: all soils except CL < 10 and CH


CBR_METHOD_TEXT = {
    "astm": "log CBR = 2.465 − 1.12 log DPI (ASTM D6951, all soils except CL with CBR < 10 and CH)",
    "cl": "CBR = 1 / (0.017019 × DPI)² (ASTM D6951, CL soils with CBR < 10)",
    "ch": "CBR = 1 / (0.002871 × DPI) (ASTM D6951, CH soils)",
    "binamarga": "log CBR = 2.8135 − 1.313 log DCP (Indonesian DCP guideline, 60° cone)",
}


def dcp(data: Dict[str, Any]) -> Dict[str, Any]:
    """03.10 DCP: penetration per blow per interval and per layer, CBR by correlation."""
    factor = 2.0 if _txt(data.get("hammer")) == "4.6" else 1.0
    method = _txt(data.get("correlation")) or "astm"
    cumulative = _txt(data.get("blows_mode")) == "cumulative"
    start = num(data.get("start_depth")) or 0.0  # mm below the reference surface where the test starts
    raw = [r for r in _rows(data, "readings") if num(r.get("reading")) is not None and num(r.get("blows")) is not None]
    if len(raw) < 2:
        raise CalcError("Enter at least two readings (the zero reading and one set of blows)")
    blows: List[float] = []
    readings: List[float] = []
    total = 0.0
    for i, r in enumerate(raw):
        b, p = float(num(r.get("blows")) or 0.0), float(num(r.get("reading")) or 0.0)
        if b < 0:
            raise CalcError("Blows cannot be negative")
        total = b if cumulative else (total + b if i else b)
        blows.append(total)
        readings.append(p)
    zero_entered = num(data.get("zero_reading"))
    if blows[0] == 0:
        zero = readings[0]
    else:  # no zero row: the scale reading before the first blow is entered separately (or 0)
        zero = zero_entered if zero_entered is not None else 0.0
        blows.insert(0, 0.0)
        readings.insert(0, zero)
    depth = [start + (p - zero) for p in readings]
    for i in range(1, len(blows)):
        if blows[i] < blows[i - 1]:
            raise CalcError("The cumulative blows must not decrease; check the blow counts")
        if depth[i] < depth[i - 1]:
            raise CalcError("The penetration readings must not decrease; check the readings")
    notes = ["DCP index DPI = penetration between two readings / blows × hammer factor (1 for the 8 kg hammer, 2 for the 4.6 kg hammer).",
             CBR_METHOD_TEXT.get(method, CBR_METHOD_TEXT["astm"])]
    if factor == 2:
        notes.append("4.6 kg hammer: the DCP index is doubled before the correlation, as ASTM D6951 prescribes.")
    interval_rows: List[List[Any]] = []
    profile: List[Tuple[float, float]] = []
    low_dpi = False
    for i in range(1, len(blows)):
        db, dp = blows[i] - blows[i - 1], depth[i] - depth[i - 1]
        if db <= 0:
            continue
        dpi = dp / db * factor
        cbr = cbr_from_dpi(dpi, method) if dpi > 0 else None
        if dpi < 1:
            low_dpi = True
        interval_rows.append([rnd(depth[i - 1], 5), rnd(depth[i], 5), db, rnd(dp, 4), rnd(dpi, 4), rnd(cbr, 4)])
        if cbr is not None:
            profile += [(cbr, depth[i - 1]), (cbr, depth[i])]
    if not interval_rows:
        raise CalcError("No set of blows with penetration was found")
    layers_in = [r for r in _rows(data, "layers") if num(r.get("top")) is not None and num(r.get("bottom")) is not None]
    auto = not layers_in
    if auto:
        layers_in = [{"top": depth[0], "bottom": depth[-1], "description": "Whole test"}]
    layer_rows: List[List[Any]] = []
    layer_lines: List[Tuple[float, float]] = []
    for r in layers_in:
        top, bottom = float(num(r.get("top")) or 0.0), float(num(r.get("bottom")) or 0.0)
        if bottom <= top:
            raise CalcError("A layer's bottom must be below its top")
        b_top, b_bot = interpolate(top, depth, blows), interpolate(bottom, depth, blows)
        if b_top is None or b_bot is None:
            layer_rows.append([_txt(r.get("description")), top, bottom, None, None, None, "Outside the tested depth"])
            continue
        if b_bot - b_top <= 0:
            layer_rows.append([_txt(r.get("description")), top, bottom, rnd(b_bot - b_top, 4), None, None, "No blows in this layer"])
            continue
        dpi = (bottom - top) / (b_bot - b_top) * factor
        cbr = cbr_from_dpi(dpi, method)
        layer_rows.append([_txt(r.get("description")), rnd(top, 5), rnd(bottom, 5), rnd(b_bot - b_top, 4), rnd(dpi, 4), rnd(cbr, 4), ""])
        layer_lines += [(cbr, top), (cbr, bottom)]
    if low_dpi:
        notes.append("A DCP index below 1 mm/blow means near refusal (gravel, rock or a very stiff layer); the CBR there is outside the correlation.")
    if any(row[5] is not None and row[5] > 100 for row in interval_rows):
        notes.append("CBR above 100 % is outside the range of the correlations; report it as > 100 %.")
    if auto:
        notes.append("No layers were entered: one layer over the whole test is used. Enter the layer boundaries seen on the cumulative-blows chart to get a CBR per layer.")
    notes.append("The CBR from a DCP is an estimate; confirm design values with field or laboratory CBR tests.")
    valid_layers = [row for row in layer_rows if row[5] is not None]
    weakest = min(valid_layers, key=lambda row: row[5]) if valid_layers else None
    values: List[Value] = [("Hammer factor", factor, ""), ("Final depth", rnd(depth[-1], 5), "mm"), ("Total blows", blows[-1], "")]
    charts = [chart("Cumulative blows against depth", axis("Cumulative blows"), axis("Depth (mm)", reverse=True),
                    series("Blows", list(zip(blows, depth)))),
              chart("CBR against depth", axis("CBR (%)", log=True), axis("Depth (mm)", reverse=True),
                    series("Per interval", profile, style="line"), series("Per layer", layer_lines, style="line", dash=True))]
    return result(
        summary=[("Weakest layer CBR", weakest[5] if weakest else None, "%"), ("DCP index", weakest[4] if weakest else None, "mm/blow"),
                 ("Final depth", rnd(depth[-1], 5), "mm")],
        values=values,
        tables=[table("Layers", ["Layer", "From (mm)", "To (mm)", "Blows", "DCP index (mm/blow)", "CBR (%)", "Remark"], layer_rows,
                      key=["Layer", "From (mm)", "To (mm)", "CBR (%)"], note="Remark"),
                table("Readings", ["From (mm)", "To (mm)", "Blows", "Penetration (mm)", "DCP index (mm/blow)", "CBR (%)"], interval_rows)],
        charts=charts, notes=notes,
        method="Dynamic cone penetrometer (ASTM D6951; Indonesian DCP guideline, SE Menteri PU 04/SE/M/2010)")


# --------------------------------------------------------------------------- #
# 01.05 Pre-drilling checklist / permit to work
# --------------------------------------------------------------------------- #

YNA = [("yes", "Yes"), ("no", "No"), ("na", "N.A.")]

# key, label, group, critical (a "No" on a critical item stops the work)
CHECK_ITEMS: List[Tuple[str, str, str, bool]] = [
    ("utility_drawings", "Utility drawings and permits checked with the owner", "Underground and overhead utilities", True),
    ("utility_scan", "Point scanned with a cable / pipe locator (CAT & Genny)", "Underground and overhead utilities", True),
    ("hand_dig", "Inspection pit hand-dug to 1.5 m before drilling", "Underground and overhead utilities", False),
    ("overhead_lines", "Clear of overhead power lines (safe distance kept)", "Underground and overhead utilities", True),
    ("access_route", "Access route safe for the rig and vehicles", "Access and ground", False),
    ("ground_bearing", "Ground firm and level for the rig (mats or platform if soft)", "Access and ground", True),
    ("water_work", "Work over water: pontoon checked, life jackets and rescue boat", "Access and ground", True),
    ("rig_inspection", "Daily rig inspection done and signed", "Rig and equipment", True),
    ("emergency_stop", "Emergency stop works; rotating parts guarded", "Rig and equipment", True),
    ("wire_ropes", "Wire ropes, hooks, shackles and slings in good condition", "Rig and equipment", True),
    ("leaks", "No hydraulic, fuel or oil leaks; spill kit on site", "Rig and equipment", False),
    ("ppe", "PPE worn: helmet, safety boots, gloves, glasses, hearing protection, vest", "People and PPE", True),
    ("crew_fit", "Crew fit for work; no alcohol or drugs; competent operator", "People and PPE", True),
    ("toolbox", "Toolbox talk held and the JSA explained to the crew", "People and PPE", True),
    ("first_aid", "First aid kit on site and a trained first aider", "Emergency preparedness", True),
    ("fire_extinguisher", "Fire extinguisher on site and inspected", "Emergency preparedness", True),
    ("emergency_contacts", "Emergency contacts and the nearest hospital known to the crew", "Emergency preparedness", True),
    ("barricade", "Work area barricaded with signage; public kept out", "Site control", True),
    ("traffic", "Traffic control where the work is near a road", "Site control", False),
    ("housekeeping", "Housekeeping: tools, rods and samples stored safely", "Site control", False),
    ("height", "Work at height on the mast: harness and anchor point", "Working at height", True),
    ("weather", "Weather suitable; stop rule for lightning and heavy rain briefed", "Weather", True),
    ("excavation_protection", "Pit or trench deeper than 1.5 m: sloped, benched or shored", "Excavation", True),
]

SOIL_TYPES = [("rock", "Stable rock"), ("A", "Type A (cohesive, qu ≥ 144 kPa)"), ("B", "Type B (qu 48–144 kPa, angular gravel, silt)"),
              ("C", "Type C (qu ≤ 48 kPa, granular, submerged or seeping)")]
# OSHA 1926 Subpart P Appendix B: maximum allowable slope (H : V) for excavations under 20 ft (6.1 m).
SLOPE_HV = {"rock": 0.0, "A": 0.75, "B": 1.0, "C": 1.5}
RISK = [("low", "Low"), ("medium", "Medium"), ("high", "High")]


def predrill_checklist(data: Dict[str, Any]) -> Dict[str, Any]:
    """01.05 pre-drilling checklist: fit to start when no critical item is answered "No"."""
    answers = {key: _txt(data.get(key)) for key, _, _, _ in CHECK_ITEMS}
    extra = [r for r in _rows(data, "other_checks") if _txt(r.get("item"))]
    jsa = [r for r in _rows(data, "jsa") if _txt(r.get("step")) or _txt(r.get("hazard"))]
    if not any(answers.values()) and not extra and not jsa:
        raise CalcError("Answer the checklist items")
    labels = dict(YNA)
    rows: List[List[Any]] = []
    blocking: List[str] = []
    actions: List[str] = []
    missing: List[str] = []
    counts = {"yes": 0, "no": 0, "na": 0, "": 0}
    for key, label, group, critical in CHECK_ITEMS:
        a = answers[key]
        counts[a if a in counts else ""] += 1
        rows.append([group, label, "Critical" if critical else "", labels.get(a, "Not answered")])
        if a == "no":
            (blocking if critical else actions).append(label)
        elif not a and critical:
            missing.append(label)
    for r in extra:
        a = _txt(r.get("answer"))
        critical = bool(r.get("critical"))
        counts[a if a in counts else ""] += 1
        rows.append(["Other", _txt(r.get("item")), "Critical" if critical else "", labels.get(a, "Not answered")])
        if a == "no":
            (blocking if critical else actions).append(_txt(r.get("item")))
        elif not a and critical:
            missing.append(_txt(r.get("item")))
    notes: List[str] = []
    depth = num(data.get("excavation_depth"))
    soil = _txt(data.get("soil_type"))
    values: List[Value] = []
    if depth is not None and depth > 0:
        values.append(("Excavation depth", depth, "m"))
        if depth >= 1.5:
            if not soil:
                missing.append("Soil type for the excavation")
            elif soil in SLOPE_HV:
                hv = SLOPE_HV[soil]
                values += [("Maximum slope (H:V)", f"{hv:g} : 1" if hv else "Vertical", ""),
                           ("Slope angle", rnd(90.0 if hv == 0 else math.degrees(math.atan(1 / hv)), 3), "°"),
                           ("Set-back of the top edge each side", rnd(depth * hv, 3), "m")]
                notes.append("Excavations 1.5 m (5 ft) deep or more need sloping, benching or shoring unless they are entirely in stable rock (29 CFR 1926.652).")
            if depth > 6.1:
                notes.append("Excavations deeper than 6.1 m (20 ft) need a protective system designed by a registered professional engineer (29 CFR 1926.652(b)).")
        else:
            notes.append("Excavation shallower than 1.5 m: no protective system is required unless a competent person sees signs of cave-in (29 CFR 1926.652(a)).")
    high_open = [r for r in jsa if _txt(r.get("risk")) == "high" and not _txt(r.get("control"))]
    if high_open:
        missing.append("Controls for the high-risk JSA steps")
    if not jsa:
        notes.append("Add the job safety analysis (step, hazard, control, PPE, responsible) before work starts.")
    if blocking:
        status = "Not fit to start"
        notes.append("Work must not start until the critical items answered No are corrected and the checklist is signed again.")
    elif missing:
        status = "Checklist incomplete"
        notes.append("Answer every critical item (Yes, No or N.A.) before work starts.")
    elif actions:
        status = "Fit to start, with actions"
        notes.append("Work may start; close the items answered No as soon as possible.")
    else:
        status = "Fit to start"
    values = [("Result", status, ""), ("Items answered Yes", counts["yes"], ""), ("Items answered No", counts["no"], ""),
              ("Items N.A.", counts["na"], ""), ("Not answered", counts[""], "")] + values
    tables = [table("Checklist", ["Group", "Item", "Critical", "Answer"], rows, key=["Answer", "Item"], note="Critical")]
    if blocking or actions or missing:
        tables.insert(0, table("Items to resolve", ["Item", "Kind"],
                               [[x, "Stops the work"] for x in blocking] + [[x, "Not answered"] for x in missing]
                               + [[x, "Action needed"] for x in actions]))
    # The JSA itself is printed with the worksheet data; the result only checks it.
    notes.append("Critical items stop the work when answered No; the other items need an action but do not stop the work.")
    return result(summary=[("Result", status, ""), ("Critical items No", len(blocking), ""), ("Not answered", len(missing), "")],
                  values=values, tables=tables, notes=notes,
                  method="Pre-drilling checklist and permit to work (29 CFR 1926 Subpart P, OSHA 3071 job hazard analysis, ISO 45001:2018)")
