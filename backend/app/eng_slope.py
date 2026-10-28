"""Slope stability: infinite slope with seepage, and circular slip surfaces by the simplified
Bishop method (with the ordinary method of slices for comparison) and a grid search.

Pure Python, SI units: m, kPa, kN/m3; forces per metre run.

Geometry of the circular analysis: x to the right, y up; the ground rises from the toe on the
left to the crest on the right, so the slip mass moves to the left. Soil layers are horizontal
and given by their bottom elevation (the last layer goes down without limit). Pore pressure
comes from a phreatic line (u = gamma_w * vertical depth below it) or from ru = u / sigma_v.
A pseudo-static horizontal force kh*W acts at each slice centroid, out of the slope.

Sources: Bishop (1955); Fellenius (1936); Duncan, Wright & Brandon (2014), Soil Strength and
Slope Stability; Das, Principles of Geotechnical Engineering (infinite slope with seepage);
required factors of safety after SNI 8460:2017. Results are preliminary.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import calcbase
from .calcbase import CalcError, rnd
from .engineering import GAMMA_W, PRELIMINARY_NOTE

Point = Tuple[float, float]

STANDARDS: List[Tuple[str, str]] = [
    ("SNI 8460:2017", "Geotechnical design requirements: minimum factors of safety for slopes"),
    ("Bishop (1955)", "The use of the slip circle in the stability analysis of slopes, Géotechnique 5"),
    ("Fellenius (1936)", "Ordinary method of slices"),
    ("Duncan, Wright & Brandon (2014)", "Soil Strength and Slope Stability, 2nd ed."),
    ("Das (2010)", "Principles of Geotechnical Engineering: infinite slope with seepage"),
    ("Giam & Donald (1989)", "ACADS slope stability programs review: benchmark problems"),
]

MAX_LAYERS = 5
SEARCH_BUDGET_S = 1.4  # wall-clock limit for the grid search (serverless request)


def _val(inputs: Dict[str, Any], key: str, label: str, default: Optional[float] = None,
         lo: Optional[float] = None, hi: Optional[float] = None, required: bool = True) -> Optional[float]:
    raw = inputs.get(key)
    value = calcbase.num(raw)
    if raw not in (None, "") and value is None:
        raise CalcError(f"{label} must be a number")
    if value is None:
        if default is None and required:
            raise CalcError(f"{label} is required")
        value = default
    if value is None:
        return None
    if lo is not None and value < lo:
        raise CalcError(f"{label} must be at least {lo:g}")
    if hi is not None and value > hi:
        raise CalcError(f"{label} must be at most {hi:g}")
    return value


def _need(inputs: Dict[str, Any], key: str, label: str, default: Optional[float] = None,
          lo: Optional[float] = None, hi: Optional[float] = None) -> float:
    value = _val(inputs, key, label, default, lo, hi)
    assert value is not None
    return value


def classify(fs: float, seismic: bool) -> str:
    """Class of a factor of safety after the SNI 8460:2017 slope table (1.25 / 1.5 / 2.0) and FS >= 1.1 pseudo-static."""
    if seismic:
        return "Stable under the seismic load (FS ≥ 1.1)" if fs >= 1.1 else "Unsafe under the seismic load (FS < 1.1)"
    if fs >= 1.5:
        return "Stable (FS ≥ 1.5)"
    if fs >= 1.25:
        return "Marginal (1.25 ≤ FS < 1.5): only where the analysis uncertainty is low and repair costs are comparable"
    if fs >= 1.0:
        return "Unsafe (FS < 1.25)"
    return "Failure expected (FS < 1)"


# ---------------------------------------------------------------------------
# (a) Infinite slope
# ---------------------------------------------------------------------------

def infinite_slope(*, c: float, phi_deg: float, gamma: float, gamma_sat: float, beta_deg: float, z: float,
                   m: float, kh: float = 0.0) -> Dict[str, float]:
    """FS of an infinite slope with seepage parallel to the surface (Das). The water table is m*z above
    the slip plane (m = 0 dry, m = 1 water at the surface). Per unit length of slope:
    N' = W cos(b) - kh W sin(b) - u, T = W sin(b) + kh W cos(b), u = gamma_w m z cos^2(b)."""
    b = math.radians(beta_deg)
    w = (gamma * (1 - m) + gamma_sat * m) * z * math.cos(b)
    u = GAMMA_W * m * z * math.cos(b) ** 2
    n_eff = w * math.cos(b) - kh * w * math.sin(b) - u
    t = w * math.sin(b) + kh * w * math.cos(b)
    fs = (c + max(0.0, n_eff) * math.tan(math.radians(phi_deg))) / t
    return {"FS": fs, "sigma_n_eff": n_eff, "tau": t, "u": u}


def _infinite(inputs: Dict[str, Any]) -> Dict[str, Any]:
    beta = _need(inputs, "beta", "Slope angle β", lo=1, hi=80)
    z = _need(inputs, "z", "Depth of the slip plane z", lo=0.1, hi=100)
    m = _need(inputs, "m", "Water height ratio m", 0.0, lo=0, hi=1)
    gamma = _need(inputs, "gamma", "Unit weight γ", lo=10, hi=25)
    gamma_sat = _need(inputs, "gamma_sat", "Saturated unit weight γsat", gamma + 1.0, lo=GAMMA_W + 0.1, hi=26)
    c = _need(inputs, "c", "Cohesion c'", 0.0, lo=0, hi=500)
    phi = _need(inputs, "phi", "Friction angle φ'", lo=0, hi=50)
    kh = _need(inputs, "kh", "Seismic coefficient kh", 0.0, lo=0, hi=0.6)
    req = _need(inputs, "fs_req", "Required FS", 1.1 if kh > 0 else 1.5, lo=1, hi=3)
    if c == 0 and phi == 0:
        raise CalcError("Enter c' or φ'")
    res = infinite_slope(c=c, phi_deg=phi, gamma=gamma, gamma_sat=gamma_sat, beta_deg=beta, z=z, m=m, kh=kh)
    fs = res["FS"]
    depths = [z * i / 20 for i in range(1, 41)]
    curve = [(min(infinite_slope(c=c, phi_deg=phi, gamma=gamma, gamma_sat=gamma_sat, beta_deg=beta, z=d, m=m, kh=kh)["FS"], 5.0), d)
             for d in depths]
    charts = [calcbase.chart("Factor of safety with depth of the slip plane", calcbase.axis("FS (capped at 5)"),
                             calcbase.axis("Depth z (m)", reverse=True),
                             calcbase.series("FS", curve, "line"),
                             calcbase.series("Required FS", [(req, depths[0]), (req, depths[-1])], "line", dash=True))]
    notes = ["Infinite slope: slip plane parallel to the surface, seepage parallel to the slope, end effects ignored.",
             "m = 0: dry; m = 1: water table at the ground surface."]
    if c == 0:
        notes.append("c' = 0: FS does not depend on depth; FS = tan φ' / tan β for a dry slope.")
    if kh > 0:
        notes.append("Pseudo-static: kh·W acts horizontally out of the slope at every point.")
    notes += ["Required FS after SNI 8460:2017: 1.25 to ≥ 2.0 by the uncertainty and the cost of failure; 1.5 is usual for permanent slopes, 1.1 under the seismic load.",
              PRELIMINARY_NOTE]
    status = classify(fs, kh > 0)
    out = calcbase.result(
        summary=[("FS", rnd(fs, 3), ""), ("Required FS", req, "")],
        values=[("Slope angle β", beta, "°"), ("Depth z", z, "m"), ("Water height ratio m", m, ""),
                ("Pore pressure u on the plane", rnd(res["u"], 4), "kPa"), ("Effective normal stress σ'n", rnd(res["sigma_n_eff"], 4), "kPa"),
                ("Driving shear stress τ", rnd(res["tau"], 4), "kPa"), ("Class", status, "")],
        charts=charts, notes=notes,
        method="Infinite slope with seepage parallel to the slope (Das)")
    out["checks"] = [{"check": "Factor of safety", "case": "Seismic" if kh > 0 else "Static", "value": rnd(fs, 3), "unit": "",
                      "required": f"≥ {req:g}", "ok": fs >= req}]
    out["standards"] = [list(s) for s in STANDARDS[:1] + STANDARDS[4:5]]
    out["status"] = "pass" if fs >= req else "fail"
    out["classification"] = status
    return out


# ---------------------------------------------------------------------------
# (b) Circular slip surfaces
# ---------------------------------------------------------------------------

class Model:
    def __init__(self, ground: List[Point], layers: List[Dict[str, float]], phreatic: Optional[List[Point]], ru: float,
                 q: float, q_from: float, kh: float):
        self.ground = ground
        self.layers = layers  # sorted from the top; each {bottom, gamma, gamma_sat, c, phi, tanphi}
        self.phreatic = phreatic
        self.ru = ru
        self.q = q
        self.q_from = q_from
        self.kh = kh
        # ground extended flat far beyond its ends
        span = ground[-1][0] - ground[0][0]
        self.ext = [(ground[0][0] - 50 * span, ground[0][1])] + ground + [(ground[-1][0] + 50 * span, ground[-1][1])]

    @staticmethod
    def interp(pts: Sequence[Point], x: float) -> float:
        if x <= pts[0][0]:
            return pts[0][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x <= x1:
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y1
        return pts[-1][1]

    def y_ground(self, x: float) -> float:
        return self.interp(self.ground, x)

    def y_water(self, x: float) -> Optional[float]:
        return None if self.phreatic is None else self.interp(self.phreatic, x)

    def layer_at(self, y: float) -> Dict[str, float]:
        for layer in self.layers:
            if y >= layer["bottom"]:
                return layer
        return self.layers[-1]

    def column_weight(self, x: float, yb: float, ys: float) -> float:
        """Weight per unit width of the soil column between yb and ys at x (kN/m per m)."""
        yw = self.y_water(x)
        w = 0.0
        top = ys
        for layer in self.layers:
            bot = max(layer["bottom"], yb)
            if top <= bot:
                if layer["bottom"] <= yb:
                    break
                continue
            if yw is None or yw <= bot:
                w += layer["gamma"] * (top - bot)
            elif yw >= top:
                w += layer["gamma_sat"] * (top - bot)
            else:
                w += layer["gamma"] * (top - yw) + layer["gamma_sat"] * (yw - bot)
            top = bot
            if layer["bottom"] <= yb:
                break
        return w

    def intersections(self, xc: float, yc: float, r: float) -> List[float]:
        """x of the points where the lower half of the circle crosses the ground."""
        xs: List[float] = []
        for (x0, y0), (x1, y1) in zip(self.ext, self.ext[1:]):
            dx, dy = x1 - x0, y1 - y0
            fx, fy = x0 - xc, y0 - yc
            a = dx * dx + dy * dy
            b = 2 * (fx * dx + fy * dy)
            cc = fx * fx + fy * fy - r * r
            disc = b * b - 4 * a * cc
            if disc < 0 or a == 0:
                continue
            sq = math.sqrt(disc)
            for t in ((-b - sq) / (2 * a), (-b + sq) / (2 * a)):
                if 0 <= t <= 1:
                    y = y0 + t * dy
                    if y <= yc + 1e-9:
                        xs.append(x0 + t * dx)
        return sorted(xs)

    def slip_range(self, xc: float, yc: float, r: float) -> Optional[Tuple[float, float, float]]:
        """(x_left, x_right, max depth) of the deepest part of the circle below the ground."""
        xs = self.intersections(xc, yc, r)
        best = None
        for xl, xr in zip(xs, xs[1:]):
            if xr - xl < 1e-6:
                continue
            xm = (xl + xr) / 2
            arc = yc - math.sqrt(max(0.0, r * r - (xm - xc) ** 2))
            depth = 0.0
            for k in range(1, 8):
                x = xl + (xr - xl) * k / 8
                depth = max(depth, self.y_ground(x) - (yc - math.sqrt(max(0.0, r * r - (x - xc) ** 2))))
            if self.y_ground(xm) - arc > 0 and (best is None or depth > best[2]):
                best = (xl, xr, depth)
        return best

    def slices(self, xc: float, yc: float, r: float, xl: float, xr: float, n: int) -> List[Dict[str, float]]:
        out = []
        b = (xr - xl) / n
        for i in range(n):
            x0 = xl + i * b
            x1 = x0 + b
            xm = x0 + b / 2
            yb = yc - math.sqrt(max(0.0, r * r - (xm - xc) ** 2))
            ys = self.y_ground(xm)
            h = ys - yb
            if h <= 0:
                continue
            # base angle from the chord of the arc across the slice
            yb0 = yc - math.sqrt(max(0.0, r * r - (x0 - xc) ** 2))
            yb1 = yc - math.sqrt(max(0.0, r * r - (x1 - xc) ** 2))
            alpha = math.atan2(yb1 - yb0, b)
            w_soil = self.column_weight(xm, yb, ys) * b
            w_q = self.q * b if (self.q > 0 and xm >= self.q_from) else 0.0
            layer = self.layer_at(yb)
            if self.phreatic is not None:
                yw = self.y_water(xm)
                u = GAMMA_W * max(0.0, (yw if yw is not None else -math.inf) - yb)
            else:
                u = self.ru * w_soil / b
            out.append({"x": xm, "b": b, "h": h, "alpha": alpha, "W": w_soil + w_q, "Ws": w_soil, "yg": (ys + yb) / 2,
                        "u": u, "c": layer["c"], "tanphi": layer["tanphi"], "ys": ys, "yb": yb, "phi": layer["phi"]})
        return out

    def factor(self, sl: List[Dict[str, float]], xc: float, yc: float, r: float) -> Optional[Tuple[float, float, int]]:
        """(FS Bishop, FS ordinary, number of slices with m_alpha < 0.2) or None when nothing drives."""
        drive = 0.0
        ordinary = 0.0
        for s in sl:
            sa, ca = math.sin(s["alpha"]), math.cos(s["alpha"])
            drive += s["W"] * sa + self.kh * s["Ws"] * (yc - s["yg"]) / r
            n_eff = s["W"] * ca - self.kh * s["Ws"] * sa - s["u"] * s["b"] / ca
            ordinary += s["c"] * s["b"] / ca + max(0.0, n_eff) * s["tanphi"]
        if drive <= 1e-9:
            return None
        fs_o = ordinary / drive
        fs = max(fs_o, 0.05)
        low = 0
        for _ in range(60):
            resist = 0.0
            low = 0
            for s in sl:
                sa, ca = math.sin(s["alpha"]), math.cos(s["alpha"])
                m_a = ca + sa * s["tanphi"] / fs
                if m_a < 0.2:
                    low += 1
                    m_a = 0.2
                resist += (s["c"] * s["b"] + max(0.0, s["W"] - s["u"] * s["b"]) * s["tanphi"]) / m_a
            new = resist / drive
            if abs(new - fs) < 1e-5:
                fs = new
                break
            fs = new
        return fs, fs_o, low


def _points(rows: Any, label: str, min_points: int = 2) -> List[Point]:
    if isinstance(rows, str):
        parts = [p for p in rows.replace("\n", ";").split(";") if p.strip()]
        rows = [dict(zip(("x", "y"), p.replace(",", " ").split())) for p in parts]
    pts: List[Point] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        x, y = calcbase.num(row.get("x")), calcbase.num(row.get("y"))
        if x is None and y is None:
            continue
        if x is None or y is None:
            raise CalcError(f"{label}: every point needs x and y")  # label is "Ground surface" or "Phreatic line"
        pts.append((x, y))
    if len(pts) < min_points:
        raise CalcError(f"{label}: enter at least {min_points} points")
    for (x0, _), (x1, _) in zip(pts, pts[1:]):
        if x1 <= x0:
            raise CalcError(f"{label}: x must increase from left to right")
    return pts


def _geometry(inputs: Dict[str, Any]) -> Tuple[List[Point], float, float, float, float]:
    """Ground polyline and (x_toe, y_toe, x_crest, y_crest)."""
    if str(inputs.get("geometry") or "simple") == "points":
        ground = _points(inputs.get("surface"), "Ground surface", 3)
        if len(ground) > 30:
            raise CalcError("Ground surface: at most 30 points")
        ys = [p[1] for p in ground]
        y_top, y_bot = max(ys), min(ys)
        i_crest = ys.index(y_top)
        i_toe = max(i for i in range(i_crest + 1) if ys[i] == min(ys[: i_crest + 1]))
        if i_crest <= i_toe or y_top - ys[i_toe] < 0.5:
            raise CalcError("Ground surface: enter the slope from the toe (left, low) to the crest (right, high)")
        return ground, ground[i_toe][0], ground[i_toe][1], ground[i_crest][0], y_top
    H = _need(inputs, "H", "Slope height H", lo=0.5, hi=200)
    beta = _need(inputs, "beta", "Slope angle β", lo=5, hi=85)
    bench_w = _need(inputs, "bench_w", "Bench width", 0.0, lo=0, hi=100)
    bench_h = _need(inputs, "bench_h", "Bench height above the toe", H / 2, lo=0, hi=H)
    run = 1 / math.tan(math.radians(beta))
    x_toe = max(H, 5.0)
    if bench_w > 0 and 0 < bench_h < H:
        x1 = x_toe + bench_h * run
        x2 = x1 + bench_w
        x_crest = x2 + (H - bench_h) * run
        ground = [(0.0, 0.0), (x_toe, 0.0), (x1, bench_h), (x2, bench_h), (x_crest, H), (x_crest + max(H * 1.5, 10.0), H)]
    else:
        x_crest = x_toe + H * run
        ground = [(0.0, 0.0), (x_toe, 0.0), (x_crest, H), (x_crest + max(H * 1.5, 10.0), H)]
    return ground, x_toe, 0.0, x_crest, H


def _layers(inputs: Dict[str, Any]) -> List[Dict[str, float]]:
    rows = [r for r in (inputs.get("layers") or []) if isinstance(r, dict) and any(calcbase.num(r.get(k)) is not None for k in ("gamma", "c", "phi"))]
    if not rows:
        raise CalcError("Add at least one soil layer")
    if len(rows) > MAX_LAYERS:
        raise CalcError("At most 5 soil layers")
    out = []
    for i, r in enumerate(rows):
        label = f"Soil layers row {i + 1}"
        gamma = _need(r, "gamma", f"{label}, γ (kN/m³)", lo=10, hi=26)
        gamma_sat = _need(r, "gamma_sat", f"{label}, γsat (kN/m³)", gamma + 1.0, lo=GAMMA_W + 0.1, hi=27)
        c = _need(r, "c", f"{label}, c' (kPa)", 0.0, lo=0, hi=1000)
        phi = _need(r, "phi", f"{label}, φ' (°)", 0.0, lo=0, hi=50)
        if c == 0 and phi == 0:
            raise CalcError("Each soil layer needs c' or φ'")
        bottom = _val(r, "bottom", f"{label}, Bottom elevation (m)", required=False)
        if bottom is None:
            if i < len(rows) - 1:
                raise CalcError("Enter the bottom elevation of every soil layer except the last")
            bottom = -math.inf
        out.append({"bottom": bottom, "gamma": gamma, "gamma_sat": gamma_sat, "c": c, "phi": phi, "tanphi": math.tan(math.radians(phi))})
    for a, b in zip(out, out[1:]):
        if b["bottom"] >= a["bottom"]:
            raise CalcError("Soil layers: list them from the top down with decreasing bottom elevations")
    out[-1]["bottom"] = -math.inf
    return out


def _circular(inputs: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    ground, x_toe, y_toe, x_crest, y_crest = _geometry(inputs)
    H = y_crest - y_toe
    layers = _layers(inputs)
    water = str(inputs.get("water") or "none")
    phreatic: Optional[List[Point]] = None
    ru = 0.0
    if water == "phreatic":
        phreatic = _points(inputs.get("phreatic"), "Phreatic line", 2)
    elif water == "ru":
        ru = _need(inputs, "ru", "Pore pressure ratio ru", lo=0, hi=0.9)
    q = _need(inputs, "q", "Surcharge on the crest q", 0.0, lo=0, hi=500)
    q_off = _need(inputs, "q_offset", "Surcharge starts behind the crest at", 0.0, lo=0, hi=200)
    kh = _need(inputs, "kh", "Seismic coefficient kh", 0.0, lo=0, hi=0.6)
    n_sl = int(_need(inputs, "n_slices", "Number of slices", 40, lo=30, hi=50))
    depth_lim = _need(inputs, "depth_limit", "Maximum depth of the slip below the toe", max(H, 3.0), lo=0, hi=500)
    req = _need(inputs, "fs_req", "Required FS", 1.1 if kh > 0 else 1.5, lo=1, hi=3)
    model = Model(ground, layers, phreatic, ru, q, x_crest + q_off, kh)

    span = max(x_crest - x_toe, H)
    min_depth = max(0.3, 0.05 * H)
    y_floor = y_toe - depth_lim
    n_search = 24  # slices during the search; the critical circle is recomputed with n_slices

    def evaluate(xc: float, yc: float, r: float, n: int = n_search) -> Optional[Dict[str, Any]]:
        if yc - r < y_floor - 1e-6:
            return None
        rng = model.slip_range(xc, yc, r)
        if rng is None or rng[2] < min_depth:
            return None
        xl, xr, _ = rng
        sl = model.slices(xc, yc, r, xl, xr, n)
        if not sl:
            return None
        res = model.factor(sl, xc, yc, r)
        if res is None:
            return None
        return {"xc": xc, "yc": yc, "R": r, "FS": res[0], "FS_ord": res[1], "low": res[2], "xl": xl, "xr": xr}

    def radii(xc: float, yc: float, n: int) -> List[float]:
        top = y_crest - 0.1 * H
        bottom = max(y_floor, yc - 10 * span)
        out = [yc - (bottom + (top - bottom) * k / (n - 1)) for k in range(n)]
        out.append(math.hypot(xc - x_toe, yc - y_toe))  # through the toe
        return [r for r in out if r > 0.1]

    def search(xs: List[float], ys: List[float], n_r: int, grid: Optional[Dict[Tuple[int, int], float]] = None) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        for j, yc in enumerate(ys):
            for i, xc in enumerate(xs):
                best = None
                for r in radii(xc, yc, n_r):
                    res = evaluate(xc, yc, r)
                    if res is not None:
                        found.append(res)
                        if best is None or res["FS"] < best:
                            best = res["FS"]
                if grid is not None and best is not None:
                    grid[(i, j)] = best
        return found

    nx = ny = 10
    gx0, gx1 = x_toe - 0.3 * span, x_crest + 0.3 * span
    gy0, gy1 = y_crest + 0.1 * H, y_crest + 1.6 * span
    gxs = [gx0 + (gx1 - gx0) * i / (nx - 1) for i in range(nx)]
    gys = [gy0 + (gy1 - gy0) * j / (ny - 1) for j in range(ny)]
    grid: Dict[Tuple[int, int], float] = {}
    found = search(gxs, gys, 10, grid)
    if not found:
        raise CalcError("No slip circle found; check the geometry and the maximum slip depth")
    best = min(found, key=lambda r: r["FS"])
    dx, dy = (gx1 - gx0) / (nx - 1), (gy1 - gy0) / (ny - 1)
    passes = 0
    while time.perf_counter() - t0 < SEARCH_BUDGET_S and passes < 3:
        passes += 1
        xs = [best["xc"] + dx * k / 2 for k in (-2, -1, 0, 1, 2)]
        ys = [best["yc"] + dy * k / 2 for k in (-2, -1, 0, 1, 2)]
        ys = [y for y in ys if y > y_crest]
        found += search(xs, ys, 14)
        best = min(found, key=lambda r: r["FS"])
        dx, dy = dx / 2, dy / 2
    elapsed = time.perf_counter() - t0

    # The best candidates again with the chosen number of slices; then distinct next circles.
    ranked = sorted(found, key=lambda r: r["FS"])
    pool: List[Dict[str, Any]] = []
    for cand in ranked:
        if len(pool) >= 40:
            break
        if all(abs(cand["xc"] - o["xc"]) + abs(cand["yc"] - o["yc"]) + abs(cand["R"] - o["R"]) > 0.15 * span for o in pool[-1:]) or len(pool) < 12:
            again = evaluate(cand["xc"], cand["yc"], cand["R"], n_sl)
            if again is not None:
                pool.append(again)
    pool.sort(key=lambda r: r["FS"])
    crit = pool[0] if pool else best
    sl = model.slices(crit["xc"], crit["yc"], crit["R"], crit["xl"], crit["xr"], n_sl)
    others: List[Dict[str, Any]] = []
    for cand in pool[1:]:
        if all(abs(cand["xc"] - o["xc"]) + abs(cand["yc"] - o["yc"]) + abs(cand["R"] - o["R"]) > 0.15 * span for o in [crit] + others):
            others.append(cand)
        if len(others) == 4:
            break

    fs, fs_o = crit["FS"], crit["FS_ord"]
    status = classify(fs, kh > 0)
    notes = [
        "Simplified Bishop: moment equilibrium about the circle centre with vertical slice equilibrium; interslice shear ignored.",
        "Ordinary method of slices (Fellenius) shown for comparison; it is usually lower than Bishop.",
        "Grid search: centres on a 10 × 10 grid refined around the minimum; for each centre, radii from just below the crest down to the depth limit and the circle through the toe.",
        "Required FS after SNI 8460:2017: 1.25 to ≥ 2.0 by the uncertainty and the cost of failure; 1.5 is usual for permanent slopes, 1.1 under the seismic load.",
    ]
    if phreatic is not None:
        notes.append("Pore pressure from the phreatic line: u = γw × vertical depth below the line (hydrostatic).")
    elif ru > 0:
        notes.append("Pore pressure from ru: u = ru × vertical total stress at the slice base.")
    if kh > 0:
        notes.append("Pseudo-static: kh·W acts horizontally at each slice centroid, out of the slope; surcharge inertia ignored.")
    if q > 0:
        notes.append("Surcharge acts on the crest from the given distance behind the crest edge to the right.")
    if crit.get("low"):
        notes.append("Some slices of the critical circle have m_α < 0.2 (steep base near the toe); Bishop may be unreliable there; check with another method.")
    if crit["yc"] - crit["R"] <= y_floor + 0.02 * H:
        notes.append("The critical circle reaches the depth limit; deeper slips may be more critical. Increase the depth limit if the ground allows it.")
    near_edge = crit["xc"] <= gx0 + 1e-6 or crit["xc"] >= gx1 - 1e-6 or crit["yc"] >= gy1 - 1e-6
    if near_edge:
        notes.append("The critical centre is at the edge of the search grid; the true minimum may lie outside it.")
    notes += ["Tension cracks, external water in front of the toe and reinforcement are not modelled.", PRELIMINARY_NOTE]

    slice_rows = [[i + 1, s["x"], s["b"], s["h"], math.degrees(s["alpha"]), s["W"], s["u"], s["c"], s["phi"],
                   math.cos(s["alpha"]) + math.sin(s["alpha"]) * s["tanphi"] / fs] for i, s in enumerate(sl)]
    circle_rows = [[k + 1, r["xc"], r["yc"], r["R"], r["FS"], r["FS_ord"], r["xl"], r["xr"]] for k, r in enumerate([crit] + others)]
    grid_rows: List[List[Any]] = [[gys[j]] + [rnd(grid[(i, j)], 3) if (i, j) in grid else None for i in range(nx)] for j in reversed(range(ny))]
    tables = [
        calcbase.table("Critical and next circles", ["No.", "Centre x (m)", "Centre y (m)", "Radius R (m)", "FS Bishop", "FS ordinary", "Entry x (m)", "Exit x (m)"],
                       circle_rows, key=["No.", "FS Bishop", "FS ordinary"]),
        calcbase.table("Minimum FS for each grid centre (Bishop)", ["Centre y (m) / x (m)"] + [f"{x:.1f}" for x in gxs], grid_rows),
        calcbase.table("Slices of the critical circle", ["Slice", "x (m)", "b (m)", "h (m)", "α (°)", "W (kN/m)", "u (kPa)", "c' (kPa)", "φ' (°)", "m_α"],
                       slice_rows, key=["Slice", "α (°)", "W (kN/m)", "u (kPa)"]),
    ]
    grid_pts = [[rnd(gxs[i], 4), rnd(gys[j], 4), rnd(v, 4)] for (i, j), v in grid.items()]
    charts = [{"title": "Minimum FS of the grid centres", "kind": "value", "x": calcbase.axis("Centre x (m)"),
               "y": calcbase.axis("Centre y (m)"), "points": grid_pts, "value_label": "FS Bishop"}]

    section = _section(model, ground, layers, phreatic, crit, others, sl, y_floor, q, x_crest + q_off, gxs, gys)
    out = calcbase.result(
        summary=[("FS Bishop", rnd(fs, 3), ""), ("FS ordinary", rnd(fs_o, 3), ""), ("Required FS", req, "")],
        values=[("Slope height H", rnd(H, 4), "m"), ("Critical centre x", rnd(crit["xc"], 4), "m"), ("Critical centre y", rnd(crit["yc"], 4), "m"),
                ("Radius R", rnd(crit["R"], 4), "m"), ("Entry x", rnd(crit["xl"], 4), "m"), ("Exit x", rnd(crit["xr"], 4), "m"),
                ("Circles tried", len(found), ""), ("Search time", rnd(elapsed, 2), "s"), ("Class", status, "")],
        tables=tables, charts=charts, notes=notes,
        method="Simplified Bishop (1955) circular slip with grid search; ordinary method of slices for comparison")
    out["section"] = section
    out["checks"] = [{"check": "Factor of safety (Bishop)", "case": "Seismic" if kh > 0 else "Static", "value": rnd(fs, 3), "unit": "",
                      "required": f"≥ {req:g}", "ok": fs >= req}]
    out["standards"] = [list(s) for s in STANDARDS]
    out["status"] = "pass" if fs >= req else "fail"
    out["classification"] = status
    return out


def _r(v: float) -> float:
    return round(v, 3)


def _section(model: Model, ground: List[Point], layers: List[Dict[str, float]], phreatic: Optional[List[Point]],
             crit: Dict[str, Any], others: List[Dict[str, Any]], sl: List[Dict[str, float]], y_floor: float,
             q: float, q_from: float, gxs: List[float], gys: List[float]) -> Dict[str, Any]:
    x0, x1 = ground[0][0], ground[-1][0]
    y_min = min(min(p[1] for p in ground), crit["yc"] - crit["R"], y_floor) - 1.0
    polys: List[Dict[str, Any]] = []
    top_limit = max(p[1] for p in ground) + 1.0
    for k, layer in enumerate(layers):
        top = top_limit if k == 0 else layers[k - 1]["bottom"]
        bot = max(layer["bottom"], y_min)
        if top <= bot:
            continue
        xs = {x0, x1} | {p[0] for p in ground}
        for (ax, ay), (bx, by) in zip(ground, ground[1:]):
            for level in (top, bot):
                if (ay - level) * (by - level) < 0:
                    xs.add(ax + (level - ay) / (by - ay) * (bx - ax))
        upper = [(x, min(max(model.y_ground(x), bot), top)) for x in sorted(xs)]
        pts = [[_r(x), _r(y)] for x, y in upper] + [[_r(x1), _r(bot)], [_r(x0), _r(bot)]]
        polys.append({"role": f"layer{k % 5}", "points": pts})
    lines: List[Dict[str, Any]] = [{"role": "ground", "points": [[_r(x), _r(y)] for x, y in ground]}]
    if phreatic is not None:
        lines.append({"role": "water", "points": [[_r(x), _r(y)] for x, y in phreatic]})

    def arc(c: Dict[str, Any], steps: int = 48) -> List[List[float]]:
        a0 = math.atan2(model.y_ground(c["xl"]) - c["yc"], c["xl"] - c["xc"])
        a1 = math.atan2(model.y_ground(c["xr"]) - c["yc"], c["xr"] - c["xc"])
        return [[_r(c["xc"] + c["R"] * math.cos(a0 + (a1 - a0) * k / steps)), _r(c["yc"] + c["R"] * math.sin(a0 + (a1 - a0) * k / steps))]
                for k in range(steps + 1)]

    for o in others:
        lines.append({"role": "circle2", "points": arc(o)})
    for s in sl[::1]:
        lines.append({"role": "slice", "points": [[_r(s["x"] - s["b"] / 2), _r(s["yb"])], [_r(s["x"] - s["b"] / 2), _r(model.y_ground(s["x"] - s["b"] / 2))]]})
    lines.append({"role": "circle", "points": arc(crit)})
    lines.append({"role": "radius", "points": [[_r(crit["xc"]), _r(crit["yc"])], arc(crit)[0]]})
    lines.append({"role": "radius", "points": [[_r(crit["xc"]), _r(crit["yc"])], arc(crit)[-1]]})
    marks = [{"role": "centre", "at": [_r(crit["xc"]), _r(crit["yc"])]}]
    marks += [{"role": "grid", "at": [_r(x), _r(y)]} for x in gxs for y in gys]
    arrows: List[Dict[str, Any]] = []
    if q > 0:
        for k in range(4):
            x = q_from + (x1 - q_from) * (k + 0.5) / 4
            if x < x1:
                y = model.y_ground(x)
                arrows.append({"role": "load", "from": [_r(x), _r(y + 1.2)], "to": [_r(x), _r(y)], "label": "q" if k == 0 else "",
                               "value": q if k == 0 else None, "unit": "kPa"})
    labels = [{"at": [_r(crit["xc"]), _r(crit["yc"])], "text": f"FS = {crit['FS']:.3f}"}]
    return {"polygons": polys, "lines": lines, "marks": marks, "arrows": arrows, "labels": labels}


def analyse(inputs: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(inputs.get("mode") or "circular")
    if mode == "infinite":
        return _infinite(inputs)
    if mode == "circular":
        return _circular(inputs)
    raise CalcError("Choose the infinite slope or the circular slip method")
