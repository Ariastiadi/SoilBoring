"""Laboratory test calculations: raw readings in, results out.

One pure function per test. Each takes the cleaned worksheet data (numbers as floats or
None, selects as strings, item tables as lists of row dicts) and returns
``calcbase.result(...)`` with a ``lab`` dict whose keys are the result fields of that test.

Units: masses in g, lengths in mm or cm as labelled, stresses in kPa (inputs in kg/cm² are
converted with 1 kg/cm² = 98.0665 kPa), unit weights in kN/m³ (γ = ρ · 9.81), densities in
g/cm³. Where the laboratory templates deviate from the ASTM / SNI method the standard method
is the default and the template's way is offered as an option of the worksheet.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .calcbase import CalcError, axis, chart, interpolate, linear_fit, num, result, rnd, series, table

KPA_PER_KGCM2 = 98.0665
GAMMA_W = 9.81  # kN/m³; unit weight γ = ρ (g/cm³) · 9.81
RING_N = {"kN": 1000.0, "kgf": 9.80665, "lbf": 4.4482216}  # newtons per unit of the ring factor
IN_MM = 25.4
MAX_SPECIMENS = 4

# Density of water (g/cm³) by temperature (°C).
WATER_DENSITY = {
    15: 0.99910, 16: 0.99894, 17: 0.99877, 18: 0.99859, 19: 0.99840, 20: 0.99821, 21: 0.99799,
    22: 0.99777, 23: 0.99754, 24: 0.99730, 25: 0.99705, 26: 0.99679, 27: 0.99652, 28: 0.99624,
    29: 0.99595, 30: 0.99565, 31: 0.99534, 32: 0.99503, 33: 0.99470, 34: 0.99437, 35: 0.99403,
}
# Dynamic viscosity of water (poise) by temperature (°C).
WATER_VISCOSITY = {
    15: 0.01138, 16: 0.01109, 17: 0.01081, 18: 0.01053, 19: 0.01027, 20: 0.01009, 21: 0.00984,
    22: 0.00961, 23: 0.00938, 24: 0.00916, 25: 0.00895, 26: 0.00875, 27: 0.00855, 28: 0.00836,
    29: 0.00818, 30: 0.00800, 31: 0.00784, 32: 0.00768, 33: 0.00752, 34: 0.00737, 35: 0.00719,
}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _r(value: Optional[float], digits: int = 2) -> Optional[float]:
    """Rounded to a fixed number of decimals (display only)."""
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def _opt(data: Dict[str, Any], key: str, default: Optional[float] = None) -> Optional[float]:
    value = num(data.get(key))
    return default if value is None else value


def _need(data: Dict[str, Any], key: str, label: str, positive: bool = True) -> float:
    value = num(data.get(key))
    if value is None:
        raise CalcError(f"{label} is required")
    if positive and value <= 0:
        raise CalcError(f"{label} must be greater than zero")
    return value


def _choice(data: Dict[str, Any], key: str, default: str) -> str:
    return str(data.get(key) or default)


def _rows(data: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    return [r for r in data.get(key) or [] if isinstance(r, dict)]


def _mean(values: Sequence[Optional[float]]) -> Optional[float]:
    good = [v for v in values if v is not None and math.isfinite(v)]
    return sum(good) / len(good) if good else None


def _table_temperature(tbl: Dict[int, float], t: float) -> float:
    if t < 15 or t > 35:
        raise CalcError("The temperature must be between 15 and 35 °C")
    lo = int(math.floor(t))
    hi = min(lo + 1, 35)
    if lo == hi:
        return tbl[lo]
    return tbl[lo] + (tbl[hi] - tbl[lo]) * (t - lo)


def water_density(t: float) -> float:
    return _table_temperature(WATER_DENSITY, t)


def water_viscosity(t: float) -> float:
    return _table_temperature(WATER_VISCOSITY, t)


def water_content(wet: Optional[float], dry: Optional[float], tare: Optional[float]) -> Optional[float]:
    """w (%) from container + wet soil, container + dry soil and container; None if incomplete."""
    if wet is None or dry is None:
        return None
    tare = tare or 0.0
    if dry - tare <= 0:
        raise CalcError("The dry soil mass must be greater than the container mass")
    if wet < dry:
        raise CalcError("The wet mass must not be less than the dry mass")
    return (wet - dry) / (dry - tare) * 100


def _row_w(row: Dict[str, Any], suffix: str = "") -> Optional[float]:
    return water_content(num(row.get("m_wet" + suffix)), num(row.get("m_dry" + suffix)), num(row.get("m_tare" + suffix)))


def _ring_newton(data: Dict[str, Any], default_factor: Optional[float], default_unit: str) -> float:
    """Newtons per dial division of the proving ring."""
    factor = _opt(data, "ring_factor", default_factor)
    if factor is None:
        raise CalcError("Proving ring factor is required")
    if factor <= 0:
        raise CalcError("Proving ring factor must be greater than zero")
    unit = _choice(data, "ring_unit", default_unit)
    if unit not in RING_N:
        raise CalcError("Choose the unit of the proving ring factor")
    return factor * RING_N[unit]


def _to_kpa(value: float, unit: str) -> float:
    return value if unit == "kpa" else value * KPA_PER_KGCM2


def _consistency(qu_kpa: float) -> str:
    for limit, name in ((25, "Very soft"), (50, "Soft"), (100, "Medium"), (200, "Stiff"), (400, "Very stiff")):
        if qu_kpa < limit:
            return name
    return "Hard"


def _mohr_series(name: str, s3: float, s1: float) -> Dict[str, Any]:
    centre, radius = (s1 + s3) / 2, (s1 - s3) / 2
    pts = [(centre + radius * math.cos(math.radians(a)), radius * math.sin(math.radians(a))) for a in range(180, -1, -5)]
    return series(name, pts, "line")


def strength_fit(points: Sequence[Tuple[float, float]]) -> Dict[str, Any]:
    """Mohr–Coulomb parameters from failure points in p–q space (p = (σ1+σ3)/2, q = (σ1−σ3)/2).

    q = a + p tanα gives φ = asin(tanα), c = a / cos φ. A negative intercept is replaced by an
    envelope through the origin; a slope that does not rise gives φ = 0 and c = mean q."""
    ps = [p for p, _ in points]
    qs = [q for _, q in points]
    if len(points) < 2 or max(ps) - min(ps) <= 1e-9:
        mean_q = sum(qs) / len(qs)
        return {"c": mean_q, "phi": 0.0, "r2": None, "case": "single"}
    a, b, r2 = linear_fit(ps, qs)
    if b >= 1:
        raise CalcError("The failure points do not give a valid strength envelope")
    if b <= 0:
        return {"c": sum(qs) / len(qs), "phi": 0.0, "r2": r2, "case": "flat"}
    if a < 0:
        slope = sum(p * q for p, q in points) / sum(p * p for p in ps)
        if slope >= 1:
            raise CalcError("The failure points do not give a valid strength envelope")
        return {"c": 0.0, "phi": math.degrees(math.asin(slope)), "r2": r2, "case": "origin"}
    phi = math.asin(b)
    return {"c": a / math.cos(phi), "phi": math.degrees(phi), "r2": r2, "case": "fit"}


def _fit_notes(fit: Dict[str, Any]) -> List[str]:
    if fit["case"] == "origin":
        return ["The fitted intercept was negative; the envelope is taken through the origin."]
    if fit["case"] in ("flat", "single"):
        return ["The strength does not increase with confining stress; φ is taken as zero and c as the mean strength."]
    return []


def _solve(matrix: List[List[float]], rhs: List[float]) -> List[float]:
    """Gaussian elimination with partial pivoting (small systems)."""
    n = len(rhs)
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-14:
            raise CalcError("The points do not allow a curve fit")
        a[col], a[piv] = a[piv], a[col]
        for r in range(col + 1, n):
            f = a[r][col] / a[col][col]
            for k in range(col, n + 1):
                a[r][k] -= f * a[col][k]
    out = [0.0] * n
    for r in range(n - 1, -1, -1):
        out[r] = (a[r][n] - sum(a[r][k] * out[k] for k in range(r + 1, n))) / a[r][r]
    return out


def polyfit(xs: Sequence[float], ys: Sequence[float], degree: int) -> Callable[[float], float]:
    """Least-squares polynomial; returns the fitted function (x is centred for conditioning)."""
    mx = sum(xs) / len(xs)
    us = [x - mx for x in xs]
    m = degree + 1
    ata = [[sum(u ** (i + j) for u in us) for j in range(m)] for i in range(m)]
    aty = [sum(y * u ** i for u, y in zip(us, ys)) for i in range(m)]
    coef = _solve(ata, aty)
    return lambda x: sum(c * (x - mx) ** i for i, c in enumerate(coef))


class Pchip:
    """Shape-preserving piecewise cubic Hermite interpolation (Fritsch–Carlson) through (x, y),
    x strictly increasing. Unlike a natural spline it does not overshoot between the points."""

    def __init__(self, xs: Sequence[float], ys: Sequence[float]) -> None:
        n = len(xs)
        self.x, self.y = list(xs), list(ys)
        self.h = [xs[i + 1] - xs[i] for i in range(n - 1)]
        if any(v <= 0 for v in self.h):
            raise CalcError("The pressures must increase from one load step to the next")
        delta = [(ys[i + 1] - ys[i]) / self.h[i] for i in range(n - 1)]
        m = [0.0] * n
        m[0], m[-1] = delta[0], delta[-1]
        for i in range(1, n - 1):
            if delta[i - 1] * delta[i] > 0:
                w1, w2 = 2 * self.h[i] + self.h[i - 1], self.h[i] + 2 * self.h[i - 1]
                m[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])
        self.m = m

    def eval(self, x: float) -> Tuple[float, float, float]:
        """Value, first and second derivative."""
        i = 0
        while i < len(self.h) - 1 and x > self.x[i + 1]:
            i += 1
        h = self.h[i]
        t = (x - self.x[i]) / h
        y0, y1, m0, m1 = self.y[i], self.y[i + 1], self.m[i] * h, self.m[i + 1] * h
        y = (2 * t ** 3 - 3 * t ** 2 + 1) * y0 + (t ** 3 - 2 * t ** 2 + t) * m0 + (-2 * t ** 3 + 3 * t ** 2) * y1 + (t ** 3 - t ** 2) * m1
        d1 = ((6 * t ** 2 - 6 * t) * y0 + (3 * t ** 2 - 4 * t + 1) * m0 + (6 * t - 6 * t ** 2) * y1 + (3 * t ** 2 - 2 * t) * m1) / h
        d2 = ((12 * t - 6) * y0 + (6 * t - 4) * m0 + (6 - 12 * t) * y1 + (6 * t - 2) * m1) / h ** 2
        return y, d1, d2


def _log_interp_x(target: float, xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """x where y reaches target, interpolating linearly in log10 x (xs > 0)."""
    for i in range(1, len(xs)):
        y0, y1 = ys[i - 1], ys[i]
        if (y0 - target) * (y1 - target) <= 0 and y0 != y1:
            f = (target - y0) / (y1 - y0)
            return float(10 ** (math.log10(xs[i - 1]) + f * (math.log10(xs[i]) - math.log10(xs[i - 1]))))
    return None


# --------------------------------------------------------------------------- #
# Classification (ASTM D2487)
# --------------------------------------------------------------------------- #

def a_line(ll: float) -> float:
    return 0.73 * (ll - 20)


def plasticity_symbol(ll: float, pi: float) -> str:
    """Position on the plasticity chart: CL, CH, ML, MH or CL-ML."""
    above = pi >= 4 and pi >= a_line(ll)
    if ll >= 50:
        return "CH" if above else "MH"
    if not above:
        return "ML"
    return "CL-ML" if pi <= 7 else "CL"


def uscs_symbol(fines: float, sand: float, gravel: float, ll: Optional[float], pi: Optional[float],
                cu: Optional[float] = None, cc: Optional[float] = None) -> str:
    """USCS group symbol (ASTM D2487, organic soils excluded); "" when the data do not decide it.

    fines, sand and gravel in %; pi = 0 (or None with ll None) marks non-plastic fines."""
    if fines >= 50:
        if ll is None:
            return "ML" if pi == 0 else ""
        return plasticity_symbol(ll, pi or 0.0)
    prefix = "G" if gravel > sand else "S"

    def graded() -> Optional[str]:
        if cu is None or cc is None:
            return None
        return "W" if cu >= (4 if prefix == "G" else 6) and 1 <= cc <= 3 else "P"

    def fines_kind() -> Optional[str]:
        if ll is None:
            return "M" if pi == 0 else None
        sym = plasticity_symbol(ll, pi or 0.0)
        return "CM" if sym == "CL-ML" else ("C" if sym in ("CL", "CH") else "M")

    if fines < 5:
        g = graded()
        return prefix + g if g else ""
    kind = fines_kind()
    if fines > 12:
        if kind is None:
            return ""
        return f"{prefix}C-{prefix}M" if kind == "CM" else prefix + kind
    g = graded()
    if g is None or kind is None:
        return ""
    return f"{prefix}{g}-{prefix}{'C' if kind in ('C', 'CM') else 'M'}"


# --------------------------------------------------------------------------- #
# 05.04 Water content and density
# --------------------------------------------------------------------------- #

def moisture(data: Dict[str, Any]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for row in _rows(data, "specimens"):
        if num(row.get("m_wet")) is None and num(row.get("m_dry")) is None:
            continue
        w = _row_w(row)
        if w is None:
            raise CalcError("Enter the wet and the dry mass of each specimen")
        tare = num(row.get("m_tare")) or 0.0
        vol = num(row.get("volume"))
        rho_m = rho_d = None
        if vol is not None:
            if vol <= 0:
                raise CalcError("The ring volume must be greater than zero")
            rho_m = (float(row["m_wet"]) - tare) / vol
            rho_d = (float(row["m_dry"]) - tare) / vol
        rows.append({"id": row.get("ring_no") or "", "w": w, "rho_m": rho_m, "rho_d": rho_d})
    if not rows:
        raise CalcError("Enter at least one specimen")
    w_avg = _mean([r["w"] for r in rows])
    rho_m_avg = _mean([r["rho_m"] for r in rows])
    rho_d_avg = _mean([r["rho_d"] for r in rows])
    assert w_avg is not None
    g_bulk = rho_m_avg * GAMMA_W if rho_m_avg is not None else None
    g_dry = rho_d_avg * GAMMA_W if rho_d_avg is not None else None
    values: List[Tuple[str, Any, str]] = [("Water content w", _r(w_avg), "%")]
    if rho_m_avg is not None and rho_d_avg is not None:
        values += [("Bulk density ρ", _r(rho_m_avg, 3), "g/cm³"), ("Dry density ρd", _r(rho_d_avg, 3), "g/cm³"),
                   ("Bulk unit weight γ", _r(g_bulk), "kN/m³"), ("Dry unit weight γd", _r(g_dry), "kN/m³")]
    gs = _opt(data, "gs")
    notes = ["Water content is the mass of water divided by the mass of dry soil."]
    if gs is not None and rho_d_avg:
        e = gs / rho_d_avg - 1
        if e > 0:
            values += [("Void ratio e", _r(e, 3), ""), ("Porosity n", _r(e / (1 + e) * 100, 1), "%"),
                       ("Degree of saturation Sr", _r(min(w_avg * gs / e, 100.0), 1), "%")]
    if len(rows) > 1:
        ws = [r["w"] for r in rows]
        if max(ws) - min(ws) > 0.1 * w_avg:
            notes.append("The specimens differ by more than 10 % of the mean water content; check the readings.")
    tbl = table("Specimens", ["Ring / container", "Water content w (%)", "Bulk density ρ (g/cm³)", "Dry density ρd (g/cm³)"],
                [[r["id"], _r(r["w"]), _r(r["rho_m"], 3), _r(r["rho_d"], 3)] for r in rows])
    summary = [("w", _r(w_avg), "%"), ("γ", _r(g_bulk), "kN/m³"), ("γd", _r(g_dry), "kN/m³")]
    return result(summary, values, [tbl], [], notes, method="ASTM D2216 oven drying; density from ring volume",
                  lab={"w": _r(w_avg), "gamma_bulk": _r(g_bulk), "gamma_dry": _r(g_dry)})


# --------------------------------------------------------------------------- #
# 05.05 Specific gravity
# --------------------------------------------------------------------------- #

def specific_gravity(data: Dict[str, Any]) -> Dict[str, Any]:
    rho20 = WATER_DENSITY[20]
    tables = []
    values: List[Tuple[str, Any, str]] = []
    notes: List[str] = []
    # Pycnometer calibration: volume of each pycnometer from its mass filled with water.
    vp: Dict[str, List[float]] = {}
    cal_rows = []
    for row in _rows(data, "calibration"):
        t, mp, mpw = num(row.get("temp")), num(row.get("m_p")), num(row.get("m_pw"))
        if t is None or mp is None or mpw is None:
            continue
        if mpw <= mp:
            raise CalcError("The pycnometer filled with water must weigh more than the empty pycnometer")
        v = (mpw - mp) / water_density(t)
        key = str(row.get("pycnometer_no") or "")
        vp.setdefault(key, []).append(v)
        cal_rows.append([key, t, mp, mpw, _r(v, 3)])
    if cal_rows:
        tables.append(table("Pycnometer calibration", ["Pycnometer", "Temperature (°C)", "Pycnometer (g)",
                                                       "Pycnometer + water (g)", "Volume Vp (mL)"], cal_rows))
        # Scatter of the calibrated volume per pycnometer (sample standard deviation); the worst one is reported.
        sds = []
        for vols in vp.values():
            if len(vols) >= 2:
                mean = sum(vols) / len(vols)
                sds.append(math.sqrt(sum((v - mean) ** 2 for v in vols) / (len(vols) - 1)))
        if sds:
            values.append(("Standard deviation of Vp", _r(max(sds), 4), "mL"))
            if max(sds) >= 0.05:
                notes.append("The calibration volumes scatter by 0.05 mL or more; repeat the calibration or replace the pycnometer.")
    det_rows = []
    g20s: List[float] = []
    for row in _rows(data, "determinations"):
        t, mps, mp = num(row.get("temp")), num(row.get("m_ps")), num(row.get("m_p"))
        mpw, mpws = num(row.get("m_pw")), num(row.get("m_pws"))
        if mps is None and mpws is None:
            continue
        if t is None:
            raise CalcError("Temperature is required")
        if mps is None or mp is None or mpws is None:
            raise CalcError("Enter the pycnometer, pycnometer + soil and pycnometer + water + soil masses")
        rho_t = water_density(t)
        key = str(row.get("pycnometer_no") or "")
        if mpw is None:
            # ASTM D854: mass of the pycnometer filled with water at the test temperature from its calibrated volume.
            if key not in vp:
                raise CalcError("Pycnometer + water is required (or a calibration of that pycnometer)")
            mpw = mp + sum(vp[key]) / len(vp[key]) * rho_t
        ms = mps - mp
        if ms <= 0:
            raise CalcError("The pycnometer with dry soil must weigh more than the empty pycnometer")
        vs = (mpw - (mpws - ms)) / rho_t
        if vs <= 0:
            raise CalcError("The masses give no soil volume; check the readings")
        gt = ms / vs / rho_t
        g20 = gt * rho_t / rho20
        g20s.append(g20)
        det_rows.append([key, t, _r(ms, 3), _r(vs, 3), _r(gt, 4), _r(g20, 4)])
    if not g20s:
        raise CalcError("Enter at least one determination")
    gs = sum(g20s) / len(g20s)
    if len(g20s) > 1 and max(g20s) - min(g20s) > 0.02:
        notes.append("The determinations differ by more than 0.02; repeat the test.")
    notes.append("Gs is reported at 20 °C: G20 = K · Gt with K = ρw(T) / ρw(20 °C).")
    tables.insert(0, table("Determinations", ["Pycnometer", "Temperature (°C)", "Dry soil Ms (g)", "Soil volume Vs (cm³)",
                                              "Gt", "G20"], det_rows))
    values.insert(0, ("Specific gravity Gs (20 °C)", _r(gs, 3), ""))
    return result([("Gs", _r(gs, 3), "")], values, tables, [], notes,
                  method="ASTM D854 water pycnometer", lab={"gs": _r(gs, 3)})


# --------------------------------------------------------------------------- #
# 05.06 Grain size: sieve and hydrometer
# --------------------------------------------------------------------------- #

def _finer_at(curve: List[Tuple[float, float]], d: float) -> Optional[float]:
    """% finer than d on a curve of (size mm, % finer) sorted by increasing size (log interpolation)."""
    if not curve:
        return None
    if d >= curve[-1][0]:
        return curve[-1][1] if d == curve[-1][0] else 100.0 if curve[-1][1] >= 99.999 else None
    if d < curve[0][0]:
        return 0.0 if curve[0][1] <= 0 else None
    for (d0, p0), (d1, p1) in zip(curve, curve[1:]):
        if d0 <= d <= d1:
            if d1 == d0:
                return p1
            f = (math.log10(d) - math.log10(d0)) / (math.log10(d1) - math.log10(d0))
            return p0 + f * (p1 - p0)
    return None


def _size_at(curve: List[Tuple[float, float]], pct: float) -> Optional[float]:
    """Particle size at which pct % is finer (Dxx), log interpolation; None outside the curve."""
    for (d0, p0), (d1, p1) in zip(curve, curve[1:]):
        if p0 <= pct <= p1 and p1 > p0:
            f = (pct - p0) / (p1 - p0)
            return float(10 ** (math.log10(d0) + f * (math.log10(d1) - math.log10(d0))))
    return None


def grain_size(data: Dict[str, Any]) -> Dict[str, Any]:
    sieves = sorted([r for r in _rows(data, "sieves") if num(r.get("opening")) is not None and num(r.get("retained")) is not None],
                    key=lambda r: -float(r["opening"]))
    hydro = [r for r in _rows(data, "hydrometer") if num(r.get("t_min")) is not None and num(r.get("reading")) is not None]
    if not sieves and not hydro:
        raise CalcError("Enter at least one sieve or hydrometer reading")
    split = float(_choice(data, "split_sieve", "2.00"))
    m_total = _opt(data, "m_dry_total")
    m_fine = _opt(data, "m_hydro")
    notes: List[str] = []
    sieve_rows = []
    sieve_pts: List[Tuple[float, float]] = []
    p_split = 100.0
    if sieves:
        if m_total is None or m_total <= 0:
            raise CalcError("Dry mass of the whole sample is required")
        cum = 0.0
        cum_fine = 0.0
        for r in sieves:
            size, ret = float(r["opening"]), float(r["retained"])
            if size >= split - 1e-9 or not m_fine:
                # Coarse sieves (or every sieve when there is no separate fine specimen): whole sample.
                cum += ret
                passing = 100 - cum / m_total * 100
                if size >= split - 1e-9:
                    p_split = passing
                cum_shown = cum
            else:
                # Fine sieves on the washed fine specimen; scaled by the percentage passing the split sieve.
                cum_fine += ret
                passing = (100 - cum_fine / m_fine * 100) * p_split / 100
                cum_shown = cum_fine
            if passing < -0.01:
                raise CalcError("The retained masses exceed the dry mass of the sample")
            passing = max(passing, 0.0)
            sieve_pts.append((size, passing))
            sieve_rows.append([r.get("sieve") or "", size, ret, _r(cum_shown), _r(100 - passing), _r(passing)])
    # Hydrometer.
    hydro_rows = []
    hydro_pts: List[Tuple[float, float]] = []
    gs = _opt(data, "gs")
    if hydro:
        if gs is None or gs <= 1:
            raise CalcError("Specific gravity Gs is required for the hydrometer analysis")
        w_h = m_fine if m_fine else m_total
        if not w_h or w_h <= 0:
            raise CalcError("Dry mass of the hydrometer specimen is required")
        kind = _choice(data, "hydrometer_type", "151H")
        mode = _choice(data, "hydro_method", "astm")
        zero = _opt(data, "zero_corr", 0.0) or 0.0
        if mode == "template":
            notes.append("Template method: percent finer from the reading, effective depth from the temperature-corrected reading, viscosity at 27 °C.")
        else:
            notes.append("ASTM D422: percent finer from the corrected reading, effective depth from the reading, viscosity at the test temperature.")
        for r in sorted(hydro, key=lambda r: float(r["t_min"])):
            t = float(r["t_min"])
            if t <= 0:
                continue
            reading = float(r["reading"]) - zero
            k = num(r.get("k")) or 0.0
            corrected = reading + k
            temp = num(r.get("temp"))
            if mode == "template":
                eta, rho_w = 0.00855, 0.9968
                r_pct, r_depth = reading, corrected
            else:
                if temp is None:
                    raise CalcError("Temperature is required for each hydrometer reading")
                eta, rho_w = water_viscosity(temp), water_density(temp)
                r_pct, r_depth = corrected, reading
            if kind == "152H":
                depth = 16.3 - 0.164 * r_depth
                a = 1.65 * gs / ((gs - 1) * 2.65)
                p_sub = r_pct * a / w_h * 100
            else:
                depth = 281.29 - 265 * r_depth
                p_sub = gs / (gs - 1) * 100000 / w_h * (r_pct - 1)
            if depth <= 0:
                raise CalcError("A hydrometer reading is outside the range of the hydrometer")
            kk = math.sqrt(30 * eta / (980.7 * (gs - rho_w)))
            d = kk * math.sqrt(depth / t)
            p_total = max(0.0, p_sub * p_split / 100)
            hydro_pts.append((d, p_total))
            hydro_rows.append([t, temp, _r(reading, 4), _r(corrected, 4), _r(depth, 3), _r(kk, 5), _r(d, 5), _r(p_total)])
    curve = sorted(sieve_pts + hydro_pts)
    # Fractions (ASTM D2487 sizes): gravel > 4.75 mm, sand 4.75–0.075 mm, silt 0.075–0.002 mm, clay < 0.002 mm.
    f475 = _finer_at(curve, 4.75)
    f075 = _finer_at(curve, 0.075)
    f002 = _finer_at(curve, 0.002)
    gravel = 100 - f475 if f475 is not None else None
    sand = f475 - f075 if f475 is not None and f075 is not None else None
    clay = f002
    silt = f075 - f002 if f075 is not None and f002 is not None else None
    if f075 is not None and f002 is None and hydro_pts:
        notes.append("The hydrometer readings do not reach 0.002 mm; the clay fraction is not determined.")
    d10, d30, d60 = _size_at(curve, 10), _size_at(curve, 30), _size_at(curve, 60)
    cu = d60 / d10 if d10 and d60 else None
    cc = d30 ** 2 / (d10 * d60) if d10 and d30 and d60 else None
    ll, pi = _opt(data, "ll"), _opt(data, "pi")
    symbol = ""
    if f075 is not None and gravel is not None and sand is not None:
        symbol = uscs_symbol(f075, sand, gravel, ll, pi, cu, cc)
    values: List[Tuple[str, Any, str]] = [
        ("Gravel", _r(gravel), "%"), ("Sand", _r(sand), "%"), ("Silt", _r(silt), "%"), ("Clay", _r(clay), "%"),
        ("Fines (passing 0.075 mm)", _r(f075), "%"),
        ("D10", rnd(d10, 3), "mm"), ("D30", rnd(d30, 3), "mm"), ("D60", rnd(d60, 3), "mm"),
        ("Coefficient of uniformity Cu", _r(cu), ""), ("Coefficient of curvature Cc", _r(cc), ""),
    ]
    if symbol:
        values.append(("USCS group symbol", symbol, ""))
    elif f075 is not None and 5 <= f075 and ll is None:
        notes.append("Enter the liquid limit and plasticity index to classify the soil.")
    tables = []
    if sieve_rows:
        tables.append(table("Sieve analysis", ["Sieve", "Opening (mm)", "Mass retained (g)", "Cumulative retained (g)",
                                               "Retained (%)", "Passing (%)"], sieve_rows))
    if hydro_rows:
        tables.append(table("Hydrometer analysis", ["Time (min)", "Temperature (°C)", "Reading R", "Corrected reading",
                                                    "Effective depth L (cm)", "K", "Diameter D (mm)", "Finer than D (%)"], hydro_rows))
    top = max(d for d, _ in curve) if curve else 100.0
    bottom = min(d for d, _ in curve) if curve else 0.001
    bounds = [series(name, [(size, 0), (size, 100)], "line", dash=True)
              for name, size in (("Gravel / sand 4.75 mm", 4.75), ("Sand / silt 0.075 mm", 0.075), ("Silt / clay 0.002 mm", 0.002))
              if bottom <= size <= top]
    charts = [chart("Grain size distribution", axis("Particle size (mm)", log=True, reverse=True), axis("Percent finer (%)"),
                    series("Sieve analysis", sorted(sieve_pts)), series("Hydrometer", sorted(hydro_pts)), *bounds)]
    summary: List[Tuple[str, Any, str]] = [("Gravel", _r(gravel), "%"), ("Sand", _r(sand), "%"), ("Fines", _r(f075), "%")]
    if symbol:
        summary.append(("USCS", symbol, ""))
    method = "ASTM D6913 sieve analysis; ASTM D422 / D7928 hydrometer" if hydro else "ASTM D6913 sieve analysis"
    return result(summary, values, tables, charts, notes, method=method,
                  lab={"gravel": _r(gravel), "sand": _r(sand), "silt": _r(silt), "clay": _r(clay), "fines": _r(f075),
                       "d10": rnd(d10, 3), "d30": rnd(d30, 3), "d60": rnd(d60, 3), "cu": _r(cu), "cc": _r(cc),
                       "uscs": symbol or None})


# --------------------------------------------------------------------------- #
# 05.07 Atterberg limits
# --------------------------------------------------------------------------- #

def _plasticity_class(pi: float) -> str:
    if pi <= 0:
        return "Non-plastic"
    for limit, name in ((5, "Slightly plastic"), (10, "Low plasticity"), (20, "Medium plasticity"), (35, "High plasticity")):
        if pi <= limit:
            return name
    return "Very high plasticity"


def atterberg(data: Dict[str, Any]) -> Dict[str, Any]:
    trials = []
    for row in _rows(data, "ll_trials"):
        n = num(row.get("blows"))
        w = _row_w(row)
        if n is None or w is None:
            continue
        if n <= 0:
            raise CalcError("The number of blows must be greater than zero")
        trials.append((n, w))
    if not trials:
        raise CalcError("Enter at least one liquid limit trial")
    notes: List[str] = []
    fit = None
    if len(trials) == 1:
        # One-point method (ASTM D4318 method B), valid for 20–30 blows.
        n, w = trials[0]
        ll = w * (n / 25) ** 0.121
        notes.append("One-point liquid limit (ASTM D4318 method B); valid for 20 to 30 blows.")
        if not 20 <= n <= 30:
            notes.append("The one-point method needs 20 to 30 blows; add more trials.")
    else:
        xs = [math.log10(n) for n, _ in trials]
        a, b, r2 = linear_fit(xs, [w for _, w in trials])
        ll = a + b * math.log10(25)
        fit = (a, b, r2)
        if b >= 0:
            notes.append("The water content does not decrease with the number of blows; check the trials.")
    pl_ws = [w for w in (_row_w(r) for r in _rows(data, "pl_trials")) if w is not None]
    non_plastic = bool(data.get("non_plastic"))
    pl = None if non_plastic or not pl_ws else sum(pl_ws) / len(pl_ws)
    pi = None
    if non_plastic:
        pi = 0.0
    elif pl is not None:
        pi = ll - pl
        if pi < 0:
            notes.append("The plastic limit is higher than the liquid limit; the soil is reported as non-plastic.")
            pi, pl = 0.0, None
    pl_shown: Tuple[str, Any, str] = ("Plastic limit PL", _r(pl), "%") if pl is not None else (
        ("Plastic limit PL", "NP", "") if pi == 0 else ("Plastic limit PL", None, "%"))
    values: List[Tuple[str, Any, str]] = [("Liquid limit LL", _r(ll), "%"), pl_shown, ("Plasticity index PI", _r(pi), "%")]
    if fit is not None:
        values.append(("Flow index", _r(-fit[1]), ""))
    symbol = None
    if pi is not None:
        values.append(("Plasticity", _plasticity_class(pi), ""))
        symbol = plasticity_symbol(ll, pi)
        values.append(("Plasticity chart", symbol, ""))
        values.append(("A-line PI at this LL", _r(max(a_line(ll), 0.0)), "%"))
    wn = _opt(data, "w_natural")
    if wn is not None and pi:
        values.append(("Liquidity index LI", _r((wn - (pl or 0)) / pi), ""))
        values.append(("Consistency index CI", _r((ll - wn) / pi), ""))
    tbl_rows = [["LL", i + 1, n, _r(w)] for i, (n, w) in enumerate(trials)] + [["PL", i + 1, None, _r(w)] for i, w in enumerate(pl_ws)]
    tables = [table("Trials", ["Test", "Trial", "Blows N", "Water content w (%)"], tbl_rows)]
    charts = []
    ns = [n for n, _ in trials]
    flow = [series("Trials", [(n, w) for n, w in trials], "points")]
    if fit is not None:
        lo, hi = min(ns + [10.0]), max(ns + [50.0])
        flow.append(series("Fitted line", [(x, fit[0] + fit[1] * math.log10(x)) for x in (lo, 25, hi)], "line"))
    flow.append(series("LL at 25 blows", [(25, ll)], "points"))
    charts.append(chart("Flow curve", axis("Number of blows N", log=True), axis("Water content w (%)"), *flow))
    if pi is not None:
        top = max(100.0, ll + 10)
        charts.append(chart("Plasticity chart", axis("Liquid limit LL (%)"), axis("Plasticity index PI (%)"),
                            series("A-line", [(25.5, 4), (top, a_line(top))], "line"),
                            series("U-line", [(16, 7.2), (min(top, 74.7), 0.9 * (min(top, 74.7) - 8))], "line", dash=True),
                            series("CL-ML zone", [(12.4, 4), (25.5, 4), (29.6, 7), (15.8, 7), (12.4, 4)], "line", dash=True),
                            series("LL = 50", [(50, 0), (50, 60)], "line", dash=True),
                            series("Sample", [(ll, pi)], "points")))
    summary: List[Tuple[str, Any, str]] = [("LL", _r(ll), "%"), ("PL", pl_shown[1], pl_shown[2]), ("PI", _r(pi), "%")]
    if symbol:
        summary.append(("Chart", symbol, ""))
    return result(summary, values, tables, charts, notes,
                  method="ASTM D4318 multipoint liquid limit (Casagrande cup) and plastic limit (thread rolling)",
                  lab={"ll": _r(ll), "pl": _r(pl), "pi": _r(pi)})


# --------------------------------------------------------------------------- #
# 05.08 Compaction (Proctor)
# --------------------------------------------------------------------------- #

def _proctor_points(rows: List[Dict[str, Any]], volume: Optional[float]) -> List[Tuple[float, float, float]]:
    """(w %, ρm, ρd) per compaction point."""
    out = []
    for row in rows:
        ms, mm = num(row.get("m_mold_soil")), num(row.get("m_mold"))
        if ms is None or mm is None:
            continue
        v = num(row.get("volume")) or volume
        if not v or v <= 0:
            raise CalcError("Mold volume is required")
        ws = [w for w in (_row_w(row), _row_w(row, "_2")) if w is not None]
        if not ws:
            raise CalcError("Enter the water content of each compaction point")
        w = sum(ws) / len(ws)
        rho_m = (ms - mm) / v
        if rho_m <= 0:
            raise CalcError("The mold with soil must weigh more than the empty mold")
        out.append((w, rho_m, rho_m / (1 + w / 100)))
    return sorted(out)


def _peak(points: List[Tuple[float, float, float]], how: str) -> Dict[str, Any]:
    """Maximum dry density and optimum water content from the compaction points."""
    ws = [p[0] for p in points]
    ds = [p[2] for p in points]
    if len(points) < 3:
        raise CalcError("At least three compaction points are needed")
    if max(ws) - min(ws) <= 0:
        raise CalcError("The compaction points must have different water contents")
    i_max = ds.index(max(ds))
    out: Dict[str, Any] = {"curve": None, "reached": 0 < i_max < len(points) - 1}
    if how == "poly":
        f = polyfit(ws, ds, 3 if len(points) >= 5 else 2)
        grid = [ws[0] + (ws[-1] - ws[0]) * i / 1000 for i in range(1001)]
        vals = [f(w) for w in grid]
        j = vals.index(max(vals))
        if 0 < j < len(grid) - 1:
            out.update(omc=grid[j], mdd=vals[j], curve=[(w, f(w)) for w in grid[::20]] + [(grid[-1], vals[-1])])
            return out
    # Parabola through the highest point and its neighbours.
    i = min(max(i_max, 1), len(points) - 2)
    f2 = polyfit(ws[i - 1:i + 2], ds[i - 1:i + 2], 2)
    lo, hi = ws[i - 1], ws[i + 1]
    grid = [lo + (hi - lo) * k / 500 for k in range(501)]
    vals = [f2(w) for w in grid]
    j = vals.index(max(vals))
    out.update(omc=grid[j], mdd=vals[j], curve=[(w, f2(w)) for w in grid[::25]] + [(grid[-1], vals[-1])])
    return out


def _proctor(data: Dict[str, Any], rows_key: str, volume_key: str) -> Optional[Dict[str, Any]]:
    rows = _rows(data, rows_key)
    if not rows:
        return None
    points = _proctor_points(rows, _opt(data, volume_key))
    if not points:
        return None
    peak = _peak(points, _choice(data, "curve_fit", "poly"))
    notes = []
    if not peak["reached"]:
        notes.append("The highest dry density is at the end of the test points; add points on the other side of the optimum.")
    mdd, omc = peak["mdd"], peak["omc"]
    manual_mdd, manual_omc = _opt(data, "mdd_manual"), _opt(data, "omc_manual")
    if manual_mdd is not None or manual_omc is not None:
        notes.append("Maximum dry density and optimum water content were entered manually.")
        mdd = manual_mdd if manual_mdd is not None else mdd
        omc = manual_omc if manual_omc is not None else omc
    gs = _opt(data, "gs")
    ws = [p[0] for p in points]
    zav = []
    if gs is not None and gs > 1:
        lo, hi = min(ws) - 1, max(ws) + 1
        zav = [(w, gs / (1 + gs * w / 100)) for w in [lo + (hi - lo) * k / 20 for k in range(21)]]
    ch = chart("Compaction curve", axis("Water content w (%)"), axis("Dry density ρd (g/cm³)"),
               series("Test points", [(p[0], p[2]) for p in points], "points"),
               series("Fitted curve", peak["curve"] or [], "line"),
               series("Zero air voids (Sr = 100 %)", zav, "line", dash=True),
               series("OMC / MDD", [(omc, min(p[2] for p in points)), (omc, mdd), (min(ws), mdd)], "line", dash=True))
    tbl = table("Compaction points", ["Point", "Water content w (%)", "Bulk density ρ (g/cm³)", "Dry density ρd (g/cm³)",
                                      "Zero air voids ρd (g/cm³)"],
                [[i + 1, _r(w), _r(rm, 3), _r(rd, 3), _r(gs / (1 + gs * w / 100), 3) if gs and gs > 1 else None]
                 for i, (w, rm, rd) in enumerate(points)])
    return {"mdd": mdd, "omc": omc, "chart": ch, "table": tbl, "notes": notes, "points": points}


def compaction(data: Dict[str, Any]) -> Dict[str, Any]:
    out = _proctor(data, "points", "mold_volume")
    if out is None:
        raise CalcError("Enter at least three compaction points")
    mdd, omc = out["mdd"], out["omc"]
    values: List[Tuple[str, Any, str]] = [
        ("Maximum dry density MDD", _r(mdd, 3), "g/cm³"), ("Optimum water content OMC", _r(omc), "%"),
        ("95 % of MDD", _r(0.95 * mdd, 3), "g/cm³"), ("Maximum dry unit weight", _r(mdd * GAMMA_W), "kN/m³"),
    ]
    notes = out["notes"] + ["MDD and OMC from a polynomial fit through the points (cubic for five or more points)."
                            if _choice(data, "curve_fit", "poly") == "poly"
                            else "MDD and OMC from a parabola through the highest point and its neighbours."]
    std = "ASTM D1557 modified Proctor" if _choice(data, "method", "standard") == "modified" else "ASTM D698 standard Proctor"
    return result([("MDD", _r(mdd, 3), "g/cm³"), ("OMC", _r(omc), "%")], values, [out["table"]], [out["chart"]], notes,
                  method=std, lab={"mdd": _r(mdd, 3), "omc": _r(omc)})


# --------------------------------------------------------------------------- #
# 05.09 CBR (laboratory)
# --------------------------------------------------------------------------- #

STD_STRESS = {2.54: 6.894757, 5.08: 10.342136}  # MPa: 1000 and 1500 psi on the 3 in² piston


def _origin_shift(pts: List[Tuple[float, float]]) -> float:
    """Penetration (mm) where the tangent at the steepest part of an initially concave-up curve meets zero load."""
    early = [p for p in pts if p[0] <= 7.62 + 1e-9]
    if len(early) < 3:
        return 0.0
    slopes = [(early[i + 1][1] - early[i][1]) / (early[i + 1][0] - early[i][0]) for i in range(len(early) - 1)
              if early[i + 1][0] > early[i][0]]
    if not slopes:
        return 0.0
    i = slopes.index(max(slopes))
    # Only a clearly concave-up start is corrected (steepest slope more than 10 % above the first one).
    if i == 0 or slopes[i] <= 1.1 * max(slopes[0], 0.0):
        return 0.0
    x0, y0 = early[i]
    return max(0.0, x0 - y0 / slopes[i])


def cbr_lab(data: Dict[str, Any]) -> Dict[str, Any]:
    newton = _ring_newton(data, 3.38, "lbf")
    area = (_opt(data, "piston_area", 19.3548) or 19.3548) * 100  # mm²
    pen_mm = IN_MM if _choice(data, "pen_unit", "in") == "in" else 1.0
    rule = _choice(data, "cbr_rule", "astm")
    soaked = _choice(data, "soaked", "soaked") == "soaked"
    height = _opt(data, "height", 116.43) or 116.43
    swell_factor = _opt(data, "swell_factor", 0.0254) or 0.0254
    specimens = [r for r in _rows(data, "specimens")][:3]
    pen_rows = sorted([r for r in _rows(data, "penetration") if num(r.get("pen")) is not None], key=lambda r: float(r["pen"]))
    if not pen_rows:
        raise CalcError("Enter the penetration readings")
    notes: List[str] = []
    rule_note = {
        "astm": "CBR is the 2.54 mm value; when the 5.08 mm value is higher the standard asks for a retest and, if confirmed, the 5.08 mm value is used.",
        "average": "CBR is the average of the 2.54 mm and 5.08 mm values (template rule).",
        "min": "CBR is the lower of the 2.54 mm and 5.08 mm values.",
    }
    notes.append(rule_note.get(rule, rule_note["astm"]))
    results: List[Dict[str, Any]] = []
    curves = []
    for i in range(3):
        col = f"load_{i + 1}"
        pts = [(float(r["pen"]) * pen_mm, float(r[col]) * newton / area) for r in pen_rows if num(r.get(col)) is not None]
        if len(pts) < 2:
            continue
        spec = specimens[i] if i < len(specimens) else {}
        manual = num(spec.get("zero_corr"))
        shift = manual * pen_mm if manual is not None else _origin_shift(pts)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        cbrs = {}
        for d, std in STD_STRESS.items():
            s = interpolate(d + shift, xs, ys)
            cbrs[d] = s / std * 100 if s is not None else None
        c1, c2 = cbrs[2.54], cbrs[5.08]
        if c1 is None:
            raise CalcError("The penetration readings must reach 2.54 mm")
        if c2 is None:
            value = c1
        elif rule == "average":
            value = (c1 + c2) / 2
        elif rule == "min":
            value = min(c1, c2)
        else:
            value = c2 if c2 > c1 else c1
        w = _row_w(spec) if spec else None
        rho_d = None
        ms, mm, vol = num(spec.get("m_mold_soil")), num(spec.get("m_mold")), num(spec.get("volume"))
        if ms is not None and mm is not None and vol:
            rho_m = (ms - mm) / vol
            rho_d = rho_m / (1 + (w or 0) / 100)
        results.append({"n": i + 1, "blows": num(spec.get("blows")), "w": w, "rho_d": rho_d, "c1": c1, "c2": c2,
                        "cbr": value, "shift": shift, "swell": None, "higher2": c2 is not None and c2 > c1})
        curves.append(series(f"Specimen {i + 1}", pts, "both"))
    if not results:
        raise CalcError("Enter the load dial readings of at least one specimen")
    if rule == "astm" and any(r["higher2"] for r in results):
        notes.append("The 5.08 mm value is higher than the 2.54 mm value; confirm with a retest.")
    if any(r["shift"] > 0 for r in results):
        notes.append("The origin of a concave-up load curve was corrected with the tangent at its steepest part.")
    # Swell during soaking: dial change over the initial specimen height.
    swell_rows = sorted([r for r in _rows(data, "swell") if num(r.get("day")) is not None], key=lambda r: float(r["day"]))
    swell_series = []
    if soaked and swell_rows:
        for res in results:
            col = f"swell_{res['n']}"
            readings = [(float(r["day"]), float(r[col])) for r in swell_rows if num(r.get(col)) is not None]
            if not readings:
                continue
            base = readings[0][1] if readings[0][0] == 0 else 0.0
            pts = [(day, (dial - base) * swell_factor / height * 100) for day, dial in readings]
            if readings[0][0] != 0:
                pts.insert(0, (0.0, 0.0))
            res["swell"] = pts[-1][1]
            swell_series.append(series(f"Specimen {res['n']}", pts, "both"))
        if swell_rows and float(swell_rows[0]["day"]) != 0:
            notes.append("There is no reading at day 0; the swell is measured from a zero dial reading.")
    # Compaction and design CBR at the target dry density.
    proctor = _proctor(data, "compaction", "compaction_volume")
    mdd = proctor["mdd"] if proctor else _opt(data, "mdd_manual")
    omc = proctor["omc"] if proctor else _opt(data, "omc_manual")
    pct = float(_choice(data, "design_pct", "95"))
    design = design_swell = target = None
    dens = sorted([r for r in results if r["rho_d"] is not None], key=lambda r: r["rho_d"])
    if mdd is not None and dens:
        target = mdd * pct / 100
        if len(dens) >= 2:
            design = interpolate(target, [r["rho_d"] for r in dens], [r["cbr"] for r in dens])
            sw = [r for r in dens if r["swell"] is not None]
            if len(sw) == len(dens):
                design_swell = interpolate(target, [r["rho_d"] for r in dens], [r["swell"] for r in dens])
        if design is None and len(dens) >= 2:
            notes.append("The target dry density is outside the range of the specimens; the design CBR is not interpolated.")
    if design is not None:
        cbr_value, swell_value = design, design_swell
    else:
        main = dens[-1] if dens else results[-1]
        cbr_value, swell_value = main["cbr"], main["swell"]
        if len(results) > 1:
            notes.append("CBR is reported for the densest specimen.")
    values: List[Tuple[str, Any, str]] = []
    if design is not None:
        values.append(("Design CBR at the target density", _r(design, 1), "%"))
        values.append(("Target dry density", _r(target, 3), "g/cm³"))
    else:
        values.append(("CBR", _r(cbr_value, 1), "%"))
    if swell_value is not None:
        values.append(("Swell", _r(swell_value), "%"))
    if mdd is not None:
        values.append(("Maximum dry density MDD", _r(mdd, 3), "g/cm³"))
    if omc is not None:
        values.append(("Optimum water content OMC", _r(omc), "%"))
    for cls_limit, name in ((3, "Very poor"), (7, "Poor"), (20, "Fair"), (50, "Good")):
        if cbr_value < cls_limit:
            values.append(("Subgrade rating", name, ""))
            break
    else:
        values.append(("Subgrade rating", "Very good", ""))
    tables = [table("Specimens", ["Specimen", "Blows per layer", "Water content w (%)", "Dry density ρd (g/cm³)",
                                  "CBR 2.54 mm (%)", "CBR 5.08 mm (%)", "CBR (%)", "Swell (%)", "Origin correction (mm)"],
                    [[r["n"], r["blows"], _r(r["w"]), _r(r["rho_d"], 3), _r(r["c1"]), _r(r["c2"]), _r(r["cbr"]),
                      _r(r["swell"]), _r(r["shift"], 2)] for r in results])]
    charts = [chart("Load–penetration curves", axis("Penetration (mm)"), axis("Piston stress (MPa)"), *curves)]
    if dens:
        cbr_dens = [series("Specimens", [(r["rho_d"], r["cbr"]) for r in dens], "both")]
        if target is not None:
            top = max(r["cbr"] for r in dens)
            cbr_dens.append(series("Target dry density", [(target, 0), (target, top)], "line", dash=True))
        charts.append(chart("CBR versus dry density", axis("Dry density ρd (g/cm³)"), axis("CBR (%)"), *cbr_dens))
    if swell_series:
        charts.append(chart("Swell during soaking", axis("Time (days)"), axis("Swell (%)"), *swell_series))
    if proctor:
        charts.append(proctor["chart"])
        tables.append(proctor["table"])
        notes.extend(proctor["notes"])
    summary = [("CBR", _r(cbr_value, 1), "%"), ("Swell", _r(swell_value), "%")]
    return result(summary, values, tables, charts, notes, method="ASTM D1883 / SNI 1744:2012 laboratory CBR",
                  lab={"cbr": _r(cbr_value, 1), "swell": _r(swell_value), "mdd": _r(mdd, 3), "omc": _r(omc),
                       "condition": "soaked" if soaked else "unsoaked"})


# --------------------------------------------------------------------------- #
# Compression tests: UCS, UU and CU triaxial
# --------------------------------------------------------------------------- #

def _axial_mm(data: Dict[str, Any], default: str) -> float:
    return 0.01 if _choice(data, "axial_unit", default) == "0.01mm" else 1.0


def _stress_strain(readings: List[Tuple[float, float]], a0: float, h0: float, newton: float) -> List[Tuple[float, float]]:
    """(strain %, axial stress kPa) with the area corrected for barrelling: A = A0 / (1 − ε).
    readings: (deformation mm, load dial); a0 cm², h0 mm."""
    out = []
    for dl, dial in readings:
        eps = dl / h0
        if eps >= 1:
            raise CalcError("The deformation must be smaller than the specimen height")
        area = a0 / (1 - eps)
        out.append((eps * 100, dial * newton / area * 10))  # N/cm² → kPa
    return out


def _failure(curve: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Peak stress within 15 % strain (the stress at 15 % when there is no peak); returns (strain %, stress)."""
    usable = [p for p in curve if p[0] <= 15 + 1e-9] or curve[:1]
    best = usable[0]
    for p in usable:
        if p[1] > best[1]:
            best = p
    return best


def ucs(data: Dict[str, Any]) -> Dict[str, Any]:
    d = _need(data, "diameter", "Diameter")
    h = _need(data, "height", "Height")
    newton = _ring_newton(data, 0.35, "kgf")
    unit = _axial_mm(data, "mm")
    a0 = math.pi * d ** 2 / 4  # cm²
    readings = sorted([r for r in _rows(data, "readings") if num(r.get("deformation")) is not None], key=lambda r: float(r["deformation"]))
    curves: Dict[str, List[Tuple[float, float]]] = {}
    for key in ("dial_undisturbed", "dial_remolded"):
        pts = [(float(r["deformation"]) * unit, float(r[key])) for r in readings if num(r.get(key)) is not None]
        if pts:
            curves[key] = _stress_strain(pts, a0, h * 10, newton)
    if "dial_undisturbed" not in curves:
        raise CalcError("Enter the load dial readings of the undisturbed specimen")
    eps_f, qu = _failure(curves["dial_undisturbed"])
    if qu <= 0:
        raise CalcError("The load readings give no strength")
    qr = _failure(curves["dial_remolded"])[1] if "dial_remolded" in curves else None
    st = qu / qr if qr else None
    w = water_content(_opt(data, "m_wet"), _opt(data, "m_dry"), _opt(data, "m_tare"))
    mass = _opt(data, "mass")
    vol = a0 * h
    rho_m = mass / vol if mass else None
    rho_d = rho_m / (1 + w / 100) if rho_m is not None and w is not None else None
    values: List[Tuple[str, Any, str]] = [
        ("Unconfined compressive strength qu", _r(qu, 1), "kPa"), ("qu", _r(qu / KPA_PER_KGCM2, 3), "kg/cm²"),
        ("Strain at failure", _r(eps_f, 1), "%"), ("Undrained shear strength su = qu/2", _r(qu / 2, 1), "kPa"),
        ("Consistency", _consistency(qu), ""),
    ]
    if qr:
        values += [("Remolded strength qu,r", _r(qr, 1), "kPa"), ("Sensitivity St", _r(st), "")]
    if w is not None:
        values.append(("Water content w", _r(w), "%"))
    if rho_m is not None:
        values += [("Bulk density ρ", _r(rho_m, 3), "g/cm³"), ("Dry density ρd", _r(rho_d, 3), "g/cm³")]
    values.append(("Initial area A0", _r(a0, 3), "cm²"))
    rem = dict(curves.get("dial_remolded", []))
    tbl = table("Stress–strain", ["Strain (%)", "Stress, undisturbed (kPa)", "Stress, remolded (kPa)"],
                [[_r(e, 2), _r(s, 1), _r(rem.get(e), 1)] for e, s in curves["dial_undisturbed"]]
                + [[_r(e, 2), None, _r(s, 1)] for e, s in curves.get("dial_remolded", [])
                   if e not in dict(curves["dial_undisturbed"])])
    sers = [series("Undisturbed", curves["dial_undisturbed"], "line"), series("Peak", [(eps_f, qu)], "points")]
    if "dial_remolded" in curves:
        sers.append(series("Remolded", curves["dial_remolded"], "line", dash=True))
    charts = [chart("Stress–strain curve", axis("Axial strain (%)"), axis("Axial stress (kPa)"), *sers),
              chart("Mohr circle", axis("Normal stress σ (kPa)"), axis("Shear stress τ (kPa)"),
                    _mohr_series("Undisturbed", 0.0, qu), series("su", [(0, qu / 2), (qu, qu / 2)], "line", dash=True))]
    notes = ["Area corrected for barrelling: A = A0 / (1 − ε). Failure is the peak stress, or the stress at 15 % strain."]
    lab = {"qu": _r(qu, 1), "strain": _r(eps_f, 1), "su": _r(qu / 2, 1), "st": _r(st)}
    return result([("qu", _r(qu, 1), "kPa"), ("ε", _r(eps_f, 1), "%"), ("St", _r(st), "")], values, [tbl], charts, notes,
                  method="ASTM D2166 / SNI 3638:2012 unconfined compression", lab=lab)


def _specimen_readings(data: Dict[str, Any], col: str, unit: float) -> List[Tuple[float, float]]:
    rows = sorted([r for r in _rows(data, "readings") if num(r.get("axial")) is not None], key=lambda r: float(r["axial"]))
    return [(float(r["axial"]) * unit, float(r[col])) for r in rows if num(r.get(col)) is not None]


def triaxial(data: Dict[str, Any]) -> Dict[str, Any]:
    """UU triaxial (ASTM D2850)."""
    newton = _ring_newton(data, 0.35, "kgf")
    unit = _axial_mm(data, "0.01mm")
    sunit = _choice(data, "stress_unit", "kgcm2")
    specs = _rows(data, "specimens")[:3]
    results: List[Dict[str, Any]] = []
    curves = []
    for i, spec in enumerate(specs):
        readings = _specimen_readings(data, f"load_{i + 1}", unit)
        s3_in = num(spec.get("cell_pressure"))
        if not readings:
            continue
        if s3_in is None:
            raise CalcError("Cell pressure is required")
        d = num(spec.get("diameter")) or _opt(data, "diameter")
        h = num(spec.get("height")) or _opt(data, "height")
        if not d or not h or d <= 0 or h <= 0:
            raise CalcError("Specimen height and diameter are required")
        a0 = math.pi * d ** 2 / 4
        curve = _stress_strain(readings, a0, h * 10, newton)
        eps_f, dev = _failure(curve)
        s3 = _to_kpa(s3_in, sunit)
        w = water_content(num(spec.get("m_wet")), num(spec.get("m_dry")), 0.0)
        vol = a0 * h
        m_wet = num(spec.get("m_wet"))
        rho_m = m_wet / vol if m_wet else None
        rho_d = rho_m / (1 + w / 100) if rho_m is not None and w is not None else None
        results.append({"n": i + 1, "s3": s3, "dev": dev, "eps": eps_f, "w": w, "rho_m": rho_m, "rho_d": rho_d})
        curves.append(series(f"Specimen {i + 1}", curve, "line"))
    if not results:
        raise CalcError("Enter the readings of at least one specimen")
    fit = strength_fit([(r["s3"] + r["dev"] / 2, r["dev"] / 2) for r in results])
    su = sum(r["dev"] / 2 for r in results) / len(results)
    c, phi = fit["c"], fit["phi"]
    values: List[Tuple[str, Any, str]] = [
        ("Undrained shear strength cu (mean)", _r(su, 1), "kPa"), ("Cohesion c", _r(c, 1), "kPa"),
        ("Friction angle φ", _r(phi, 1), "°"), ("Coefficient of determination R²", _r(fit["r2"], 3), ""),
        ("Consistency", _consistency(2 * su), ""),
    ]
    tbl = table("Specimens", ["Specimen", "σ3 (kPa)", "Deviator stress at failure (kPa)", "Strain at failure (%)",
                              "σ1 (kPa)", "su (kPa)", "Water content w (%)", "Bulk density ρ (g/cm³)", "Dry density ρd (g/cm³)"],
                [[r["n"], _r(r["s3"], 1), _r(r["dev"], 1), _r(r["eps"], 1), _r(r["s3"] + r["dev"], 1), _r(r["dev"] / 2, 1),
                  _r(r["w"]), _r(r["rho_m"], 3), _r(r["rho_d"], 3)] for r in results])
    charts = [chart("Deviator stress versus strain", axis("Axial strain (%)"), axis("Deviator stress (kPa)"), *curves),
              _mohr_chart("Mohr circles", [(r["s3"], r["s3"] + r["dev"]) for r in results], c, phi),
              _pq_chart("p–q diagram", [(r["s3"] + r["dev"] / 2, r["dev"] / 2) for r in results], fit, "p (kPa)")]
    notes = ["c and φ from a least-squares line through the failure points in p–q space: φ = asin(tan α), c = a / cos φ.",
             "For saturated clay the undrained strength is cu with φu = 0."] + _fit_notes(fit)
    return result([("cu", _r(su, 1), "kPa"), ("c", _r(c, 1), "kPa"), ("φ", _r(phi, 1), "°")], values, [tbl], charts, notes,
                  method="ASTM D2850 / SNI 4813:2015 unconsolidated-undrained triaxial",
                  lab={"test": "UU", "c": _r(c, 1), "phi": _r(phi, 1), "cu": _r(su, 1)})


def _mohr_chart(title: str, circles: List[Tuple[float, float]], c: float, phi: float, label: str = "σ") -> Dict[str, Any]:
    top = max(s1 for _, s1 in circles) if circles else 1.0
    sers = [_mohr_series(f"Specimen {i + 1}", s3, s1) for i, (s3, s1) in enumerate(circles)]
    sers.append(series("Failure envelope", [(0, c), (top, c + top * math.tan(math.radians(phi)))], "line", dash=True))
    return chart(title, axis(f"Normal stress {label} (kPa)"), axis("Shear stress τ (kPa)"), *sers)


def _pq_chart(title: str, pts: List[Tuple[float, float]], fit: Dict[str, Any], xlabel: str) -> Dict[str, Any]:
    phi = math.radians(fit["phi"])
    a = fit["c"] * math.cos(phi)
    top = max(p for p, _ in pts) * 1.2 if pts else 1.0
    return chart(title, axis(xlabel), axis("q (kPa)"), series("Failure points", pts, "points"),
                 series("Kf line", [(0, a), (top, a + top * math.sin(phi))], "line", dash=True))


def triaxial_cu(data: Dict[str, Any]) -> Dict[str, Any]:
    """CU triaxial with pore pressure measurement (ASTM D4767)."""
    newton = _ring_newton(data, None, "kgf")
    unit = _axial_mm(data, "0.01mm")
    sunit = _choice(data, "stress_unit", "kgcm2")
    by_ratio = _choice(data, "failure", "max_dev") == "max_ratio"
    mem_e, mem_t = _opt(data, "membrane_e"), _opt(data, "membrane_t")
    specs = _rows(data, "specimens")[:3]
    results: List[Dict[str, Any]] = []
    dev_curves, du_curves, ratio_curves, paths = [], [], [], []
    notes: List[str] = []
    for i, spec in enumerate(specs):
        rows = sorted([r for r in _rows(data, "readings") if num(r.get("axial")) is not None and num(r.get(f"load_{i + 1}")) is not None],
                      key=lambda r: float(r["axial"]))
        if not rows:
            continue
        cell, back = num(spec.get("cell_pressure")), num(spec.get("back_pressure"))
        if cell is None:
            raise CalcError("Cell pressure is required")
        d = num(spec.get("diameter")) or _opt(data, "diameter")
        h = num(spec.get("height")) or _opt(data, "height")
        if not d or not h or d <= 0 or h <= 0:
            raise CalcError("Specimen height and diameter are required")
        cell_k = _to_kpa(cell, sunit)
        back_k = _to_kpa(back, sunit) if back is not None else None
        a0, v0 = math.pi * d ** 2 / 4, math.pi * d ** 2 / 4 * h
        dv = num(spec.get("dv_consolidation")) or 0.0
        ev = dv / v0
        lc = h * 10 * (1 - ev / 3)  # mm, consolidated length
        ac = a0 * (1 - 2 * ev / 3)  # cm², consolidated area
        dc = math.sqrt(4 * ac / math.pi) * 10  # mm
        u0 = None
        pts: List[Dict[str, Any]] = []
        for r in rows:
            eps = float(r["axial"]) * unit / lc
            if eps >= 1:
                raise CalcError("The deformation must be smaller than the specimen height")
            area = ac / (1 - eps)
            dev = float(r[f"load_{i + 1}"]) * newton / area * 10
            if mem_e and mem_t:
                dev -= 4 * mem_e * mem_t * eps / dc  # membrane correction (kPa)
            u_in = num(r.get(f"u_{i + 1}"))
            u = _to_kpa(u_in, sunit) if u_in is not None else None
            if u is not None and u0 is None:
                u0 = u
            pts.append({"eps": eps * 100, "dev": dev, "u": u})
        if all(p["u"] is None for p in pts):
            raise CalcError("Enter the pore pressure readings")
        assert u0 is not None
        for p in pts:
            u_k: float = p["u"] if p["u"] is not None else u0
            p["s3e"] = cell_k - u_k
            p["s1e"] = p["s3e"] + p["dev"]
            p["du"] = u_k - u0
            p["ratio"] = p["s1e"] / p["s3e"] if p["s3e"] > 0 else None
        usable = [p for p in pts if p["eps"] <= 15 + 1e-9] or pts[:1]
        if by_ratio:
            cand = [p for p in usable if p["ratio"] is not None and p["dev"] > 0]
            fail = max(cand, key=lambda p: p["ratio"]) if cand else max(usable, key=lambda p: p["dev"])
        else:
            fail = max(usable, key=lambda p: p["dev"])
        s3_total = cell_k - back_k if back_k is not None else None
        w0 = water_content(num(spec.get("m_wet_before")), num(spec.get("m_dry")), 0.0)
        wf = water_content(num(spec.get("m_wet_after")), num(spec.get("m_dry")), 0.0)
        b = num(spec.get("b_value"))
        if b is not None and b < 0.95:
            notes.append("A B-value is below 0.95; the specimen may not be fully saturated.")
        results.append({"n": i + 1, "cell": cell_k, "back": back_k, "s3t": s3_total, "fail": fail, "w0": w0, "wf": wf,
                        "b": b, "a": fail["du"] / fail["dev"] if fail["dev"] else None})
        dev_curves.append(series(f"Specimen {i + 1}", [(p["eps"], p["dev"]) for p in pts], "line"))
        du_curves.append(series(f"Specimen {i + 1}", [(p["eps"], p["du"]) for p in pts], "line"))
        ratio_curves.append(series(f"Specimen {i + 1}", [(p["eps"], p["ratio"]) for p in pts if p["ratio"] is not None], "line"))
        paths.append(series(f"Specimen {i + 1}", [((p["s1e"] + p["s3e"]) / 2, p["dev"] / 2) for p in pts], "line"))
    if not results:
        raise CalcError("Enter the readings of at least one specimen")
    eff_pts = [((r["fail"]["s1e"] + r["fail"]["s3e"]) / 2, r["fail"]["dev"] / 2) for r in results]
    eff = strength_fit(eff_pts)
    tot = None
    if all(r["s3t"] is not None for r in results):
        tot = strength_fit([(r["s3t"] + r["fail"]["dev"] / 2, r["fail"]["dev"] / 2) for r in results])
    values: List[Tuple[str, Any, str]] = [
        ("Effective cohesion c'", _r(eff["c"], 1), "kPa"), ("Effective friction angle φ'", _r(eff["phi"], 1), "°")]
    if tot is not None:
        values += [("Total cohesion c", _r(tot["c"], 1), "kPa"), ("Total friction angle φ", _r(tot["phi"], 1), "°")]
    tbl = table("Failure", ["Specimen", "Cell pressure (kPa)", "Back pressure (kPa)", "Strain at failure (%)",
                            "Deviator stress (kPa)", "σ3' (kPa)", "σ1' (kPa)", "Δu (kPa)", "Skempton A", "B-value",
                            "Initial water content (%)", "Final water content (%)"],
                [[r["n"], _r(r["cell"], 1), _r(r["back"], 1), _r(r["fail"]["eps"], 1), _r(r["fail"]["dev"], 1),
                  _r(r["fail"]["s3e"], 1), _r(r["fail"]["s1e"], 1), _r(r["fail"]["du"], 1), _r(r["a"], 3), r["b"],
                  _r(r["w0"]), _r(r["wf"])] for r in results])
    charts = [chart("Deviator stress versus strain", axis("Axial strain (%)"), axis("Deviator stress (kPa)"), *dev_curves),
              chart("Excess pore pressure versus strain", axis("Axial strain (%)"), axis("Δu (kPa)"), *du_curves),
              chart("Effective stress ratio versus strain", axis("Axial strain (%)"), axis("σ1'/σ3'"), *ratio_curves),
              _mohr_chart("Mohr circles (effective)", [(r["fail"]["s3e"], r["fail"]["s1e"]) for r in results], eff["c"], eff["phi"], "σ'")]
    pq = _pq_chart("Effective stress paths", eff_pts, eff, "p' (kPa)")
    pq["series"] = [s for s in paths if s["points"]] + pq["series"]
    charts.append(pq)
    if tot is not None:
        charts.append(_mohr_chart("Mohr circles (total)", [(r["s3t"], r["s3t"] + r["fail"]["dev"]) for r in results], tot["c"], tot["phi"]))
    notes += ["Consolidated dimensions: L = L0 (1 − εv/3), A = A0 (1 − 2εv/3); area corrected during shear: A = Ac / (1 − ε).",
              "Effective stresses use the measured pore pressure; total stresses use the cell pressure minus the back pressure.",
              "c and φ from a least-squares line through the failure points in p–q space: φ = asin(tan α), c = a / cos φ."]
    notes += _fit_notes(eff)
    if mem_e and mem_t:
        notes.append("The deviator stress is corrected for the membrane.")
    summary = [("c'", _r(eff["c"], 1), "kPa"), ("φ'", _r(eff["phi"], 1), "°")]
    if tot is not None:
        summary += [("c", _r(tot["c"], 1), "kPa"), ("φ", _r(tot["phi"], 1), "°")]
    return result(summary, values, [tbl], charts, notes, method="ASTM D4767 consolidated-undrained triaxial with pore pressure",
                  lab={"c": _r(tot["c"], 1) if tot else None, "phi": _r(tot["phi"], 1) if tot else None,
                       "c_eff": _r(eff["c"], 1), "phi_eff": _r(eff["phi"], 1)})


# --------------------------------------------------------------------------- #
# 05.13 Direct shear
# --------------------------------------------------------------------------- #

def _shear_fit(points: List[Tuple[float, float]]) -> Dict[str, Any]:
    """τ = c + σ tan φ by least squares; negative intercept → through the origin."""
    sig = [s for s, _ in points]
    tau = [t for _, t in points]
    if len(points) < 2 or max(sig) - min(sig) <= 1e-9:
        raise CalcError("At least two specimens with different normal stresses are needed")
    a, b, r2 = linear_fit(sig, tau)
    if b <= 0:
        return {"c": sum(tau) / len(tau), "phi": 0.0, "r2": r2, "case": "flat"}
    if a < 0:
        slope = sum(s * t for s, t in points) / sum(s * s for s in sig)
        return {"c": 0.0, "phi": math.degrees(math.atan(slope)), "r2": r2, "case": "origin"}
    return {"c": a, "phi": math.degrees(math.atan(b)), "r2": r2, "case": "fit"}


def direct_shear(data: Dict[str, Any]) -> Dict[str, Any]:
    newton = _ring_newton(data, 0.12, "kgf")
    sunit = _choice(data, "stress_unit", "kgcm2")
    template = _choice(data, "conversion", "standard") == "template"
    gs = _opt(data, "gs")
    specs = _rows(data, "specimens")[:MAX_SPECIMENS]
    rows = sorted([r for r in _rows(data, "readings") if num(r.get("displacement")) is not None],
                  key=lambda r: float(r["displacement"]))
    results: List[Dict[str, Any]] = []
    curves = []
    for i, spec in enumerate(specs):
        col = f"dial_{i + 1}"
        readings = [(float(r["displacement"]), float(r[col])) for r in rows if num(r.get(col)) is not None]
        if not readings:
            continue
        sn = num(spec.get("normal_stress"))
        if sn is None:
            raise CalcError("Normal stress is required")
        area = num(spec.get("area")) or 28.27
        if area <= 0:
            raise CalcError("The shear box area must be greater than zero")
        if template and sunit != "kpa":
            sn_kpa = sn * 98.1
        else:
            sn_kpa = _to_kpa(sn, sunit)
        factor = 10 * (102 / KPA_PER_KGCM2 if template else 1.0)  # N/cm² → kPa (template: ×102 per kg/cm²)
        pts = [(x, dial * newton / area * factor) for x, dial in readings]
        peak = max(pts, key=lambda p: p[1])
        resid = pts[-1]
        w = _row_w(spec)
        vol = num(spec.get("volume"))
        m_wet, tare = num(spec.get("m_wet")), num(spec.get("m_tare")) or 0.0
        rho_m = (m_wet - tare) / vol if m_wet is not None and vol else None
        rho_d = rho_m / (1 + w / 100) if rho_m is not None and w is not None else None
        e = gs / rho_d - 1 if gs and rho_d else None
        sr = min(w * gs / e, 100.0) if e and w is not None and gs and e > 0 else None
        results.append({"n": i + 1, "sn": sn_kpa, "peak": peak[1], "x": peak[0], "res": resid[1], "w": w,
                        "rho_m": rho_m, "rho_d": rho_d, "e": e, "sr": sr})
        curves.append(series(f"Specimen {i + 1}", pts, "line"))
    if not results:
        raise CalcError("Enter the readings of at least one specimen")
    fit = _shear_fit([(r["sn"], r["peak"]) for r in results])
    res_fit = None
    if all(r["res"] < r["peak"] for r in results):
        try:
            res_fit = _shear_fit([(r["sn"], r["res"]) for r in results])
        except CalcError:
            res_fit = None
    values: List[Tuple[str, Any, str]] = [("Cohesion c", _r(fit["c"], 1), "kPa"), ("Friction angle φ", _r(fit["phi"], 1), "°"),
                                          ("Coefficient of determination R²", _r(fit["r2"], 3), "")]
    notes = ["Peak shear stress per specimen; c and φ from a least-squares line τ = c + σ tan φ."]
    if fit["r2"] is not None and len(results) > 2:
        if fit["r2"] < 0.9:
            notes.append("R² is below 0.90; check the specimens.")
    if res_fit is not None:
        values += [("Residual cohesion", _r(res_fit["c"], 1), "kPa"), ("Residual friction angle", _r(res_fit["phi"], 1), "°")]
        notes.append("Residual strength is taken from the last reading of each specimen.")
    if fit["case"] == "origin":
        notes.append("The fitted intercept was negative; the envelope is taken through the origin.")
    if template:
        notes.append("Template conversion: shear stress × 102 and normal stress × 98.1 per kg/cm² (the standard factor is 98.0665).")
    if len(results) < 3:
        notes.append("The standard asks for at least three specimens.")
    tbl = table("Specimens", ["Specimen", "Normal stress (kPa)", "Peak shear stress (kPa)", "Displacement at peak (mm)",
                              "Residual shear stress (kPa)", "Water content w (%)", "Bulk density ρ (g/cm³)",
                              "Dry density ρd (g/cm³)", "Void ratio e", "Degree of saturation Sr (%)"],
                [[r["n"], _r(r["sn"], 1), _r(r["peak"], 2), r["x"], _r(r["res"], 2), _r(r["w"]), _r(r["rho_m"], 3),
                  _r(r["rho_d"], 3), _r(r["e"], 3), _r(r["sr"], 1)] for r in results],
                key=["Specimen", "Normal stress (kPa)", "Peak shear stress (kPa)", "Residual shear stress (kPa)"])
    top = max(r["sn"] for r in results) * 1.2
    env = [series("Peak", [(r["sn"], r["peak"]) for r in results], "points"),
           series("Peak envelope", [(0, fit["c"]), (top, fit["c"] + top * math.tan(math.radians(fit["phi"])))], "line")]
    if res_fit is not None:
        env += [series("Residual", [(r["sn"], r["res"]) for r in results], "points"),
                series("Residual envelope", [(0, res_fit["c"]), (top, res_fit["c"] + top * math.tan(math.radians(res_fit["phi"])))], "line", dash=True)]
    charts = [chart("Shear stress versus displacement", axis("Horizontal displacement (mm)"), axis("Shear stress τ (kPa)"), *curves),
              chart("Strength envelope", axis("Normal stress σ (kPa)"), axis("Shear stress τ (kPa)"), *env)]
    return result([("c", _r(fit["c"], 1), "kPa"), ("φ", _r(fit["phi"], 1), "°")], values, [tbl], charts, notes,
                  method="ASTM D3080 / SNI 2813:2008 direct shear", lab={"c": _r(fit["c"], 1), "phi": _r(fit["phi"], 1)})


# --------------------------------------------------------------------------- #
# 05.14 One-dimensional consolidation
# --------------------------------------------------------------------------- #

def taylor_t90(times: Sequence[float], dials: Sequence[float]) -> Optional[Dict[str, float]]:
    """Square-root-of-time method. Returns t90 (same unit as times), d0 and d100, or None."""
    pts = sorted((t, d) for t, d in zip(times, dials) if t > 0)
    if len(pts) < 5:
        return None
    sign = 1.0 if pts[-1][1] >= pts[0][1] else -1.0
    first = min(zip(times, dials))[1]
    xs = [math.sqrt(t) for t, _ in pts]
    ys = [sign * (d - first) for _, d in pts]
    total = ys[-1]
    # Early straight part: √t between 0.7 and 3 √min and within the first 60 % of the movement;
    # otherwise the readings up to 60 % of the movement; at least three readings.
    early = [(x, y) for x, y in zip(xs, ys) if 0.7 <= x <= 3 and y <= 0.6 * total]
    if len(early) < 3:
        early = [(x, y) for x, y in zip(xs, ys) if y <= 0.6 * total]
    if len(early) < 3:
        early = list(zip(xs, ys))[:3]
    a, b, _ = linear_fit([x for x, _ in early], [y for _, y in early])
    if b <= 0:
        return None
    slope = b / 1.15
    for i in range(1, len(xs)):
        f0 = ys[i - 1] - (a + slope * xs[i - 1])
        f1 = ys[i] - (a + slope * xs[i])
        if f0 >= 0 > f1:
            x90 = xs[i - 1] + f0 / (f0 - f1) * (xs[i] - xs[i - 1])
            d90 = a + slope * x90
            d100 = a + (d90 - a) / 0.9
            return {"t90": x90 ** 2, "d0": first + sign * a, "d100": first + sign * d100}
    return None


def casagrande_t50(times: Sequence[float], dials: Sequence[float]) -> Optional[Dict[str, float]]:
    """Logarithm-of-time method. Returns t50, d0, d100 or None."""
    pts = sorted((t, d) for t, d in zip(times, dials) if t > 0)
    if len(pts) < 6:
        return None
    sign = 1.0 if pts[-1][1] >= pts[0][1] else -1.0
    ts = [t for t, _ in pts]
    ds = [sign * d for _, d in pts]
    lts = [math.log10(t) for t in ts]
    # Corrected zero from t1 and 4 t1 (parabolic start).
    t1 = 0.25 if ts[0] <= 0.25 and ts[-1] >= 1.0 else ts[0]
    d_t1 = interpolate(math.log10(t1), lts, ds)
    d_4t1 = interpolate(math.log10(4 * t1), lts, ds)
    if d_t1 is None or d_4t1 is None:
        return None
    d0 = d_t1 - (d_4t1 - d_t1)
    # Steepest tangent of the primary part and the secondary line through the last two readings.
    slopes = [(ds[i + 1] - ds[i]) / (lts[i + 1] - lts[i]) for i in range(len(ts) - 3)]
    if not slopes:
        return None
    k = slopes.index(max(slopes))
    s1, x1, y1 = slopes[k], lts[k], ds[k]
    s2 = (ds[-1] - ds[-2]) / (lts[-1] - lts[-2])
    if s1 <= s2:
        return None
    xi = (ds[-1] - s2 * lts[-1] - y1 + s1 * x1) / (s1 - s2)
    d100 = y1 + s1 * (xi - x1)
    d50 = (d0 + d100) / 2
    t50 = _log_interp_x(d50, ts, ds)
    if t50 is None:
        return None
    return {"t50": t50, "d0": sign * d0, "d100": sign * d100}


def preconsolidation(pressures: Sequence[float], voids: Sequence[float]) -> Optional[Dict[str, Any]]:
    """Casagrande construction on a shape-preserving cubic (PCHIP) of e–log σ, both axes normalised.

    Point of maximum curvature → horizontal line and tangent → bisector; σ'p where the
    bisector meets the virgin line through the last two loading points."""
    pts = [(math.log10(p), e) for p, e in zip(pressures, voids) if p > 0]
    if len(pts) < 4:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x_lo, x_hi, y_lo, y_hi = min(xs), max(xs), min(ys), max(ys)
    if x_hi - x_lo <= 0 or y_hi - y_lo <= 0:
        return None
    xn = [(x - x_lo) / (x_hi - x_lo) for x in xs]
    yn = [(y - y_lo) / (y_hi - y_lo) for y in ys]
    sp = Pchip(xn, yn)
    best = None
    end = xn[-2]
    for k in range(1, 400):
        x = xn[0] + (end - xn[0]) * k / 400
        _, d1, d2 = sp.eval(x)
        kappa = -d2 / (1 + d1 * d1) ** 1.5
        if best is None or kappa > best[0]:
            best = (kappa, x)
    if best is None or best[0] <= 0:
        return None
    xm = best[1]
    ym, slope, _ = sp.eval(xm)
    bis = math.tan(math.atan(slope) / 2)
    sv = (yn[-1] - yn[-2]) / (xn[-1] - xn[-2])
    if abs(bis - sv) < 1e-12:
        return None
    xi = (yn[-1] - sv * xn[-1] - ym + bis * xm) / (bis - sv)
    if not xn[0] <= xi <= xn[-1]:
        return None

    def real(x: float, y: float) -> Tuple[float, float]:
        return float(10 ** (x_lo + x * (x_hi - x_lo))), y_lo + y * (y_hi - y_lo)

    pc, epc = real(xi, ym + bis * (xi - xm))
    p_m, e_m = real(xm, ym)
    return {"pc": pc, "e_pc": epc, "point": (p_m, e_m), "slope": slope, "bis": bis,
            "real": real, "xm": xm, "ym": ym, "xi": xi}


def consolidation(data: Dict[str, Any]) -> Dict[str, Any]:
    h0 = _need(data, "h0", "Initial height")
    dia = _need(data, "diameter", "Diameter")
    gs = _need(data, "gs", "Specific gravity Gs")
    m_tare = _opt(data, "m_tare", 0.0) or 0.0
    m_dry = _need(data, "m_dry_after", "Container + dry soil after test")
    sunit = _choice(data, "stress_unit", "kgcm2")
    dial0 = _opt(data, "dial_zero", 0.0) or 0.0
    area = math.pi / 4 * (dia / 10) ** 2  # cm²
    vol = area * h0 / 10
    ws = m_dry - m_tare
    if ws <= 0:
        raise CalcError("The dry soil mass must be greater than the container mass")
    hs = ws / (area * gs) * 10  # mm, height of solids
    if hs >= h0:
        raise CalcError("The height of solids exceeds the specimen height; check the masses")
    e0 = (h0 - hs) / hs
    m_ring, m_ring_soil = _opt(data, "m_ring"), _opt(data, "m_ring_soil")
    w0 = rho0 = None
    if m_ring is not None and m_ring_soil is not None:
        w0 = ((m_ring_soil - m_ring) - ws) / ws * 100
        rho0 = (m_ring_soil - m_ring) / vol
    m_wet_after = _opt(data, "m_wet_after")
    wf = (m_wet_after - m_dry) / ws * 100 if m_wet_after is not None else None
    incs = [r for r in _rows(data, "increments") if num(r.get("pressure")) is not None and num(r.get("dial")) is not None]
    if not incs:
        raise CalcError("Enter the load increments")
    # Time readings, grouped by the pressure of their increment.
    timed: Dict[float, List[Tuple[float, float]]] = {}
    for r in _rows(data, "time_readings"):
        p, t, dd = num(r.get("pressure")), num(r.get("t_min")), num(r.get("dial"))
        if p is not None and t is not None and dd is not None:
            timed.setdefault(_to_kpa(p, sunit), []).append((t, dd))
    cv_method = _choice(data, "cv_method", "taylor")
    rows: List[Dict[str, Any]] = []
    load_pts: List[Tuple[float, float]] = []
    unload_pts: List[Tuple[float, float]] = []
    h_prev, e_prev, p_prev, p_max = h0, e0, 0.0, 0.0
    time_charts = []
    for r in incs:
        p = _to_kpa(float(r["pressure"]), sunit)
        h = h0 - (float(r["dial"]) - dial0)
        e = (h - hs) / hs
        loading = p > p_max
        hdr = (h_prev + h) / 4 / 10  # cm, double drainage
        dp = (p - p_prev) / 1000  # MPa
        av = (e_prev - e) / dp if dp > 0 else None  # 1/MPa = m²/MN
        mv = av / (1 + e_prev) if av is not None else None
        cv = num(r.get("cv"))  # cm²/s, entered from the laboratory's own time curve
        t_used = None
        if p in timed:
            readings = sorted(timed[p])
            tt, dl = [x[0] for x in readings], [x[1] for x in readings]
            tay, cas = taylor_t90(tt, dl), casagrande_t50(tt, dl)
            cv_time = None
            if cv_method == "casagrande" and cas:
                cv_time, t_used = 0.197 * hdr ** 2 / (cas["t50"] * 60), cas["t50"]
            elif tay:
                cv_time, t_used = 0.848 * hdr ** 2 / (tay["t90"] * 60), tay["t90"]
            elif cas:
                cv_time, t_used = 0.197 * hdr ** 2 / (cas["t50"] * 60), cas["t50"]
            if cv is None:
                cv = cv_time
            label = f"{_r(p, 1):g} kPa"
            root = [series(label, [(math.sqrt(t), d) for t, d in readings if t >= 0], "both")]
            if tay:
                root.append(series("t90", [(math.sqrt(tay["t90"]), min(dl)), (math.sqrt(tay["t90"]), max(dl))], "line", dash=True))
            logt = [series(label, [(t, d) for t, d in readings if t > 0], "both")]
            if cas:
                logt.append(series("t50", [(cas["t50"], min(dl)), (cas["t50"], max(dl))], "line", dash=True))
            time_charts.append(chart("Time curve (square root of time)", axis("√t (√min)"), axis("Dial reading (mm)", reverse=True), *root))
            time_charts.append(chart("Time curve (log time)", axis("Time (min)", log=True), axis("Dial reading (mm)", reverse=True), *logt))
        if cv is None and num(r.get("t90")) is not None and float(r["t90"]) > 0:
            t_used = float(r["t90"])
            cv = 0.848 * hdr ** 2 / (t_used * 60)
        k = cv * 1e-4 * mv * 1e-3 * 9.81 * 100 if cv is not None and mv is not None and mv > 0 else None  # cm/s
        rows.append({"p": p, "dial": float(r["dial"]), "h": h, "e": e, "hdr": hdr, "av": av if loading else None,
                     "mv": mv if loading else None, "cv": cv, "t": t_used, "k": k if loading else None, "loading": loading})
        (load_pts if loading else unload_pts).append((p, e))
        p_max = max(p_max, p)
        h_prev, e_prev, p_prev = h, e, p
    positive = [(p, e) for p, e in load_pts if p > 0]
    notes: List[str] = []
    # Compression index: virgin line through the last two loading points (or regression over the last three).
    cc = None
    if len(positive) >= 2:
        if _choice(data, "cc_points", "last2") == "last3" and len(positive) >= 3:
            last = positive[-3:]
            _, slope, _ = linear_fit([math.log10(p) for p, _ in last], [e for _, e in last])
            cc = -slope
        else:
            (p1, e1), (p2, e2) = positive[-2], positive[-1]
            cc = (e1 - e2) / (math.log10(p2) - math.log10(p1))
    unl = [(p, e) for p, e in unload_pts if p > 0]
    cr = None
    if len(unl) >= 2:
        (p1, e1), (p2, e2) = unl[0], unl[-1]
        if p1 != p2:
            cr = (e2 - e1) / (math.log10(p1) - math.log10(p2))
    pre = preconsolidation([p for p, _ in positive], [e for _, e in positive])
    pc = pre["pc"] if pre else None
    manual_pc = _opt(data, "pc_manual")
    if manual_pc is not None:
        pc = _to_kpa(manual_pc, sunit)
        notes.append("The preconsolidation pressure was entered manually.")
    elif pc is None:
        notes.append("The preconsolidation pressure could not be found from the curve; enter it manually.")
    sv0 = _opt(data, "sigma_v0")
    ocr = pc / _to_kpa(sv0, sunit) if pc is not None and sv0 else None
    # cv for the summary: first loading increment above the in-situ stress (when given) or above σ'p.
    ref = _to_kpa(sv0, sunit) if sv0 else pc
    cv_rows = [r for r in rows if r["loading"] and r["cv"] is not None]
    cv_pick = None
    if cv_rows:
        above = [r for r in cv_rows if ref is not None and r["p"] >= ref]
        cv_pick = (above[0] if above else cv_rows[-1])["cv"]
    cv_year = cv_pick * 3153.6 if cv_pick is not None else None
    ef = rows[-1]["e"]
    values: List[Tuple[str, Any, str]] = [
        ("Initial void ratio e0", _r(e0, 4), ""), ("Compression index Cc", _r(cc, 3), ""),
        ("Recompression index Cr", _r(cr, 3), ""), ("Preconsolidation pressure σ'p", _r(pc, 1), "kPa"),
        ("Overconsolidation ratio OCR", _r(ocr), ""), ("Coefficient of consolidation cv", rnd(cv_year, 3), "m²/year"),
        ("Compression ratio Cc/(1+e0)", _r(cc / (1 + e0), 3) if cc is not None else None, ""),
        ("Height of solids Hs", _r(hs, 4), "mm"), ("Initial water content w0", _r(w0), "%"),
        ("Final water content wf", _r(wf), "%"), ("Initial bulk density ρ0", _r(rho0, 3), "g/cm³"),
        ("Initial dry density ρd0", _r(ws / vol, 3), "g/cm³"), ("Final void ratio ef", _r(ef, 4), ""),
    ]
    if w0 is not None:
        values.append(("Initial degree of saturation", _r(min(w0 * gs / e0, 100.0), 1), "%"))
    if wf is not None and ef > 0:
        values.append(("Final degree of saturation", _r(min(wf * gs / ef, 100.0), 1), "%"))
    tbl = table("Load increments", ["Pressure (kPa)", "Dial (mm)", "Height (mm)", "Void ratio e", "Drainage path Hdr (cm)",
                                    "av (m²/MN)", "mv (m²/MN)", "t90 or t50 (min)", "cv (cm²/s)", "cv (m²/year)", "k (cm/s)"],
                [[_r(r["p"], 1), r["dial"], _r(r["h"], 3), _r(r["e"], 4), _r(r["hdr"], 4), rnd(r["av"], 3), rnd(r["mv"], 3),
                  rnd(r["t"], 3), rnd(r["cv"], 3), rnd(r["cv"] * 3153.6 if r["cv"] is not None else None, 3), rnd(r["k"], 3)]
                 for r in rows],
                key=["Pressure (kPa)", "Void ratio e", "mv (m²/MN)", "cv (m²/year)", "k (cm/s)"])
    elog = [series("Loading", positive, "both"), series("Unloading", unl, "both", dash=True)]
    if pre and manual_pc is None:
        real = pre["real"]
        xm, ym = pre["xm"], pre["ym"]
        elog += [series("Horizontal line", [real(xm, ym), real(1.0, ym)], "line", dash=True),
                 series("Tangent", [real(xm, ym), real(min(1.0, xm + 0.3), ym + pre["slope"] * (min(1.0, xm + 0.3) - xm))], "line", dash=True),
                 series("Bisector", [real(xm, ym), real(pre["xi"], ym + pre["bis"] * (pre["xi"] - xm))], "line", dash=True),
                 series("Virgin line", [(pc, pre["e_pc"]), positive[-1]], "line", dash=True)]
    if pc is not None:
        elog.append(series("σ'p", [(pc, min(e for _, e in positive)), (pc, max(e for _, e in positive))], "line", dash=True))
    charts = [chart("e–log p curve", axis("Effective pressure (kPa)", log=True), axis("Void ratio e"), *elog)]
    cvs = [(r["p"], r["cv"] * 3153.6) for r in rows if r["loading"] and r["cv"] is not None and r["p"] > 0]
    if cvs:
        charts.append(chart("cv versus pressure", axis("Effective pressure (kPa)", log=True), axis("cv (m²/year)"), series("cv", cvs, "both")))
    charts += time_charts
    notes += ["Void ratio from the height of solids: e = (H − Hs) / Hs, Hs = Ws / (A · Gs).",
              "Cc from the last loading points; Cr from the unloading branch; σ'p by the Casagrande construction on a smooth curve through the loading points.",
              "cv = 0.848 Hdr² / t90 (square root of time) or 0.197 Hdr² / t50 (log time), double drainage."]
    if cv_pick is not None:
        notes.append("cv for the summary is taken at the first load increment above the in-situ stress (or σ'p when it is not given).")
    summary = [("Cc", _r(cc, 3), ""), ("e0", _r(e0, 3), ""), ("σ'p", _r(pc, 0), "kPa")]
    return result(summary, values, [tbl], charts, notes, method="ASTM D2435 / SNI 2475:2008 incremental loading oedometer",
                  lab={"cc": _r(cc, 3), "cr": _r(cr, 3), "e0": _r(e0, 4), "pc": _r(pc, 1), "cv": rnd(cv_year, 3)})


# --------------------------------------------------------------------------- #
# 05.15 One-dimensional swell (method C)
# --------------------------------------------------------------------------- #

def swelling(data: Dict[str, Any]) -> Dict[str, Any]:
    h0 = _need(data, "h0", "Initial height")
    dia = _need(data, "diameter", "Diameter")
    gs = _need(data, "gs", "Specific gravity Gs")
    m_tare = _opt(data, "m_tare", 0.0) or 0.0
    m_dry = _need(data, "m_dry_after", "Container + dry soil after test")
    dial0 = _opt(data, "dial_zero", 0.0) or 0.0
    area = math.pi / 4 * (dia / 10) ** 2
    vol = area * h0 / 10
    ws = m_dry - m_tare
    if ws <= 0:
        raise CalcError("The dry soil mass must be greater than the container mass")
    hs = ws / (area * gs) * 10
    if hs >= h0:
        raise CalcError("The height of solids exceeds the specimen height; check the masses")
    steps = [r for r in _rows(data, "steps") if num(r.get("stress")) is not None and num(r.get("dial")) is not None]
    if not steps:
        raise CalcError("Enter the load steps")
    rows: List[Dict[str, Any]] = []
    for r in steps:
        h = h0 - (float(r["dial"]) - dial0)
        rows.append({"p": float(r["stress"]), "h": h, "e": (h - hs) / hs, "phase": str(r.get("phase") or ""),
                     "strain": (h0 - h) / h0 * 100, "dial": float(r["dial"])})
    before = next((r for r in rows if r["phase"] == "before_wetting"), None)
    after_i = next((i for i, r in enumerate(rows) if r["phase"] == "after_wetting"), None)
    if before is None or after_i is None:
        raise CalcError("Mark the step at the vertical stress before wetting and the step after wetting")
    after = rows[after_i]
    h1, h2 = before["h"], after["h"]
    swell = (h2 - h1) / h1 * 100
    # Swell pressure: stress at which loading after wetting brings the void ratio back to its value before wetting.
    post = [r for r in rows[after_i:] if r["phase"] in ("after_wetting", "load", "") and r["p"] > 0]
    sp = _log_interp_x(before["e"], [r["p"] for r in post], [r["e"] for r in post]) if len(post) >= 2 else None
    notes = ["Swell = (h2 − h1) / h1 with h1 the height before and h2 the height after wetting under the same stress.",
             "Swell pressure: the stress at which loading after wetting returns the void ratio to its value before wetting (log-linear interpolation)."]
    if swell <= 0:
        notes.append("The specimen did not swell on wetting.")
    if sp is None and swell > 0:
        notes.append("The loading after wetting does not reach the void ratio before wetting; load further to find the swell pressure.")
    m_ring, m_ring_soil = _opt(data, "m_ring"), _opt(data, "m_ring_soil")
    wi = rho_i = None
    if m_ring is not None and m_ring_soil is not None:
        wi = ((m_ring_soil - m_ring) - ws) / ws * 100
        rho_i = (m_ring_soil - m_ring) / vol
    m_wet_after = _opt(data, "m_wet_after")
    wf = (m_wet_after - m_dry) / ws * 100 if m_wet_after is not None else None
    e_i, e_f = (h0 - hs) / hs, rows[-1]["e"]
    rho_f = gs / (1 + e_f) * (1 + wf / 100) if wf is not None else None
    values: List[Tuple[str, Any, str]] = [
        ("Swell", _r(swell, 3), "%"), ("Swell pressure", _r(sp, 1), "kPa"),
        ("Height before wetting h1", _r(h1, 3), "mm"), ("Height after wetting h2", _r(h2, 3), "mm"),
        ("Height of solids Hs", _r(hs, 4), "mm"), ("Initial void ratio e0", _r(e_i, 4), ""),
        ("Initial water content", _r(wi), "%"), ("Final water content", _r(wf), "%"),
        ("Initial bulk density", _r(rho_i, 3), "g/cm³"), ("Initial dry density", _r(gs / (1 + e_i), 3), "g/cm³"),
        ("Final bulk density", _r(rho_f, 3), "g/cm³"),
    ]
    if wi is not None:
        values.append(("Initial degree of saturation", _r(min(wi * gs / e_i, 100.0), 1), "%"))
    phase_names = {"seating": "Seating", "load": "Loading", "before_wetting": "Before wetting",
                   "after_wetting": "After wetting", "unload": "Unloading"}
    tbl = table("Load steps", ["Stress (kPa)", "Step", "Dial (mm)", "Height (mm)", "Strain (%)", "Void ratio e"],
                [[r["p"], phase_names.get(r["phase"], r["phase"]), r["dial"], _r(r["h"], 3), _r(r["strain"], 3), _r(r["e"], 4)] for r in rows])
    pre_pts = [(r["p"], r["e"]) for r in rows[:after_i] if r["p"] > 0]
    post_pts = [(r["p"], r["e"]) for r in rows[after_i:] if r["p"] > 0]
    sers = [series("Before wetting", pre_pts, "both"), series("After wetting", post_pts, "both"),
            series("Wetting", [(before["p"], before["e"]), (after["p"], after["e"])], "line", dash=True)]
    if sp is not None:
        sers.append(series("Swell pressure", [(before["p"], before["e"]), (sp, before["e"])], "line", dash=True))
    charts = [chart("Void ratio versus stress", axis("Vertical stress (kPa)", log=True), axis("Void ratio e"), *sers)]
    times = [(num(r.get("t_min")), num(r.get("dial"))) for r in _rows(data, "time_readings")]
    tpts = sorted((t, d) for t, d in times if t is not None and d is not None and t > 0)
    if tpts:
        ref = before["dial"]
        charts.append(chart("Swell versus time", axis("Time (min)", log=True), axis("Swell (%)"),
                            series("Swell", [(t, (ref - d) / h1 * 100) for t, d in tpts], "both")))
    return result([("Swell", _r(swell, 2), "%"), ("Swell pressure", _r(sp, 1), "kPa")], values, [tbl], charts, notes,
                  method="ASTM D4546 method C one-dimensional swell", lab={"swell": _r(swell, 3), "swell_pressure": _r(sp, 1)})


# --------------------------------------------------------------------------- #
# 05.16 Los Angeles abrasion
# --------------------------------------------------------------------------- #

LA_GRADINGS: Dict[str, List[Tuple[float, float, float]]] = {  # passing mm, retained mm, mass g
    "A": [(37.5, 25.0, 1250), (25.0, 19.0, 1250), (19.0, 12.5, 1250), (12.5, 9.5, 1250)],
    "B": [(19.0, 12.5, 2500), (12.5, 9.5, 2500)],
    "C": [(9.5, 6.3, 2500), (6.3, 4.75, 2500)],
    "D": [(4.75, 2.36, 5000)],
    "1": [(75.0, 63.0, 2500), (63.0, 50.0, 2500), (50.0, 37.5, 5000)],
    "2": [(50.0, 37.5, 5000), (37.5, 25.0, 5000)],
    "3": [(37.5, 25.0, 5000), (25.0, 19.0, 5000)],
}


def la_abrasion(data: Dict[str, Any]) -> Dict[str, Any]:
    grading = _choice(data, "grading", "A")
    fr = [r for r in _rows(data, "fractions") if num(r.get("mass_1")) is not None or num(r.get("mass_2")) is not None]
    if not fr:
        raise CalcError("Enter the masses of the size fractions")
    losses = []
    rows: List[List[Any]] = []
    for trial in (1, 2):
        masses = [num(r.get(f"mass_{trial}")) for r in fr]
        a = sum(m for m in masses if m is not None)
        b = _opt(data, f"retained_{trial}")
        if a <= 0:
            continue
        if b is None:
            raise CalcError("Mass retained on the 1.70 mm sieve (No. 12) is required")
        if b > a:
            raise CalcError("The mass after the test must not exceed the mass before the test")
        loss = (a - b) / a * 100
        losses.append(loss)
        rows.append([trial, a, b, _r(loss)])
    if not losses:
        raise CalcError("Enter the masses of the size fractions")
    loss = sum(losses) / len(losses)
    notes = ["Loss = (a − b) / a with a the mass before the test and b the mass retained on the 1.70 mm (No. 12) sieve."]
    spec = LA_GRADINGS.get(grading)
    if spec is not None:
        nominal = sum(m for _, _, m in spec)
        def matches(r: Dict[str, Any]) -> bool:
            p, q = num(r.get("passing")), num(r.get("retained"))
            return p is not None and q is not None and any(abs(p - sp) <= 0.05 * sp and abs(q - sq) <= 0.05 * sq for sp, sq, _ in spec)
        if not all(matches(r) for r in fr) or len(fr) != len(spec):
            notes.append("The size fractions do not match the chosen grading.")
        for _, a, _, _ in rows:
            if abs(a - nominal) > 0.01 * nominal:
                notes.append("The total mass differs from the mass required by the grading.")
                break
    revs = _opt(data, "revolutions") or (1000 if grading in ("1", "2", "3") else 500)
    values: List[Tuple[str, Any, str]] = [("Abrasion loss", _r(loss), "%"), ("Revolutions", int(revs), "")]
    tbl = table("Trials", ["Trial", "Mass before test a (g)", "Mass retained b (g)", "Loss (%)"], rows)
    method = "ASTM C535 large coarse aggregate" if grading in ("1", "2", "3") else "ASTM C131 Los Angeles machine"
    return result([("Loss", _r(loss), "%")], values, [tbl], [], notes, method=method, lab={"loss": _r(loss)})


# --------------------------------------------------------------------------- #
# 05.17 Sulfate soundness
# --------------------------------------------------------------------------- #

def soundness(data: Dict[str, Any]) -> Dict[str, Any]:
    fr = [r for r in _rows(data, "fractions") if num(r.get("grading")) is not None]
    if not fr:
        raise CalcError("Enter the grading of each size fraction")
    losses: List[Optional[float]] = []
    for r in fr:
        before, after = num(r.get("mass_before")), num(r.get("mass_after"))
        if before is None or after is None:
            losses.append(None)
            continue
        if before <= 0:
            raise CalcError("The mass before the test must be greater than zero")
        if after > before:
            raise CalcError("The mass after the test must not exceed the mass before the test")
        losses.append((before - after) / before * 100)
    if all(v is None for v in losses):
        raise CalcError("Enter the masses before and after the test")
    notes = ["Weighted loss = Σ (loss of each fraction × its share of the original grading)."]
    filled: List[Optional[float]] = list(losses)
    for i, v in enumerate(losses):
        if v is None:
            # ASTM C88: an untested fraction takes the average loss of the next smaller and larger fractions.
            near = [x for x in (losses[i - 1] if i > 0 else None, losses[i + 1] if i + 1 < len(losses) else None) if x is not None]
            filled[i] = sum(near) / len(near) if near else 0.0
            notes.append("Untested fractions take the average loss of the neighbouring fractions.")
    total = 0.0
    rows = []
    for r, loss, raw_loss in zip(fr, filled, losses):
        weighted = (loss or 0.0) * float(r["grading"]) / 100
        total += weighted
        rows.append([r.get("size") or "", float(r["grading"]), num(r.get("mass_before")), num(r.get("mass_after")),
                     _r(raw_loss), _r(weighted)])
    if _choice(data, "aggregate", "fine") == "fine":
        notes.append("For fine aggregate, material finer than 0.300 mm counts as zero loss.")
    tbl = table("Size fractions", ["Size fraction", "Grading (%)", "Mass before (g)", "Mass after (g)", "Loss (%)",
                                   "Weighted loss (%)"], rows)
    values: List[Tuple[str, Any, str]] = [("Weighted loss", _r(total), "%")]
    method = ("ASTM C88 soundness, magnesium sulfate" if _choice(data, "solution", "sodium") == "magnesium"
              else "ASTM C88 soundness, sodium sulfate")
    return result([("Loss", _r(total), "%")], values, [tbl], [], list(dict.fromkeys(notes)),
                  method=method, lab={"loss": _r(total)})


# --------------------------------------------------------------------------- #
# 05.18 Slake durability
# --------------------------------------------------------------------------- #

def _durability(id2: float) -> str:
    for limit, name in ((30, "Very low"), (60, "Low"), (85, "Medium"), (95, "Medium high"), (98, "High")):
        if id2 < limit:
            return name
    return "Very high"


def slake_durability(data: Dict[str, Any]) -> Dict[str, Any]:
    b = _need(data, "m_dry_before", "Drum + oven-dried sample before the first cycle")
    c = _need(data, "m_drum", "Drum mass")
    if b <= c:
        raise CalcError("The drum with the sample must weigh more than the empty drum")
    a = _opt(data, "m_natural")
    w = (a - b) / (b - c) * 100 if a is not None else None
    cycles = sorted([(int(float(r["cycle"])), float(r["m_after"])) for r in _rows(data, "cycles")
                     if num(r.get("cycle")) is not None and num(r.get("m_after")) is not None])
    if not cycles:
        raise CalcError("Enter the mass after at least one cycle")
    ids = {}
    for n, m in cycles:
        if m > b:
            raise CalcError("The retained mass must not exceed the mass before the test")
        ids[n] = (m - c) / (b - c) * 100
    values: List[Tuple[str, Any, str]] = []
    if w is not None:
        values.append(("Natural water content", _r(w), "%"))
    for n, v in ids.items():
        values.append((f"Slake durability index Id{n}", _r(v), "%"))
    notes = ["Id = (mass retained after the cycle − drum) / (oven-dried sample before the test − drum)."]
    if 2 in ids:
        values.append(("Durability (Gamble)", _durability(ids[2]), ""))
    else:
        notes.append("The second-cycle index Id2 is the standard result; enter the mass after the second cycle.")
    frag = _choice(data, "fragment_type", "")
    if frag:
        values.append(("Fragment type", frag, ""))
    tbl = table("Cycles", ["Cycle", "Drum + retained sample (g)", "Slake durability index (%)"],
                [[n, m, _r(ids[n])] for n, m in cycles])
    ch = chart("Slake durability", axis("Cycle"), axis("Slake durability index (%)"),
               series("Id", [(0, 100.0)] + [(n, ids[n]) for n, _ in cycles], "both"))
    summary = [("Id2", _r(ids.get(2)), "%")] if 2 in ids else [(f"Id{cycles[-1][0]}", _r(ids[cycles[-1][0]]), "%")]
    return result(summary, values, [tbl], [ch], notes, method="ASTM D4644 slake durability",
                  lab={"id1": _r(ids.get(1)), "id2": _r(ids.get(2)), "w": _r(w)})
