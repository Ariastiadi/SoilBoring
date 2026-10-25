"""CPT / CPTu interpretation: corrected cone resistance, friction ratio, pore pressure ratio,
soil behaviour type index (Robertson 2009) and dissipation t50 / ch (Teh & Houlsby 1991)."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .calcbase import CalcError, axis, chart, interpolate, num, result, rnd, series, table, thin

PA = 101.325  # kPa, atmospheric pressure
GAMMA_W = 9.81
KGCM2 = 98.0665  # kPa per kg/cm²

ZONES = [  # upper Ic limit, zone number, description
    (1.31, 7, "Gravelly sand to dense sand"),
    (2.05, 6, "Sands: clean sand to silty sand"),
    (2.60, 5, "Sand mixtures: silty sand to sandy silt"),
    (2.95, 4, "Silt mixtures: clayey silt to silty clay"),
    (3.60, 3, "Clays: silty clay to clay"),
    (99.0, 2, "Organic soils: clay"),
]


def zone_of(ic: float) -> Dict[str, Any]:
    for limit, number, name in ZONES:
        if ic < limit:
            return {"zone": number, "name": name}
    return {"zone": 2, "name": ZONES[-1][2]}


def _ic(qt: float, fs: float, sv: float, sv_eff: float) -> Dict[str, Optional[float]]:
    net = qt - sv
    if net <= 0 or sv_eff <= 0:
        return {"Qtn": None, "Fr": None, "Ic": None, "n": None}
    fr = fs / net * 100 if fs > 0 else None
    if fr is None or fr <= 0:
        return {"Qtn": None, "Fr": None, "Ic": None, "n": None}
    n = 1.0
    ic = None
    qtn = None
    for _ in range(30):
        qtn = (net / PA) * (PA / sv_eff) ** n
        if qtn <= 0:
            return {"Qtn": None, "Fr": fr, "Ic": None, "n": None}
        ic_new = math.sqrt((3.47 - math.log10(qtn)) ** 2 + (math.log10(fr) + 1.22) ** 2)
        n_new = min(1.0, max(0.0, 0.381 * ic_new + 0.05 * (sv_eff / PA) - 0.15))
        if ic is not None and abs(ic_new - ic) < 1e-4 and abs(n_new - n) < 1e-4:
            ic = ic_new
            break
        ic, n = ic_new, n_new
    return {"Qtn": qtn, "Fr": fr, "Ic": ic, "n": n}


def interpret(record: Dict[str, Any]) -> Dict[str, Any]:
    readings = [r for r in record.get("readings") or [] if num(r.get("depth")) is not None and num(r.get("qc")) is not None]
    readings.sort(key=lambda r: float(r["depth"]))
    if len(readings) < 2:
        raise CalcError("Enter at least two readings")
    units = str(record.get("qc_unit") or "kgcm2")
    unit = 1000.0 if units in ("mpa", "mpa_kpa") else KGCM2  # to kPa
    fs_unit = 1.0 if units == "mpa_kpa" else unit
    a = num(record.get("area_ratio"))
    a = 0.8 if a is None else a
    gamma = num(record.get("unit_weight")) or 18.0
    nkt = num(record.get("nkt")) or 15.0
    gw = num(record.get("gw_depth"))
    gw = 0.0 if gw is None else gw
    has_u = any(num(r.get("u2")) is not None for r in readings)

    rows: List[List[Any]] = []
    profile: List[Dict[str, Any]] = []
    zone_len: Dict[int, float] = {}
    last_depth = 0.0
    for r in readings:
        z = float(r["depth"])
        qc = float(r["qc"]) * unit
        fs = (num(r.get("fs")) or 0.0) * fs_unit
        u2 = num(r.get("u2"))
        qt = qc + (u2 * (1 - a) if u2 is not None else 0.0)
        sv = gamma * z
        u0 = GAMMA_W * max(0.0, z - gw)
        sv_eff = sv - u0
        rf = fs / qt * 100 if qt > 0 and fs > 0 else None
        bq = (u2 - u0) / (qt - sv) if u2 is not None and qt - sv > 0 else None
        res = _ic(qt, fs, sv, sv_eff)
        ic = res["Ic"]
        zone = zone_of(ic) if ic is not None else None
        su = (qt - sv) / nkt if ic is not None and ic > 2.6 and qt > sv else None
        phi = 17.6 + 11 * math.log10(res["Qtn"]) if ic is not None and ic < 2.6 and res["Qtn"] and res["Qtn"] > 0 else None
        if zone:
            zone_len[zone["zone"]] = zone_len.get(zone["zone"], 0.0) + max(0.0, z - last_depth)
        last_depth = z
        profile.append({"z": z, "qt": qt / 1000, "rf": rf, "bq": bq, "ic": ic, "su": su, "phi": phi})
        rows.append([z, rnd(qt / 1000, 3), rnd(rf, 3), rnd(bq, 3) if has_u else None, rnd(ic, 3),
                     zone["zone"] if zone else None, rnd(su, 3), rnd(phi, 3)])

    total = sum(zone_len.values()) or 1.0
    zone_rows = [[number, name, rnd(zone_len.get(number, 0.0), 3), rnd(zone_len.get(number, 0.0) / total * 100, 3)]
                 for _, number, name in ZONES if zone_len.get(number)]
    dominant = max(zone_len.items(), key=lambda kv: kv[1])[0] if zone_len else None
    max_qt = max(p["qt"] for p in profile)
    thin_profile = thin(profile)
    charts = [
        chart("Corrected cone resistance qt", axis("qt (MPa)"), axis("Depth (m)", reverse=True),
              series("qt", [(p["qt"], p["z"]) for p in thin_profile], "line")),
        chart("Soil behaviour type index Ic", axis("Ic"), axis("Depth (m)", reverse=True),
              series("Ic", [(p["ic"], p["z"]) for p in thin_profile if p["ic"] is not None], "line"),
              series("Ic = 2.6", [(2.6, profile[0]["z"]), (2.6, profile[-1]["z"])], "line", dash=True)),
    ]
    if has_u:
        charts.append(chart("Pore pressure ratio Bq", axis("Bq"), axis("Depth (m)", reverse=True),
                            series("Bq", [(p["bq"], p["z"]) for p in thin_profile if p["bq"] is not None], "line")))
    values: List[Tuple[str, Any, str]] = [
        ("Maximum qt", rnd(max_qt, 3), "MPa"),
        ("Final depth", rnd(profile[-1]["z"], 4), "m"),
    ]
    if dominant is not None:
        values.append(("Dominant soil behaviour", next(n for _, z, n in ZONES if z == dominant), ""))
    tables = [
        table("Soil behaviour type (Robertson 2009)", ["Zone", "Soil behaviour", "Thickness (m)", "Share (%)"], zone_rows),
        table("Interpretation", ["Depth (m)", "qt (MPa)", "Rf (%)", "Bq", "Ic", "Zone", "su (kPa)", "φ' (°)"],
              thin(rows, 300)),
    ]
    notes = [
        "qt = qc + u2 (1 − a); without u2, qt = qc.",
        "Unit weight is taken as constant with depth; pore pressure is hydrostatic below the groundwater level.",
        "su = (qt − σv0) / Nkt for Ic > 2.6; φ' = 17.6 + 11 log Qtn (Kulhawy & Mayne) for Ic < 2.6.",
        "Preliminary estimate only; results must be checked by a qualified geotechnical engineer.",
    ]
    out_dis = _dissipation(record, gamma, gw)
    if out_dis:
        values.extend(out_dis["values"])
        charts.append(out_dis["chart"])
        notes.extend(out_dis["notes"])
    summary = [("Maximum qt", rnd(max_qt, 3), "MPa")]
    if dominant is not None:
        summary.append(("Zone", dominant, ""))
    if out_dis and out_dis.get("t50") is not None:
        summary.append(("t50", out_dis["t50"], "s"))
    return result(summary, values, tables, charts, notes,
                  method="Robertson (2009) normalised soil behaviour type; Teh & Houlsby (1991) dissipation")


def _dissipation(record: Dict[str, Any], gamma: float, gw: float) -> Optional[Dict[str, Any]]:
    raw = [(num(r.get("time")), num(r.get("u2"))) for r in record.get("dissipation") or []]
    data: List[Tuple[float, float]] = sorted((t, u) for t, u in raw if t is not None and u is not None and t >= 0)
    if len(data) < 3:
        return None
    depth = num(record.get("dissipation_depth"))
    u0 = GAMMA_W * max(0.0, (depth or 0.0) - gw) if depth is not None else None
    ui = max(u for _, u in data[:3])
    values: List[Tuple[str, Any, str]] = [("Initial pore pressure ui", rnd(ui, 3), "kPa")]
    notes = ["t50 from the time at 50% dissipation between the initial and the hydrostatic pressure."]
    t50 = None
    if u0 is not None and ui > u0:
        u50 = u0 + (ui - u0) / 2
        times = [t for t, _ in data]
        pressures = [u for _, u in data]
        for i in range(1, len(data)):
            if pressures[i - 1] >= u50 >= pressures[i]:
                # interpolate on log time
                t0, t1 = max(times[i - 1], 0.01), max(times[i], 0.01)
                frac = (pressures[i - 1] - u50) / (pressures[i - 1] - pressures[i]) if pressures[i - 1] != pressures[i] else 0
                t50 = 10 ** (math.log10(t0) + frac * (math.log10(t1) - math.log10(t0)))
                break
        values.append(("Hydrostatic pressure u0", rnd(u0, 3), "kPa"))
        if t50 is not None:
            ir = num(record.get("rigidity_index")) or 100.0
            radius_cm = 1.784  # 10 cm² cone
            ch = 0.245 * radius_cm ** 2 * math.sqrt(ir) / t50  # cm²/s
            values.append(("t50", rnd(t50, 3), "s"))
            values.append(("ch (Teh & Houlsby)", rnd(ch * 3153.6, 3), "m²/year"))
            notes.append("ch = T50* r² √Ir / t50 with T50* = 0.245 and r = 1.784 cm (10 cm² cone).")
        else:
            notes.append("50% dissipation was not reached during the test.")
    else:
        notes.append("Enter the test depth (above the groundwater level u0 = 0) to find t50.")
    ch_chart = chart("Dissipation", axis("Time (s)", log=True), axis("u2 (kPa)"),
                     series("u2", [(max(t, 0.1), u) for t, u in data], "line"),
                     series("u0", [(max(data[0][0], 0.1), u0), (max(data[-1][0], 0.1), u0)], "line", dash=True)
                     if u0 is not None else series("u0", [], "line"))
    return {"values": values, "chart": ch_chart, "notes": notes, "t50": rnd(t50, 3) if t50 else None}


