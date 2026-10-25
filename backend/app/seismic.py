"""Seismic site class and design response spectrum after SNI 1726:2019 (tables equal to
ASCE 7-16), from the SPT N, undrained strength or shear wave velocity of the top 30 m."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .calcbase import CalcError, axis, chart, result, rnd, series, table

# Amplification factors; columns are the spectral values the factor is given for.
_FA_COLS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5]
_FA = {"SA": [0.8] * 6, "SB": [0.9] * 6, "SC": [1.3, 1.3, 1.2, 1.2, 1.2, 1.2],
       "SD": [1.6, 1.4, 1.2, 1.1, 1.0, 1.0], "SE": [2.4, 1.7, 1.3, 1.1, 0.9, 0.8]}
_FV_COLS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
_FV = {"SA": [0.8] * 6, "SB": [0.8] * 6, "SC": [1.5, 1.5, 1.5, 1.5, 1.5, 1.4],
       "SD": [2.4, 2.2, 2.0, 1.9, 1.8, 1.7], "SE": [4.2, 3.3, 2.8, 2.4, 2.2, 2.0]}
_FPGA_COLS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
_FPGA = {"SA": [0.8] * 6, "SB": [0.9] * 6, "SC": [1.3, 1.2, 1.2, 1.2, 1.2, 1.2],
         "SD": [1.6, 1.4, 1.3, 1.2, 1.1, 1.1], "SE": [2.4, 1.9, 1.6, 1.4, 1.2, 1.1]}

CLASS_NAMES = {
    "SA": "Hard rock", "SB": "Rock", "SC": "Very dense soil and soft rock", "SD": "Medium soil",
    "SE": "Soft soil", "SF": "Special soil (site-specific analysis required)",
}


def _factor(table_: Dict[str, List[float]], cols: List[float], site: str, value: float) -> Optional[float]:
    row = table_.get(site)
    if row is None:
        return None
    if value <= cols[0]:
        return row[0]
    if value >= cols[-1]:
        return row[-1]
    for i in range(1, len(cols)):
        if value <= cols[i]:
            f = (value - cols[i - 1]) / (cols[i] - cols[i - 1])
            return row[i - 1] + f * (row[i] - row[i - 1])
    return row[-1]


def average_over_30m(layers: Sequence[Tuple[float, float, float]]) -> Tuple[Optional[float], float]:
    """Harmonic average Σd / Σ(d/x) over the top 30 m of (top, base, value) layers.
    The deepest value is extended to 30 m when the data stop short. Returns (average, depth covered)."""
    usable = sorted((t, b, v) for t, b, v in layers if b > t and v > 0)
    if not usable:
        return None, 0.0
    total_d = 0.0
    total_r = 0.0
    covered = 0.0
    for top, base, value in usable:
        if top >= 30:
            break
        b = min(base, 30.0)
        d = b - max(top, covered)
        if d <= 0:
            continue
        total_d += d
        total_r += d / value
        covered = b
    if covered < 30 and usable:
        d = 30 - covered
        total_d += d
        total_r += d / usable[-1][2]
    return (total_d / total_r if total_r else None), min(max(b for _, b, _ in usable), 30.0)


def spt_layers(spt: Sequence[Tuple[float, float]]) -> List[Tuple[float, float, float]]:
    """SPT tests as layers: each N stands for the depth half-way to its neighbours."""
    tests = sorted((d, max(n, 1.0)) for d, n in spt)  # N = 0 would make the harmonic mean zero
    out = []
    for i, (d, n) in enumerate(tests):
        top = 0.0 if i == 0 else (tests[i - 1][0] + d) / 2
        base = max(d, top + 0.1) if i + 1 == len(tests) else (d + tests[i + 1][0]) / 2
        out.append((top, base, min(n, 100.0)))
    return out


def classify(vs: Optional[float] = None, n: Optional[float] = None, su: Optional[float] = None) -> str:
    if vs is not None:
        if vs > 1500:
            return "SA"
        if vs > 750:
            return "SB"
        if vs > 350:
            return "SC"
        if vs >= 175:
            return "SD"
        return "SE"
    if n is not None:
        return "SC" if n > 50 else "SD" if n >= 15 else "SE"
    if su is not None:
        return "SC" if su >= 100 else "SD" if su >= 50 else "SE"
    raise CalcError("Enter SPT, undrained strength or shear wave velocity data")


def design(site: str, pga: float, ss: float, s1: float, tl: float = 20.0) -> Dict[str, Any]:
    fa = _factor(_FA, _FA_COLS, site, ss)
    fv = _factor(_FV, _FV_COLS, site, s1)
    fpga = _factor(_FPGA, _FPGA_COLS, site, pga)
    if fa is None or fv is None or fpga is None:
        return {"site": site, "fa": None, "fv": None, "fpga": None}
    sms, sm1 = fa * ss, fv * s1
    sds, sd1 = 2 / 3 * sms, 2 / 3 * sm1
    t0 = 0.2 * sd1 / sds if sds > 0 else 0.0
    ts = sd1 / sds if sds > 0 else 0.0
    curve = []
    t = 0.0
    while t <= max(4.0, ts * 3) + 1e-9:
        if t < t0:
            sa = sds * (0.4 + 0.6 * t / t0) if t0 > 0 else sds
        elif t <= ts:
            sa = sds
        elif t <= tl:
            sa = sd1 / t
        else:
            sa = sd1 * tl / t ** 2
        curve.append((round(t, 3), sa))
        t += 0.02 if t < 1 else 0.05
    return {"site": site, "fa": fa, "fv": fv, "fpga": fpga, "sms": sms, "sm1": sm1, "sds": sds, "sd1": sd1,
            "pga_m": fpga * pga, "t0": t0, "ts": ts, "curve": curve}


def site_class_analysis(inputs: Dict[str, Any], spt: Sequence[Tuple[float, float]] = ()) -> Dict[str, Any]:
    def f(key: str) -> Optional[float]:
        v = inputs.get(key)
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            raise CalcError(f"{key} must be a number")

    pga, ss, s1 = f("pga"), f("ss"), f("s1")
    if pga is None or ss is None or s1 is None:
        raise CalcError("Enter PGA, Ss and S1 from the hazard map (site class SB)")
    tl = f("tl") or 20.0
    vs_rows = [(float(r["top"]), float(r["base"]), float(r["vs"])) for r in inputs.get("vs_layers") or []
               if r.get("top") not in (None, "") and r.get("base") not in (None, "") and r.get("vs") not in (None, "")]
    rows = []
    vs_bar = n_bar = None
    if vs_rows:
        vs_bar, covered = average_over_30m(vs_rows)
        rows.append(["Vs30", rnd(vs_bar, 4), "m/s", rnd(covered, 3)])
    if spt:
        n_bar, covered = average_over_30m(spt_layers(spt))
        rows.append(["N̄ (SPT)", rnd(n_bar, 3), "", rnd(covered, 3)])
    forced = str(inputs.get("site") or "").upper()
    site = forced if forced in CLASS_NAMES else classify(vs_bar, n_bar)
    if site == "SF":
        raise CalcError("Site class SF needs a site-specific response analysis")
    d = design(site, pga, ss, s1, tl)
    values: List[Tuple[str, Any, str]] = [
        ("Site class", f"{site} – {CLASS_NAMES[site]}", ""),
        ("Fa", rnd(d["fa"], 3), ""), ("Fv", rnd(d["fv"], 3), ""), ("FPGA", rnd(d["fpga"], 3), ""),
        ("SMS", rnd(d["sms"], 3), "g"), ("SM1", rnd(d["sm1"], 3), "g"),
        ("SDS", rnd(d["sds"], 3), "g"), ("SD1", rnd(d["sd1"], 3), "g"),
        ("PGA_M (amax)", rnd(d["pga_m"], 3), "g"), ("T0", rnd(d["t0"], 3), "s"), ("Ts", rnd(d["ts"], 3), "s"),
    ]
    notes = [
        "Averages over the top 30 m: Σd / Σ(d/x); the deepest value is extended to 30 m when the data stop short.",
        "Fa, Fv and FPGA after SNI 1726:2019 with linear interpolation; PGA, Ss and S1 are bedrock (SB) values from the hazard map.",
        "Site class SF (liquefiable, sensitive or very soft thick clay) needs a site-specific analysis; check it separately.",
        "Use PGA_M as amax in the liquefaction analysis.",
        "Preliminary estimate only; results must be checked by a qualified geotechnical engineer.",
    ]
    return result(
        summary=[("Site class", site, ""), ("SDS", rnd(d["sds"], 3), "g"), ("SD1", rnd(d["sd1"], 3), "g"),
                 ("PGA_M", rnd(d["pga_m"], 3), "g")],
        values=values,
        tables=[table("Averages over 30 m", ["Parameter", "Value", "Unit", "Data to depth (m)"], rows)] if rows else [],
        charts=[chart("Design response spectrum", axis("Period T (s)"), axis("Sa (g)"),
                      series("Sa", d["curve"], "line"))],
        notes=notes, method="SNI 1726:2019 site classification and design spectrum")
