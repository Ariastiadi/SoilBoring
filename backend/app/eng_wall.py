"""Retaining wall stability (cantilever or gravity wall), static and pseudo-static seismic.

Pure Python, SI units: m, kPa, kN/m3, forces and moments per metre run of wall.

Geometry: x = 0 at the toe tip, y = 0 at the underside of the base. The base slab spans
0..B with B = toe + stem bottom thickness + heel. The stem stands on the base; its back
face may be battered (back_batter > 0, typical of gravity walls), its front face takes up
the rest of the taper.

Earth pressure acts on a "pressure plane":
* Rankine: the vertical plane through the heel end, from the base underside up to the
  sloping ground surface (Das, Principles of Foundation Engineering, retaining wall chapter).
  The soil between the stem and this plane moves with the wall. With c' > 0 the active
  pressure behind sloping ground follows Mazindrani & Ganjali (1997); tension is set to zero.
* Coulomb: the plane from the heel corner (base underside) to the top of the stem back,
  with wall friction delta; c' is ignored (conservative).
Seismic: Mononobe-Okabe active coefficient K_AE; the increment over the static thrust acts
at 0.6 H (Seed & Whitman 1970); wall and soil-on-wall inertia kh*W, weights times (1 - kv).
Bearing: Meyerhof general equation with Hansen depth and Meyerhof inclination factors on
the effective width B' = B - 2e (Das), or the allowable pressure the user enters.
All results are preliminary and must be checked by a geotechnical engineer.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import calcbase
from .calcbase import CalcError, rnd
from .engineering import GAMMA_W, PRELIMINARY_NOTE, bearing_capacity_factors

Point = Tuple[float, float]

STANDARDS: List[Tuple[str, str]] = [
    ("SNI 8460:2017", "Geotechnical design requirements"),
    ("Das (2011)", "Principles of Foundation Engineering: lateral earth pressure and retaining walls"),
    ("Mazindrani & Ganjali (1997)", "Lateral earth pressure of c'–φ' soil behind sloping ground"),
    ("Mononobe–Okabe; Seed & Whitman (1970)", "Seismic active earth pressure and its line of action"),
    ("Kramer (1996)", "Geotechnical Earthquake Engineering: pseudo-static retaining wall design"),
]

# Required values: (static, seismic). Common practice; the user may change them.
REQUIRED = {
    "overturning": (2.0, 1.5),
    "sliding": (1.5, 1.1),
    "bearing": (3.0, 2.0),
    "ecc_div": (6.0, 4.0),  # e <= B / n
}


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def poly_area_centroid(points: Sequence[Point]) -> Tuple[float, float, float]:
    """Area and centroid (shoelace) of a simple polygon; area >= 0."""
    a = cx = cy = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    a *= 0.5
    if abs(a) < 1e-12:
        return 0.0, 0.0, 0.0
    return abs(a), cx / (6 * a), cy / (6 * a)


def clip_below(points: Sequence[Point], level: float, keep_below: bool = True) -> List[Point]:
    """Part of a polygon below (or above) a horizontal line (Sutherland-Hodgman)."""
    def inside(p: Point) -> bool:
        return p[1] <= level if keep_below else p[1] >= level

    out: List[Point] = []
    n = len(points)
    for i in range(n):
        cur, nxt = points[i], points[(i + 1) % n]
        if inside(cur):
            out.append(cur)
        if inside(cur) != inside(nxt):
            t = (level - cur[1]) / (nxt[1] - cur[1])
            out.append((cur[0] + t * (nxt[0] - cur[0]), level))
    return out


# ---------------------------------------------------------------------------
# Earth pressure coefficients
# ---------------------------------------------------------------------------

def rankine_ka(phi_deg: float, beta_deg: float = 0.0) -> float:
    """Rankine active coefficient for a vertical wall and backfill sloping at beta (c' = 0).
    The thrust 0.5 gamma H^2 Ka acts parallel to the ground surface."""
    phi, beta = math.radians(phi_deg), math.radians(beta_deg)
    if beta_deg >= phi_deg:
        raise CalcError("The backfill slope β must be smaller than φ'")
    s = math.sqrt(max(0.0, math.cos(beta) ** 2 - math.cos(phi) ** 2))
    return math.cos(beta) * (math.cos(beta) - s) / (math.cos(beta) + s)


def rankine_kp(phi_deg: float) -> float:
    return math.tan(math.radians(45.0 + phi_deg / 2.0)) ** 2


def mazindrani_ka(phi_deg: float, beta_deg: float, c: float, sigma_v: float) -> float:
    """Rankine active coefficient Ka' of a c'-phi' soil behind sloping ground at vertical stress
    sigma_v (Mazindrani & Ganjali 1997, as given by Das). Active pressure = sigma_v Ka' cos(beta),
    which may come out negative (tension) near the surface."""
    phi, beta = math.radians(phi_deg), math.radians(beta_deg)
    if sigma_v <= 1e-9:
        return -math.inf if c > 0 else rankine_ka(phi_deg, beta_deg) / math.cos(beta)
    r = c / sigma_v
    cb2, cp, sp = math.cos(beta) ** 2, math.cos(phi), math.sin(phi)
    root = 4 * cb2 * (cb2 - cp ** 2) + 4 * r * r * cp ** 2 + 8 * r * cb2 * sp * cp
    return (2 * cb2 + 2 * r * cp * sp - math.sqrt(max(0.0, root))) / cp ** 2 - 1.0


def coulomb_ka(phi_deg: float, delta_deg: float, theta_deg: float, alpha_deg: float) -> float:
    """Coulomb active coefficient (Das). theta = back face from vertical, positive when the face
    leans back under the backfill; alpha = backfill slope; delta = wall friction.
    Thrust 0.5 gamma H^2 Ka (H vertical) at delta + theta below the horizontal."""
    return mononobe_okabe_kae(phi_deg, delta_deg, theta_deg, alpha_deg, 0.0, 0.0)


def mononobe_okabe_kae(phi_deg: float, delta_deg: float, theta_deg: float, alpha_deg: float,
                       kh: float, kv: float = 0.0) -> float:
    """Mononobe-Okabe seismic active coefficient (Kramer 1996; Das). PAE = 0.5 gamma H^2 (1 - kv) KAE."""
    phi, delta, theta, alpha = (math.radians(v) for v in (phi_deg, delta_deg, theta_deg, alpha_deg))
    if kv >= 1:
        raise CalcError("kv must be smaller than 1")
    psi = math.atan(kh / (1.0 - kv))
    if phi - alpha - psi < -1e-12:
        raise CalcError("The seismic coefficient is too large for this backfill: φ' − β − atan(kh/(1 − kv)) must not be negative")
    num = math.cos(phi - theta - psi) ** 2
    den_a = math.cos(psi) * math.cos(theta) ** 2 * math.cos(delta + theta + psi)
    inner = (math.sin(phi + delta) * math.sin(max(0.0, phi - alpha - psi))) / (
        math.cos(delta + theta + psi) * math.cos(alpha - theta))
    return num / (den_a * (1.0 + math.sqrt(max(0.0, inner))) ** 2)


# ---------------------------------------------------------------------------
# Bearing capacity of the base (Das: Meyerhof with depth and inclination factors)
# ---------------------------------------------------------------------------

def base_bearing(*, c: float, phi_deg: float, gamma: float, depth: float, b_eff: float, incl_deg: float) -> Dict[str, float]:
    f = bearing_capacity_factors(phi_deg)
    nc, nq, ng = f["Nc"], f["Nq"], f["Ngamma"]
    phi = math.radians(phi_deg)
    ratio = depth / b_eff
    k = ratio if ratio <= 1 else math.atan(ratio)
    fqd = 1 + 2 * math.tan(phi) * (1 - math.sin(phi)) ** 2 * k
    fcd = 1 + 0.4 * k if phi_deg == 0 else fqd - (1 - fqd) / (nc * math.tan(phi))
    fci = (1 - incl_deg / 90.0) ** 2
    fgi = 0.0 if phi_deg == 0 or incl_deg >= phi_deg else (1 - incl_deg / phi_deg) ** 2
    q = gamma * depth
    qu = c * nc * fcd * fci + q * nq * fqd * fci + 0.5 * gamma * b_eff * ng * fgi
    return {"qu": qu, "Nc": nc, "Nq": nq, "Ngamma": ng, "Fcd": fcd, "Fqd": fqd, "Fci": fci, "Fgi": fgi, "q": q}


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyse(inputs: Dict[str, Any]) -> Dict[str, Any]:
    method = str(inputs.get("method") or "rankine")
    if method not in ("rankine", "coulomb"):
        raise CalcError("Choose Rankine or Coulomb")
    wall_type = str(inputs.get("wall_type") or "cantilever")
    H = _need(inputs, "H", "Wall height H", lo=0.5, hi=30)
    toe = _need(inputs, "toe", "Toe length", 0.0, lo=0, hi=20)
    heel = _need(inputs, "heel", "Heel length", 0.0, lo=0, hi=30)
    t_top = _need(inputs, "t_top", "Stem thickness at the top", lo=0.1, hi=10)
    t_bot = _need(inputs, "t_bot", "Stem thickness at the base", lo=0.1, hi=20)
    batter = _need(inputs, "back_batter", "Back face batter", 0.0, lo=0, hi=20)
    D = _need(inputs, "D_base", "Base thickness", lo=0.1, hi=5)
    gc = _need(inputs, "gamma_c", "Concrete unit weight", 24.0, lo=15, hi=30)
    gamma = _need(inputs, "gamma", "Backfill unit weight γ", lo=10, hi=25)
    gamma_sat = _need(inputs, "gamma_sat", "Backfill saturated unit weight γsat", gamma + 1.0, lo=GAMMA_W + 0.1, hi=26)
    phi = _need(inputs, "phi", "Backfill friction angle φ'", lo=10, hi=50)
    c = _need(inputs, "c", "Backfill cohesion c'", 0.0, lo=0, hi=200)
    beta = _need(inputs, "beta", "Backfill slope β", 0.0, lo=0, hi=45)
    delta = _need(inputs, "delta", "Wall friction δ", round(2 * phi / 3, 2), lo=0, hi=phi)
    q = _need(inputs, "q", "Surcharge q", 0.0, lo=0, hi=500)
    gw = _val(inputs, "gw", "Groundwater depth behind the wall", required=False, lo=0)
    phi2 = _need(inputs, "found_phi", "Foundation friction angle φ'", lo=0, hi=50)
    c2 = _need(inputs, "found_c", "Foundation cohesion c'", 0.0, lo=0, hi=500)
    gamma2 = _need(inputs, "found_gamma", "Foundation unit weight γ", lo=10, hi=25)
    d_front = _need(inputs, "D_front", "Depth of the base below the ground in front", D, lo=0, hi=10)
    q_allow = _val(inputs, "q_allow", "Allowable bearing pressure", required=False, lo=1)
    passive = str(inputs.get("passive") or "no") == "yes"
    kh = _need(inputs, "kh", "Seismic coefficient kh", 0.0, lo=0, hi=0.6)
    kv = _need(inputs, "kv", "Vertical seismic coefficient kv", 0.0, lo=-0.3, hi=0.3)
    req = {
        "overturning": (_need(inputs, "fs_ot", "Required FS overturning", REQUIRED["overturning"][0], lo=1, hi=5),
                        _need(inputs, "fs_ot_eq", "Required FS overturning, seismic", REQUIRED["overturning"][1], lo=1, hi=5)),
        "sliding": (_need(inputs, "fs_sl", "Required FS sliding", REQUIRED["sliding"][0], lo=1, hi=5),
                    _need(inputs, "fs_sl_eq", "Required FS sliding, seismic", REQUIRED["sliding"][1], lo=1, hi=5)),
        "bearing": (_need(inputs, "fs_bc", "Required FS bearing", REQUIRED["bearing"][0], lo=1, hi=6),
                    _need(inputs, "fs_bc_eq", "Required FS bearing, seismic", REQUIRED["bearing"][1], lo=1, hi=6)),
    }

    if t_bot < t_top - 1e-9:
        raise CalcError("The stem must not be thinner at the base than at the top")
    if t_top + batter > t_bot + 1e-9:
        raise CalcError("Stem top thickness plus back batter cannot exceed the stem base thickness")
    if H <= D + 0.2:
        raise CalcError("Wall height H must exceed the base thickness")
    if beta >= phi:
        raise CalcError("The backfill slope β must be smaller than φ'")
    if c2 == 0 and phi2 == 0:
        raise CalcError("Enter the strength of the foundation soil (φ' or c')")

    notes: List[str] = []
    B = toe + t_bot + heel
    tb = math.tan(math.radians(beta))
    x_back0 = toe + t_bot            # stem back face at the base top
    x_bt = x_back0 - batter          # stem back face at the top
    x_ft = x_bt - t_top              # stem front face at the top
    y_w = None if gw is None else H - gw  # water level, elevation above the base underside
    if y_w is not None and y_w <= 0:
        y_w = None
        notes.append("Groundwater is below the base; no water pressure or uplift.")

    def surface(x: float) -> float:
        return H + max(0.0, x - x_bt) * tb

    # --- Bodies that move with the wall: concrete and the soil between the stem and the pressure plane.
    bodies: List[Dict[str, Any]] = []

    def add(name: str, pts: List[Point], unit: float, unit_wet: Optional[float] = None, kind: str = "concrete") -> None:
        if unit_wet is not None and y_w is not None:
            parts = [(clip_below(pts, y_w, False), unit), (clip_below(pts, y_w, True), unit_wet)]
        else:
            parts = [(pts, unit)]
        area = w = mx = my = 0.0
        for poly, uw in parts:
            if len(poly) < 3:
                continue
            a, cx, cy = poly_area_centroid(poly)
            area += a
            w += a * uw
            mx += a * uw * cx
            my += a * uw * cy
        if w > 1e-9:
            bodies.append({"name": name, "area": area, "W": w, "x": mx / w, "y": my / w, "kind": kind, "pts": pts})

    add("Stem", [(toe, D), (x_back0, D), (x_bt, H), (x_ft, H)], gc)
    add("Base", [(0.0, 0.0), (B, 0.0), (B, D), (0.0, D)], gc)
    if method == "rankine":
        plane_top = surface(B)
        Hp = plane_top
        theta = 0.0
        soil = [(x_back0, D), (B, D), (B, H), (x_bt, H)]
        add("Soil above the heel", soil, gamma, gamma_sat, "soil")
        if beta > 0 and B > x_bt:
            add("Sloping backfill above the wall top", [(x_bt, H), (B, H), (B, plane_top)], gamma, gamma_sat, "soil")
        plane = [(B, 0.0), (B, plane_top)]
    else:
        Hp = H
        theta = math.degrees(math.atan2(B - x_bt, H))
        x_at_D = B - (B - x_bt) * D / H
        wedge = [(x_back0, D), (x_at_D, D), (x_bt, H)]
        if x_at_D > x_back0 + 1e-6:
            add("Soil between the stem and the pressure plane", wedge, gamma, gamma_sat, "soil")
        plane = [(B, 0.0), (x_bt, H)]
        if c > 0:
            notes.append("Coulomb: the backfill cohesion c' is ignored (conservative).")
        if theta > 0.5:
            notes.append("Coulomb: thrust on the plane from the heel corner to the top of the stem back; the soil inside it moves with the wall.")

    # --- Active pressure along the plane (depth z below the plane top, vertical).
    zw = None if y_w is None else Hp - y_w
    gamma_sub = gamma_sat - GAMMA_W

    def sigma_v(z: float) -> float:
        if zw is None or z <= zw:
            return q + gamma * z
        return q + gamma * zw + gamma_sub * (z - zw)

    k_static_c0 = rankine_ka(phi, beta) if method == "rankine" else coulomb_ka(phi, delta, theta, beta)

    def sigma_a(z: float) -> float:
        sv = sigma_v(z)
        if method == "rankine":
            if c > 0:
                return max(0.0, sv * mazindrani_ka(phi, beta, c, sv) * math.cos(math.radians(beta)))
            return sv * k_static_c0
        return sv * k_static_c0

    n = 400
    dz = Hp / n
    zs = [i * dz for i in range(n + 1)]
    sig = [sigma_a(z) for z in zs]
    Pa = sum((sig[i] + sig[i + 1]) / 2 * dz for i in range(n))
    Ma = sum((sig[i] + sig[i + 1]) / 2 * dz * (Hp - (zs[i] + zs[i + 1]) / 2) for i in range(n))
    ya = Ma / Pa if Pa > 1e-9 else Hp / 3
    if c > 0 and method == "rankine":
        crack = next((z for z, s in zip(zs, sig) if s > 1e-6), Hp)
        if crack > 1e-6:
            notes.append("Tension zone at the top of the backfill: active pressure set to zero there (no tension).")
    else:
        crack = 0.0
    eps = math.radians(beta if method == "rankine" else theta + delta)

    def plane_x(y: float) -> float:
        if method == "rankine":
            return B
        return B - (B - x_bt) * y / H

    Ph, Pv = Pa * math.cos(eps), Pa * math.sin(eps)
    xa = plane_x(ya)

    # Water on the plane and uplift under the base (no water in front of the wall).
    Uw = Uwv = yu = U = 0.0
    if zw is not None and zw < Hp:
        hw = Hp - zw
        Uw = 0.5 * GAMMA_W * hw * hw
        yu = hw / 3
        Uwv = Uw * math.tan(math.radians(theta)) if method == "coulomb" else 0.0
        U = 0.5 * GAMMA_W * min(hw, Hp) * B
        notes.append("Groundwater behind the wall: water thrust on the plane and triangular uplift under the base (no water in front) are included.")

    # Static horizontal and vertical forces about the toe.
    Wt = sum(b["W"] for b in bodies)
    MR_w = sum(b["W"] * b["x"] for b in bodies)
    sumV = Wt + Pv + Uwv - U
    MR = MR_w + Pv * xa + Uwv * plane_x(yu)
    MO = Ph * ya + Uw * yu + U * 2 * B / 3
    sumH = Ph + Uw

    kp = rankine_kp(phi2)
    Pp = 0.5 * kp * gamma2 * d_front ** 2 + 2 * c2 * math.sqrt(kp) * d_front if passive else 0.0
    k1 = k2 = 2.0 / 3.0

    def checks(sum_v: float, mr: float, mo: float, sum_h: float, case: int) -> Dict[str, Any]:
        fs_ot = mr / mo if mo > 1e-9 else math.inf
        resist = max(0.0, sum_v) * math.tan(math.radians(k1 * phi2)) + B * k2 * c2 + Pp
        fs_sl = resist / sum_h if sum_h > 1e-9 else math.inf
        x_r = (mr - mo) / sum_v if sum_v > 1e-9 else -1.0
        e = B / 2 - x_r
        if sum_v <= 0 or x_r <= 0 or e >= B / 2:
            q_max, q_min, qu, fs_bc, incl = math.inf, 0.0, 0.0, 0.0, 90.0
            overturned = True
        else:
            overturned = False
            if abs(e) <= B / 6:
                q_max = sum_v / B * (1 + 6 * abs(e) / B)
                q_min = sum_v / B * (1 - 6 * abs(e) / B)
            else:
                q_max = 2 * sum_v / (3 * (B / 2 - abs(e)))
                q_min = 0.0
            incl = math.degrees(math.atan2(sum_h, sum_v))
            bear = base_bearing(c=c2, phi_deg=phi2, gamma=gamma2, depth=d_front, b_eff=B - 2 * abs(e), incl_deg=incl)
            qu = bear["qu"]
            fs_bc = qu / q_max if q_max > 0 else math.inf
        return {"fs_ot": fs_ot, "fs_sl": fs_sl, "resist": resist, "e": e, "x_r": x_r, "q_max": q_max, "q_min": q_min,
                "qu": qu, "fs_bc": fs_bc, "incl": incl, "overturned": overturned, "case": case}

    static = checks(sumV, MR, MO, sumH, 0)

    seismic: Optional[Dict[str, Any]] = None
    kae = d_pae = d_pae_h = d_pae_v = 0.0
    inertia_h = inertia_m = 0.0
    if kh > 0 or kv != 0:
        kae = mononobe_okabe_kae(phi, beta if method == "rankine" else delta, theta, beta, kh, kv)
        soil_part = sum((sigma_v(zs[i]) - q + sigma_v(zs[i + 1]) - q) / 2 * dz for i in range(n))  # = 0.5 gamma_eq Hp^2
        d_pae = max(0.0, ((1 - kv) * kae - k_static_c0) * (soil_part + q * Hp))
        d_pae_h, d_pae_v = d_pae * math.cos(eps), d_pae * math.sin(eps)
        y_d = 0.6 * Hp
        x_d = plane_x(y_d)
        inertia_h = sum(kh * b["W"] for b in bodies)
        inertia_m = sum(kh * b["W"] * b["y"] for b in bodies)
        sumV_e = Wt * (1 - kv) + Pv + d_pae_v + Uwv - U
        MR_e = MR_w * (1 - kv) + Pv * xa + d_pae_v * x_d + Uwv * plane_x(yu)
        MO_e = MO + d_pae_h * y_d + inertia_m
        sumH_e = sumH + d_pae_h + inertia_h
        seismic = checks(sumV_e, MR_e, MO_e, sumH_e, 1)
        seismic.update({"sumV": sumV_e, "MR": MR_e, "MO": MO_e, "sumH": sumH_e})
        if c > 0:
            notes.append("Seismic increment from Mononobe–Okabe without cohesion (conservative).")
        if zw is not None:
            notes.append("Seismic increment uses the average effective unit weight; hydrodynamic water pressure is not included.")

    # --- Checks with required values.
    rows: List[List[Any]] = []
    flags: List[Dict[str, Any]] = []

    def add_check(name: str, case: int, value: float, required: float, ok: bool, unit: str = "", req_text: Optional[str] = None) -> None:
        label_case = "Seismic" if case else "Static"
        shown = rnd(value, 3) if math.isfinite(value) else None
        rows.append([name, label_case, shown if shown is not None else "∞", req_text or f"≥ {required:g}", "OK" if ok else "Not OK"])
        flags.append({"check": name, "case": label_case, "value": shown, "unit": unit,
                      "required": req_text or f"≥ {required:g}", "ok": ok})

    for res in [static] + ([seismic] if seismic else []):
        i = res["case"]
        add_check("Overturning FS", i, res["fs_ot"], req["overturning"][i], res["fs_ot"] >= req["overturning"][i])
        add_check("Sliding FS", i, res["fs_sl"], req["sliding"][i], res["fs_sl"] >= req["sliding"][i])
        div = REQUIRED["ecc_div"][i]
        lim = B / div
        add_check("Eccentricity e (m)", i, abs(res["e"]) if not res["overturned"] else math.inf, lim,
                  not res["overturned"] and abs(res["e"]) <= lim + 1e-9, "m", f"≤ B/{div:g} = {rnd(lim, 3):g}")
        if not res["overturned"]:
            add_check("Bearing FS = qu / q_max", i, res["fs_bc"], req["bearing"][i], res["fs_bc"] >= req["bearing"][i])
            if q_allow is not None:
                add_check("q_max (kPa)", i, res["q_max"], q_allow, res["q_max"] <= q_allow + 1e-9, "kPa", f"≤ q_allow = {q_allow:g}")
        else:
            add_check("Bearing FS = qu / q_max", i, 0.0, req["bearing"][i], False)
    all_ok = all(f["ok"] for f in flags)
    if static["overturned"]:
        notes.insert(0, "The resultant falls outside the base: the wall overturns. Widen the base or lengthen the heel.")
    elif abs(static["e"]) > B / 6:
        notes.append("e > B/6: part of the base lifts off; q_max = 2ΣV / (3(B/2 − e)).")

    # --- Tables.
    weight_rows = [[b["name"], b["area"], b["W"], b["x"], b["W"] * b["x"]] for b in bodies]
    weight_rows.append(["Earth thrust, vertical component Pv", None, Pv, xa, Pv * xa])
    if Uwv:
        weight_rows.append(["Water thrust, vertical component", None, Uwv, plane_x(yu), Uwv * plane_x(yu)])
    if U:
        weight_rows.append(["Uplift under the base", None, -U, 2 * B / 3, None])
    weight_rows.append(["Total", None, sumV, None, MR])
    force_rows = [["Earth thrust, horizontal component Ph", Ph, ya, Ph * ya]]
    if Uw:
        force_rows.append(["Water thrust on the plane", Uw, yu, Uw * yu])
    if U:
        force_rows.append(["Uplift under the base", None, None, U * 2 * B / 3])
    force_rows.append(["Total, static", sumH, None, MO])
    if seismic:
        force_rows.append(["Seismic increment ΔPAE, horizontal", d_pae_h, 0.6 * Hp, d_pae_h * 0.6 * Hp])
        force_rows.append(["Inertia of the wall and soil on it, kh·W", inertia_h, inertia_m / inertia_h if inertia_h else None, inertia_m])
        force_rows.append(["Total, seismic", seismic["sumH"], None, seismic["MO"]])
    tables = [
        calcbase.table("Vertical forces and resisting moments about the toe", ["Item", "Area (m²/m)", "Force (kN/m)", "Arm from toe (m)", "Moment (kN·m/m)"],
                       weight_rows, key=["Item", "Force (kN/m)", "Moment (kN·m/m)"]),
        calcbase.table("Horizontal forces and overturning moments about the toe", ["Item", "Force (kN/m)", "Height above base (m)", "Moment (kN·m/m)"],
                       force_rows, key=["Item", "Force (kN/m)", "Moment (kN·m/m)"]),
    ]

    # --- Charts: horizontal pressure with depth.
    hp_scale = math.cos(eps)
    pts_soil = [(s * hp_scale, z) for z, s in zip(zs, sig)][::10] + [(sig[-1] * hp_scale, Hp)]
    series = [calcbase.series("Active earth pressure, horizontal", pts_soil, "line")]
    if zw is not None and zw < Hp:
        series.append(calcbase.series("Water pressure", [(0.0, zw), (GAMMA_W * (Hp - zw), Hp)], "line", dash=True))
    if seismic and d_pae > 0:
        # Seed & Whitman increment as an inverted triangle (resultant at 0.6 H).
        top = 2 * d_pae_h / Hp * 1.0
        series.append(calcbase.series("Seismic increment (inverted triangle)", [(top * (1 - z / Hp) + s * hp_scale, z) for z, s in zip(zs[::20], sig[::20])], "line", dash=True))
    charts = [calcbase.chart("Lateral pressure on the pressure plane", calcbase.axis("Horizontal pressure (kPa)"),
                             calcbase.axis("Depth below the top of the plane (m)", reverse=True), *series)]

    # --- Section drawing (equal scale; drawn by the interface).
    section = _section(bodies, B, D, H, x_bt, beta, d_front, plane, Hp, zs, sig, hp_scale, y_w, static, Ph, Pv, xa, ya, Wt, method)

    # --- Values.
    values: List[Tuple[str, Any, str]] = [
        ("Base width B", rnd(B, 4), "m"), ("Height of the pressure plane", rnd(Hp, 4), "m"),
        ("Ka (c' = 0)" if method == "rankine" else "Ka (Coulomb)", rnd(k_static_c0, 4), ""),
        ("Kp (foundation soil)", rnd(kp, 4), ""),
        ("Active thrust Pa", rnd(Pa, 4), "kN/m"), ("Ph", rnd(Ph, 4), "kN/m"), ("Pv", rnd(Pv, 4), "kN/m"),
        ("Pa acts above the base underside at", rnd(ya, 4), "m"),
        ("Passive resistance Pp", rnd(Pp, 4) if passive else None, "kN/m"),
        ("ΣV", rnd(sumV, 4), "kN/m"), ("ΣM resisting", rnd(MR, 4), "kN·m/m"), ("ΣM overturning", rnd(MO, 4), "kN·m/m"),
        ("Eccentricity e", rnd(static["e"], 3), "m"), ("B/6", rnd(B / 6, 3), "m"),
        ("q_max (toe)", rnd(static["q_max"], 4) if math.isfinite(static["q_max"]) else None, "kPa"),
        ("q_min (heel)", rnd(static["q_min"], 4), "kPa"),
        ("Load inclination ψ", rnd(static["incl"], 3), "°"),
        ("Ultimate bearing capacity qu", rnd(static["qu"], 4), "kPa"),
    ]
    if method == "coulomb":
        values.insert(2, ("Plane inclination from vertical θ", rnd(theta, 3), "°"))
        values.insert(3, ("Wall friction δ", rnd(delta, 3), "°"))
    if crack > 1e-6:
        values.append(("Depth of the tension zone", rnd(crack, 3), "m"))
    if seismic:
        values += [("K_AE (Mononobe–Okabe)", rnd(kae, 4), ""), ("ΔPAE", rnd(d_pae, 4), "kN/m"),
                   ("Overturning FS, seismic", rnd(seismic["fs_ot"], 3), ""), ("Sliding FS, seismic", rnd(seismic["fs_sl"], 3), ""),
                   ("Eccentricity e, seismic", rnd(seismic["e"], 3), "m"),
                   ("q_max, seismic", rnd(seismic["q_max"], 4) if math.isfinite(seismic["q_max"]) else None, "kPa")]
    summary: List[Tuple[str, Any, str]] = [
        ("FS overturning", rnd(static["fs_ot"], 3), ""), ("FS sliding", rnd(static["fs_sl"], 3), ""),
        ("e", rnd(static["e"], 3), "m"),
        ("q_max", rnd(static["q_max"], 4) if math.isfinite(static["q_max"]) else None, "kPa"),
        ("FS bearing", rnd(static["fs_bc"], 3), ""),
    ]
    if seismic:
        summary += [("FS overturning, seismic", rnd(seismic["fs_ot"], 3), ""), ("FS sliding, seismic", rnd(seismic["fs_sl"], 3), "")]

    notes += [
        "Sliding resistance: ΣV·tan(2/3·φ'₂) + B·(2/3)·c'₂ (+ Pp when passive resistance is counted), after Das.",
        "Passive resistance in front of the toe is counted." if passive else "Passive resistance in front of the toe is not counted (conservative).",
        "Soil above the toe is ignored (conservative).",
        "Bearing: Meyerhof equation with Hansen depth factors and Meyerhof inclination factors on B' = B − 2e (Das).",
        "Required values: overturning ≥ 2.0, sliding ≥ 1.5, bearing ≥ 3.0, e ≤ B/6 static; ≥ 1.5, ≥ 1.1, ≥ 2.0 and e ≤ B/4 seismic, as common practice with SNI 8460:2017. Change them to the project specification where it differs.",
        "Stem and base structural design (bending, shear, reinforcement) is not part of this check.",
        "Overall stability (a slip surface below the wall) must be checked separately with the slope stability analysis.",
        PRELIMINARY_NOTE,
    ]
    if wall_type == "gravity" and method == "rankine" and heel < 0.05:
        notes.append("Gravity wall without a heel: Coulomb with wall friction is usually more appropriate.")
    out = calcbase.result(summary=summary, values=[v for v in values if v[1] is not None], tables=tables, charts=charts,
                          notes=calcbase_unique(notes),
                          method=("Rankine earth pressure on the vertical plane through the heel" if method == "rankine"
                                  else "Coulomb earth pressure with wall friction") +
                          ("; Mononobe–Okabe seismic increment (Seed & Whitman)" if seismic else "") +
                          "; overturning, sliding and bearing after Das")
    out["section"] = section
    out["checks"] = flags
    out["standards"] = [list(s) for s in STANDARDS]
    out["status"] = "pass" if all_ok else "fail"
    out["summary"] = out["summary"] + ("; Checks = all OK" if all_ok else "; Checks = not OK")
    return out


def calcbase_unique(notes: List[str]) -> List[str]:
    seen: set = set()
    out = []
    for n in notes:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _r(v: float) -> float:
    return round(v, 3)


def _section(bodies: List[Dict[str, Any]], B: float, D: float, H: float, x_bt: float, beta: float, d_front: float,
             plane: List[Point], Hp: float, zs: List[float], sig: List[float], hp_scale: float, y_w: Optional[float],
             res: Dict[str, Any], Ph: float, Pv: float, xa: float, ya: float, Wt: float, method: str) -> Dict[str, Any]:
    tb = math.tan(math.radians(beta))
    far = B + max(1.0, 0.6 * H)
    polys: List[Dict[str, Any]] = []
    for b in bodies:
        polys.append({"role": b["kind"], "points": [[_r(x), _r(y)] for x, y in b["pts"]]})
    lines: List[Dict[str, Any]] = []
    # Ground behind (sloping from the stem top) and in front of the wall.
    lines.append({"role": "ground", "points": [[_r(x_bt), _r(H)], [_r(far), _r(H + (far - x_bt) * tb)]]})
    y_front = d_front
    lines.append({"role": "ground", "points": [[_r(-max(1.0, 0.4 * H)), _r(y_front)], [0.0, _r(y_front)]]})
    lines.append({"role": "plane", "points": [[_r(p[0]), _r(p[1])] for p in plane]})
    if y_w is not None:
        lines.append({"role": "water", "points": [[_r(x_bt), _r(y_w)], [_r(far), _r(y_w)]]})
    # Pressure diagram drawn behind the plane, horizontal component.
    smax = max(sig) * hp_scale if sig else 0.0
    scale = (0.35 * max(B, H) / smax) if smax > 0 else 0.0
    if scale > 0:
        top_y = plane[1][1]
        bottom_x = plane[0][0]
        top_x = plane[1][0]

        def px(y: float) -> float:
            return bottom_x + (top_x - bottom_x) * (y / top_y if top_y else 0)

        pts = [[_r(px(top_y - z) + s * hp_scale * scale), _r(top_y - z)] for z, s in list(zip(zs, sig))[::20]]
        pts.append([_r(px(0) + sig[-1] * hp_scale * scale), 0.0])
        poly = [[_r(top_x), _r(top_y)]] + pts + [[_r(bottom_x), 0.0]]
        polys.append({"role": "pressure", "points": poly})
    arrows: List[Dict[str, Any]] = []
    span = max(B, H)
    if Ph > 0:
        dx = 0.25 * span
        ang = math.atan2(Pv, Ph)
        arrows.append({"role": "force", "label": "Pa", "value": rnd(math.hypot(Ph, Pv), 4), "unit": "kN/m",
                       "from": [_r(xa + dx), _r(ya + dx * math.tan(ang))], "to": [_r(xa), _r(ya)]})
    if Wt > 0:
        wx = sum(b["W"] * b["x"] for b in bodies) / Wt
        arrows.append({"role": "weight", "label": "W", "value": rnd(Wt, 4), "unit": "kN/m",
                       "from": [_r(wx), _r(D + 0.45 * (H - D))], "to": [_r(wx), _r(D + 0.15 * (H - D))]})
    marks: List[Dict[str, Any]] = [{"role": "third", "at": [_r(B / 3), 0.0]}, {"role": "third", "at": [_r(2 * B / 3), 0.0]}]
    if not res["overturned"] and math.isfinite(res["q_max"]) and res["q_max"] > 0:
        qs = 0.25 * span / res["q_max"]
        e = res["e"]
        # Pressure under the base, drawn downward: toe value q_max when e > 0.
        q_toe, q_heel = (res["q_max"], res["q_min"]) if e >= 0 else (res["q_min"], res["q_max"])
        if abs(e) <= B / 6:
            pts_b = [[0.0, 0.0], [0.0, _r(-q_toe * qs)], [_r(B), _r(-q_heel * qs)], [_r(B), 0.0]]
        else:
            length = 3 * (B / 2 - abs(e))
            if e >= 0:
                pts_b = [[0.0, 0.0], [0.0, _r(-q_toe * qs)], [_r(length), 0.0]]
            else:
                pts_b = [[_r(B - length), 0.0], [_r(B), _r(-q_heel * qs)], [_r(B), 0.0]]
        polys.append({"role": "bearing", "points": pts_b})
        marks.append({"role": "resultant", "at": [_r(res["x_r"]), 0.0]})
    labels = [{"at": [_r(B / 2), _r(-0.02 * span)], "text": f"B = {B:.2f} m"}]
    return {"polygons": polys, "lines": lines, "arrows": arrows, "marks": marks, "labels": labels,
            "pressure_max": rnd(smax, 4), "method": method}
