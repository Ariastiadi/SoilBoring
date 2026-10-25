"""Preliminary geotechnical calculations for the SoilBoring app.

Pure Python (standard library only). SI units throughout: lengths in m,
stresses in kPa, unit weights in kN/m3, forces in kN.

Every public function validates its inputs, raises ValueError with a short
English message for impossible input, and returns plain JSON-serialisable
dicts with a "method" string and a "notes" list. All results are preliminary
estimates that must be checked by a geotechnical engineer.
"""
from __future__ import annotations

import math
from typing import Any

GAMMA_W = 9.81  # unit weight of water, kN/m3
PA = 101.325  # atmospheric pressure, kPa
PRELIMINARY_NOTE = (
    "Preliminary estimate only; results must be checked by a qualified geotechnical engineer."
)
_TOL = 1e-9

_CLAY_SYMBOLS = {"CL", "CH", "OL", "OH", "PT"}


# ---------------------------------------------------------------------------
# Small validation and formatting helpers
# ---------------------------------------------------------------------------

def _num(
    name: str,
    value: Any,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
    min_exclusive: bool = False,
) -> float:
    """Return value as a finite float, or raise ValueError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f"{name} must be a finite number")
    if min_value is not None:
        if min_exclusive and x <= min_value:
            raise ValueError(f"{name} must be greater than {min_value:g}")
        if not min_exclusive and x < min_value:
            raise ValueError(f"{name} must be at least {min_value:g}")
    if max_value is not None and x > max_value:
        raise ValueError(f"{name} must be at most {max_value:g}")
    return x


def _r(value: float | None, digits: int) -> float | None:
    """Round for output; keeps None and turns -0.0 into 0.0."""
    if value is None:
        return None
    out = round(value, digits)
    return 0.0 if out == 0 else out


def _uscs(value: Any) -> str:
    """Normalise a USCS group symbol (e.g. ' sp-sm ' -> 'SP-SM')."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("uscs must be a string")
    return value.strip().upper().replace(" ", "").replace("/", "-")


def _unique(notes: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for note in notes:
        if note not in seen:
            seen.add(note)
            out.append(note)
    return out


def _parse_spt(spt: Any) -> list[tuple[float, float]]:
    """Validate an SPT list [{"depth": m, "n": blows}] and sort it by depth."""
    if not isinstance(spt, list) or not spt:
        raise ValueError("spt must be a non-empty list")
    out: list[tuple[float, float]] = []
    for i, row in enumerate(spt):
        if not isinstance(row, dict):
            raise ValueError(f"spt[{i}] must be an object with depth and n")
        depth = _num(f"spt[{i}].depth", row.get("depth"), min_value=0.0)
        n = _num(f"spt[{i}].n", row.get("n"), min_value=0.0)
        out.append((depth, n))
    out.sort(key=lambda t: t[0])
    for (d1, _), (d2, _) in zip(out, out[1:]):
        if abs(d1 - d2) < _TOL:
            raise ValueError(f"duplicate SPT depth {d1:g} m")
    return out


def _parse_layer_bounds(layers: Any) -> list[dict[str, Any]]:
    """Validate top/base of each layer and return copies sorted by top."""
    if not isinstance(layers, list) or not layers:
        raise ValueError("layers must be a non-empty list")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(layers):
        if not isinstance(row, dict):
            raise ValueError(f"layers[{i}] must be an object")
        top = _num(f"layers[{i}].top", row.get("top"), min_value=0.0)
        base = _num(f"layers[{i}].base", row.get("base"), min_value=0.0)
        if base <= top:
            raise ValueError(f"layers[{i}]: base must be deeper than top")
        item = dict(row)
        item["top"], item["base"], item["_index"] = top, base, i
        out.append(item)
    out.sort(key=lambda r: r["top"])
    return out


def _check_continuous(layers: list[dict[str, Any]]) -> None:
    """Layers used for stress calculations must start at 0 m with no gaps or overlaps."""
    if abs(layers[0]["top"]) > 1e-6:
        raise ValueError("layers must start at the ground surface (top = 0 m)")
    for upper, lower in zip(layers, layers[1:]):
        if abs(upper["base"] - lower["top"]) > 1e-6:
            raise ValueError("layers must be continuous with no gaps or overlaps")


def _layer_at(layers: list[dict[str, Any]], z: float) -> dict[str, Any] | None:
    """Layer containing depth z (top <= z < base; the deepest base belongs to the last layer)."""
    for layer in layers:
        if layer["top"] - _TOL <= z < layer["base"] - _TOL:
            return layer
    last = max(layers, key=lambda r: r["base"])
    if abs(z - last["base"]) <= 1e-6:
        return last
    return None


def _vertical_stress(
    layers: list[tuple[float, float, float, float]], z: float, gw_depth: float | None
) -> tuple[float, float, float]:
    """Total stress, pore pressure and effective stress at depth z.

    layers: (top, base, gamma, gamma_sat), continuous from 0 m. Moist unit weight is
    used above the water table and saturated unit weight below it.
    """
    if z > layers[-1][1] + 1e-6:
        raise ValueError(f"depth {z:g} m is below the deepest layer")
    gw = math.inf if gw_depth is None else gw_depth
    sigma = 0.0
    for top, base, gamma, gamma_sat in layers:
        seg_top, seg_bot = top, min(base, z)
        if seg_bot <= seg_top:
            continue
        dry = max(0.0, min(seg_bot, gw) - seg_top)
        wet = max(0.0, seg_bot - max(seg_top, gw))
        sigma += gamma * dry + gamma_sat * wet
    u = GAMMA_W * max(0.0, z - gw)
    return sigma, u, sigma - u


# ---------------------------------------------------------------------------
# A) Shallow foundation bearing capacity
# ---------------------------------------------------------------------------

def bearing_capacity_factors(phi_deg: float) -> dict[str, float]:
    """Nc, Nq and Ngamma (Vesic) for a friction angle in degrees (0-50)."""
    phi_deg = _num("phi_deg", phi_deg, min_value=0.0, max_value=50.0)
    if phi_deg == 0.0:
        return {"Nc": 5.14, "Nq": 1.0, "Ngamma": 0.0}
    phi = math.radians(phi_deg)
    nq = math.exp(math.pi * math.tan(phi)) * math.tan(math.radians(45.0 + phi_deg / 2.0)) ** 2
    nc = (nq - 1.0) / math.tan(phi)
    ng = 2.0 * (nq + 1.0) * math.tan(phi)
    return {"Nc": nc, "Nq": nq, "Ngamma": ng}


def bearing_capacity_shallow(
    *,
    B: float,
    L: float | None,
    Df: float,
    c: float,
    phi_deg: float,
    gamma: float,
    gw_depth: float | None = None,
    gamma_sat: float | None = None,
    fs: float = 3.0,
) -> dict:
    """Ultimate and allowable bearing capacity of a shallow footing (general equation).

    qu = c Nc sc dc + q Nq sq dq + 0.5 gamma_eff B Ngamma sgamma dgamma, with Vesic
    Ngamma, De Beer shape factors and Hansen depth factors. L=None is a strip footing.
    Vertical, centric load on level ground is assumed.
    """
    B = _num("B", B, min_value=0.0, min_exclusive=True)
    if L is not None:
        L = _num("L", L, min_value=0.0, min_exclusive=True)
        if L < B - _TOL:
            raise ValueError("L must be at least B (B is the shorter side)")
    Df = _num("Df", Df, min_value=0.0)
    c = _num("c", c, min_value=0.0)
    phi_deg = _num("phi_deg", phi_deg, min_value=0.0, max_value=50.0)
    gamma = _num("gamma", gamma, min_value=0.0, min_exclusive=True)
    if gw_depth is not None:
        gw_depth = _num("gw_depth", gw_depth, min_value=0.0)
    if gamma_sat is None:
        gamma_sat_used = gamma + 1.0
    else:
        gamma_sat_used = _num("gamma_sat", gamma_sat, min_value=GAMMA_W, min_exclusive=True)
    if gamma_sat_used <= GAMMA_W:
        raise ValueError("gamma_sat must be greater than the unit weight of water (9.81)")
    fs = _num("fs", fs, min_value=1.0)
    if c == 0.0 and phi_deg == 0.0:
        raise ValueError("c and phi_deg cannot both be zero")

    notes: list[str] = []
    phi = math.radians(phi_deg)
    tan_phi = math.tan(phi)
    f = bearing_capacity_factors(phi_deg)
    nc, nq, ng = f["Nc"], f["Nq"], f["Ngamma"]

    # Shape factors (De Beer); strip footing has B/L = 0.
    b_over_l = 0.0 if L is None else B / L
    sc = 1.0 + b_over_l * (nq / nc)
    sq = 1.0 + b_over_l * tan_phi
    sg = max(0.6, 1.0 - 0.4 * b_over_l)

    # Depth factors (Hansen).
    ratio = Df / B
    k = ratio if ratio <= 1.0 else math.atan(ratio)
    if ratio > 1.0:
        notes.append("Df/B > 1: depth factors use k = arctan(Df/B).")
    dq = 1.0 + 2.0 * tan_phi * (1.0 - math.sin(phi)) ** 2 * k
    if phi_deg == 0.0:
        dc = 1.0 + 0.4 * k
    else:
        dc = dq - (1.0 - dq) / (nc * tan_phi)
    dg = 1.0

    # Overburden at the footing base and effective unit weight below it.
    gamma_sub = gamma_sat_used - GAMMA_W
    if gw_depth is None or gw_depth >= Df:
        q = gamma * Df
    else:
        q = gamma * gw_depth + gamma_sub * (Df - gw_depth)
    if gw_depth is None or gw_depth >= Df + B:
        gamma_eff = gamma
    elif gw_depth <= Df:
        gamma_eff = gamma_sub
    else:
        gamma_eff = gamma_sub + (gw_depth - Df) / B * (gamma - gamma_sub)
    if gw_depth is not None and gw_depth < Df + B:
        notes.append("Groundwater within depth Df + B: effective unit weight reduced.")
        if gamma_sat is None:
            notes.append("gamma_sat not given; gamma + 1 kN/m3 assumed.")

    term_c = c * nc * sc * dc
    term_q = q * nq * sq * dq
    term_g = 0.5 * gamma_eff * B * ng * sg * dg
    qu = term_c + term_q + term_g

    if phi_deg == 0.0:
        notes.append("phi = 0: undrained (total stress) analysis, Nc = 5.14, Ngamma = 0.")
    elif c > 0.0:
        notes.append("c-phi soil: check drained and undrained conditions separately.")
    if phi_deg > 40.0:
        notes.append("phi > 40 degrees: factors are very sensitive to phi; confirm phi by testing.")
    if 0.0 < phi_deg < 28.0 and c == 0.0:
        notes.append("Loose granular soil: local or punching shear may govern; settlement likely controls.")
    notes.append("Vertical centric load on level ground assumed; no inclination, eccentricity, base or slope factors.")
    notes.append("Settlement is not checked; allowable pressure may be limited by settlement.")
    notes.append(PRELIMINARY_NOTE)

    return {
        "method": (
            "General bearing capacity equation (Meyerhof/Vesic form): Vesic Ngamma, "
            "De Beer shape factors, Hansen depth factors"
        ),
        "factors": {
            "Nc": _r(nc, 3),
            "Nq": _r(nq, 3),
            "Ngamma": _r(ng, 3),
            "shape": {"sc": _r(sc, 3), "sq": _r(sq, 3), "sgamma": _r(sg, 3)},
            "depth": {"dc": _r(dc, 3), "dq": _r(dq, 3), "dgamma": _r(dg, 3), "k": _r(k, 3)},
        },
        "q_overburden": _r(q, 1),
        "gamma_eff": _r(gamma_eff, 2),
        "terms": {"cohesion": _r(term_c, 1), "overburden": _r(term_q, 1), "self_weight": _r(term_g, 1)},
        "qu": _r(qu, 1),
        "q_allow": _r(qu / fs, 1),
        "q_net_allow": _r((qu - q) / fs, 1),
        "units": {"stress": "kPa", "unit_weight": "kN/m3", "length": "m"},
        "inputs": {
            "B": B,
            "L": L,
            "footing": "strip" if L is None else ("square" if abs(L - B) < _TOL else "rectangular"),
            "Df": Df,
            "c": c,
            "phi_deg": phi_deg,
            "gamma": gamma,
            "gamma_sat": _r(gamma_sat_used, 3),
            "gw_depth": gw_depth,
            "fs": fs,
        },
        "notes": _unique(notes),
    }


# ---------------------------------------------------------------------------
# B) Pile capacity, Decourt SPT method
# ---------------------------------------------------------------------------

_DECOURT_K = {"clay": 120.0, "clayey_silt": 200.0, "sandy_silt": 250.0, "sand": 400.0}
_BORED_ALPHA = {"clay": 0.85, "clayey_silt": 0.60, "sandy_silt": 0.60, "sand": 0.50}
_BORED_BETA = {"clay": 0.80, "clayey_silt": 0.65, "sandy_silt": 0.65, "sand": 0.50}
_N_SHAFT_MIN, _N_SHAFT_MAX, _N_TIP_MAX = 3.0, 50.0, 50.0


def decourt_soil_class(uscs: str | None) -> str | None:
    """Decourt soil class from a USCS symbol; None when the symbol is not recognised.

    CL, CH, OL, OH, PT (and dual symbols starting with C) -> clay; ML -> sandy_silt;
    MH -> clayey_silt; symbols starting with S or G -> sand.
    """
    s = _uscs(uscs)
    if not s:
        return None
    primary = s.split("-")[0]
    if primary in _CLAY_SYMBOLS or primary.startswith("C"):
        return "clay"
    if primary == "ML":
        return "sandy_silt"
    if primary == "MH":
        return "clayey_silt"
    if primary[:1] in ("S", "G") and len(primary) == 2:
        return "sand"
    return None


def _class_at(layers: list[dict[str, Any]], z: float, notes: list[str]) -> tuple[str, str]:
    """(soil class, uscs) at depth z; unknown soils are treated as clay (lowest K)."""
    layer = _layer_at(layers, z)
    if layer is None:
        notes.append(f"No layer defined at {z:g} m; treated as clay (conservative).")
        return "clay", ""
    uscs = _uscs(layer.get("uscs"))
    cls = decourt_soil_class(uscs)
    if cls is None:
        notes.append(f"USCS '{uscs or '-'}' not recognised; treated as clay (conservative).")
        return "clay", uscs
    return cls, uscs


def _nearest(tests: list[tuple[float, float]], z: float) -> tuple[float, float]:
    """Nearest test to depth z; ties go to the lower N (conservative)."""
    return min(tests, key=lambda t: (round(abs(t[0] - z), 9), t[1]))


def _decourt(
    D: float,
    length: float,
    tests: list[tuple[float, float]],
    layers: list[dict[str, Any]],
    pile_type: str,
    fs_shaft: float,
    fs_tip: float,
) -> dict:
    notes: list[str] = []
    if length > tests[-1][0] + 1.0 + _TOL:
        raise ValueError("pile tip is below the deepest SPT")
    if D > length:
        notes.append("Pile length is shorter than its diameter; check the input.")

    # Tip: tests within one diameter above and below the tip, else the nearest test.
    window = [t for t in tests if abs(t[0] - length) <= D + _TOL]
    if not window:
        window = [_nearest(tests, length)]
        notes.append("No SPT within one diameter of the tip; nearest SPT used for Np.")
    tip_values = []
    for _, n in window:
        if n > _N_TIP_MAX:
            notes.append("Tip N values above 50 capped at 50.")
        tip_values.append(min(n, _N_TIP_MAX))
    np_ = sum(tip_values) / len(tip_values)
    tip_class, tip_uscs = _class_at(layers, length, notes)
    alpha = 1.0 if pile_type == "driven" else _BORED_ALPHA[tip_class]
    k_tip = _DECOURT_K[tip_class]
    qp = alpha * k_tip * np_
    area = math.pi * D ** 2 / 4.0
    Qp = qp * area

    # Shaft: 1 m slices from the ground surface; SPTs used for Np are excluded.
    used = set(window)
    eligible = [t for t in tests if t not in used and t[0] <= length + _TOL]
    if not eligible:
        eligible = [t for t in tests if t[0] <= length + _TOL] or list(tests)
        notes.append("No SPT along the shaft outside the tip zone; tip-zone SPTs used for the shaft.")
    perimeter = math.pi * D
    slices: list[dict[str, Any]] = []
    Qs = 0.0
    n_weighted = 0.0
    n_slices = max(1, math.ceil(length - 1e-9))
    for i in range(n_slices):
        top = float(i)
        base = min(float(i + 1), length)
        thickness = base - top
        if thickness <= _TOL:
            continue
        last = i == n_slices - 1
        inside = [t for t in eligible if top - _TOL <= t[0] < base - _TOL or (last and abs(t[0] - base) <= _TOL)]
        if not inside:
            inside = [_nearest(eligible, (top + base) / 2.0)]
        n_bar = sum(min(_N_SHAFT_MAX, max(_N_SHAFT_MIN, n)) for _, n in inside) / len(inside)
        cls, uscs = _class_at(layers, (top + base) / 2.0, notes)
        beta = 1.0 if pile_type == "driven" else _BORED_BETA[cls]
        qs = beta * 10.0 * (n_bar / 3.0 + 1.0)
        q_slice = qs * perimeter * thickness
        Qs += q_slice
        n_weighted += n_bar * thickness
        slices.append({
            "top": _r(top, 2),
            "base": _r(base, 2),
            "uscs": uscs,
            "soil_class": cls,
            "n_bar": _r(n_bar, 2),
            "beta": _r(beta, 3),
            "qs": _r(qs, 1),
            "Qs": _r(q_slice, 1),
        })

    Qult = Qp + Qs
    Qallow = Qp / fs_tip + Qs / fs_shaft
    notes.append("Shaft N values limited to 3 <= N <= 50; SPTs used for the tip are excluded from the shaft.")
    notes.append("Shaft computed in 1 m slices from the ground surface; slice N is the mean of SPTs in the slice, else the nearest SPT.")
    notes.append("Negative skin friction, group effects, uplift and settlement are not considered.")
    notes.append("Structural capacity of the pile section must be checked separately.")
    notes.append(PRELIMINARY_NOTE)
    return {
        "method": "Decourt (1982, 1996) SPT method",
        "tip": {
            "depth": _r(length, 2),
            "uscs": tip_uscs,
            "soil_class": tip_class,
            "N_values": [_r(n, 1) for n in tip_values],
            "Np": _r(np_, 2),
            "K": _r(k_tip, 1),
            "alpha": _r(alpha, 3),
            "qp": _r(qp, 1),
            "area": _r(area, 5),
            "Qp": _r(Qp, 1),
        },
        "shaft": {
            "perimeter": _r(perimeter, 4),
            "n_bar_mean": _r(n_weighted / length, 2),
            "slices": slices,
            "Qs": _r(Qs, 1),
        },
        "Qp": _r(Qp, 1),
        "Qs": _r(Qs, 1),
        "Qult": _r(Qult, 1),
        "Qallow": _r(Qallow, 1),
        "units": {"stress": "kPa", "force": "kN", "length": "m"},
        "notes": _unique(notes),
    }


def _pile_inputs(
    diameter: Any, spt: Any, layers: Any, pile_type: Any, fs_shaft: Any, fs_tip: Any
) -> tuple[float, list[tuple[float, float]], list[dict[str, Any]], str, float, float]:
    D = _num("diameter", diameter, min_value=0.0, min_exclusive=True)
    if D > 5.0:
        raise ValueError("diameter must be at most 5 m")
    tests = _parse_spt(spt)
    lay = _parse_layer_bounds(layers)
    if not isinstance(pile_type, str) or pile_type.strip().lower() not in ("driven", "bored"):
        raise ValueError("pile_type must be 'driven' or 'bored'")
    fs_s = _num("fs_shaft", fs_shaft, min_value=1.0)
    fs_t = _num("fs_tip", fs_tip, min_value=1.0)
    return D, tests, lay, pile_type.strip().lower(), fs_s, fs_t


def pile_capacity_decourt(
    *,
    diameter: float,
    length: float,
    spt: list[dict],
    layers: list[dict],
    pile_type: str = "driven",
    fs_shaft: float = 2.5,
    fs_tip: float = 2.5,
) -> dict:
    """Axial compression capacity of a single pile from SPT N values (Decourt).

    Qp = alpha K Np Ap; Qs = sum(beta 10 (N/3 + 1) perimeter dz); Qallow = Qp/fs_tip + Qs/fs_shaft.
    """
    D, tests, lay, ptype, fs_s, fs_t = _pile_inputs(diameter, spt, layers, pile_type, fs_shaft, fs_tip)
    L = _num("length", length, min_value=0.0, min_exclusive=True)
    result = _decourt(D, L, tests, lay, ptype, fs_s, fs_t)
    result["inputs"] = {
        "diameter": D, "length": L, "pile_type": ptype, "fs_shaft": fs_s, "fs_tip": fs_t,
        "n_spt": len(tests),
    }
    return result


def pile_capacity_profile(
    *,
    diameter: float,
    spt: list[dict],
    layers: list[dict],
    pile_type: str = "driven",
    fs_shaft: float = 2.5,
    fs_tip: float = 2.5,
) -> dict:
    """Decourt capacity for pile lengths from 2 m to the deepest SPT in 1 m steps (for charts)."""
    D, tests, lay, ptype, fs_s, fs_t = _pile_inputs(diameter, spt, layers, pile_type, fs_shaft, fs_tip)
    deepest = tests[-1][0]
    if deepest < 2.0:
        raise ValueError("the deepest SPT must be at least 2 m deep for a profile")
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    for length in range(2, int(math.floor(deepest + 1e-9)) + 1):
        res = _decourt(D, float(length), tests, lay, ptype, fs_s, fs_t)
        notes.extend(res["notes"])
        rows.append({
            "length": float(length),
            "Qp": res["Qp"],
            "Qs": res["Qs"],
            "Qult": res["Qult"],
            "Qallow": res["Qallow"],
        })
    notes = [n for n in _unique(notes) if n != PRELIMINARY_NOTE] + [PRELIMINARY_NOTE]
    return {
        "method": "Decourt (1982, 1996) SPT method",
        "profile": rows,
        "units": {"force": "kN", "length": "m"},
        "inputs": {"diameter": D, "pile_type": ptype, "fs_shaft": fs_s, "fs_tip": fs_t, "n_spt": len(tests)},
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# C) Primary consolidation settlement
# ---------------------------------------------------------------------------

def consolidation_settlement(
    *,
    layers: list[dict],
    q: float,
    B: float,
    L: float | None = None,
    Df: float = 0.0,
    gw_depth: float | None = None,
) -> dict:
    """One-dimensional primary consolidation settlement under a footing (2:1 stress spread).

    Layers must be continuous from the ground surface; use Cc = 0 for incompressible
    layers. q is the net pressure applied at the footing base (depth Df).
    """
    lay = _parse_layer_bounds(layers)
    _check_continuous(lay)
    q = _num("q", q, min_value=0.0)
    B = _num("B", B, min_value=0.0, min_exclusive=True)
    if L is not None:
        L = _num("L", L, min_value=0.0, min_exclusive=True)
        if L < B - _TOL:
            raise ValueError("L must be at least B (B is the shorter side)")
    Df = _num("Df", Df, min_value=0.0)
    if gw_depth is not None:
        gw_depth = _num("gw_depth", gw_depth, min_value=0.0)

    notes: list[str] = []
    props: list[dict[str, Any]] = []
    stress_layers: list[tuple[float, float, float, float]] = []
    for layer in lay:
        i = layer["_index"]
        gamma = _num(f"layers[{i}].gamma", layer.get("gamma"), min_value=0.0, min_exclusive=True)
        if layer.get("gamma_sat") is None:
            gamma_sat = gamma
            if gw_depth is not None and layer["base"] > gw_depth:
                notes.append("gamma_sat not given for a layer below the water table; gamma used (conservative).")
        else:
            gamma_sat = _num(f"layers[{i}].gamma_sat", layer.get("gamma_sat"), min_value=0.0, min_exclusive=True)
        if gw_depth is not None and layer["base"] > gw_depth and gamma_sat <= GAMMA_W:
            raise ValueError(f"layers[{i}]: unit weight below the water table must exceed 9.81 kN/m3")
        cc = _num(f"layers[{i}].Cc", layer.get("Cc"), min_value=0.0, max_value=10.0)
        cr_raw = layer.get("Cr")
        cr = cc / 5.0 if cr_raw is None else _num(f"layers[{i}].Cr", cr_raw, min_value=0.0, max_value=10.0)
        if cr > cc:
            notes.append(f"Layer {i}: Cr is larger than Cc; check the input.")
        e0 = _num(f"layers[{i}].e0", layer.get("e0"), min_value=0.0, min_exclusive=True, max_value=20.0)
        sp_raw = layer.get("sigma_p")
        sigma_p = None if sp_raw is None else _num(
            f"layers[{i}].sigma_p", sp_raw, min_value=0.0, min_exclusive=True
        )
        props.append({"index": i, "top": layer["top"], "base": layer["base"], "Cc": cc, "Cr": cr,
                      "e0": e0, "sigma_p": sigma_p, "uscs": _uscs(layer.get("uscs"))})
        stress_layers.append((layer["top"], layer["base"], gamma, gamma_sat))

    if Df >= lay[-1]["base"] - _TOL:
        raise ValueError("footing base Df is at or below the deepest layer")

    rows: list[dict[str, Any]] = []
    total = 0.0
    for p in props:
        top = max(p["top"], Df)
        base = p["base"]
        if base - top <= _TOL:
            continue
        n_sub = max(1, math.ceil((base - top) - 1e-9))
        h = (base - top) / n_sub
        for j in range(n_sub):
            s_top = top + j * h
            s_base = s_top + h
            mid = (s_top + s_base) / 2.0
            _, _, s0 = _vertical_stress(stress_layers, mid, gw_depth)
            if s0 <= 0.0:
                raise ValueError(f"effective stress is not positive at {mid:g} m; check unit weights")
            z = mid - Df
            if L is None:
                ds = q * B / (B + z)
            else:
                ds = q * B * L / ((B + z) * (L + z))
            cc, cr, e0, sp = p["Cc"], p["Cr"], p["e0"], p["sigma_p"]
            s1 = s0 + ds
            state = "NC"
            if sp is not None and sp < s0 - 1e-6:
                notes.append(f"Layer {p['index']}: sigma_p is below the in-situ effective stress; treated as normally consolidated.")
                sp = None
            if sp is None or sp <= s0 + 1e-9:
                settle = cc * h / (1.0 + e0) * math.log10(s1 / s0)
            elif s1 <= sp:
                state = "OC"
                settle = cr * h / (1.0 + e0) * math.log10(s1 / s0)
            else:
                state = "OC->NC"
                settle = (cr * h / (1.0 + e0) * math.log10(sp / s0)
                          + cc * h / (1.0 + e0) * math.log10(s1 / sp))
            total += settle
            rows.append({
                "layer": p["index"],
                "uscs": p["uscs"],
                "top": _r(s_top, 3),
                "base": _r(s_base, 3),
                "thickness": _r(h, 3),
                "mid_depth": _r(mid, 3),
                "sigma_v0_eff": _r(s0, 1),
                "delta_sigma": _r(ds, 1),
                "sigma_p": _r(sp, 1),
                "state": state,
                "settlement_mm": _r(settle * 1000.0, 1),
            })

    notes.append("Primary consolidation only; immediate and secondary compression are not included.")
    notes.append("Stress increase by the approximate 2:1 method; footing assumed flexible.")
    notes.append("Layers are split into sublayers of at most 1 m; stresses taken at sublayer mid-depth.")
    notes.append(PRELIMINARY_NOTE)
    return {
        "method": "1D consolidation (Terzaghi; Cc/Cr e-log p) with 2:1 stress distribution",
        "sublayers": rows,
        "total_settlement_mm": _r(total * 1000.0, 1),
        "units": {"stress": "kPa", "settlement": "mm", "length": "m"},
        "inputs": {"q": q, "B": B, "L": L, "footing": "strip" if L is None else "rectangular",
                   "Df": Df, "gw_depth": gw_depth, "n_layers": len(lay)},
        "notes": _unique(notes),
    }


# ---------------------------------------------------------------------------
# D) Liquefaction triggering, Idriss & Boulanger (2014) SPT procedure
# ---------------------------------------------------------------------------

_LIQ_FINES_DEFAULT = {"SP": 5.0, "SW": 5.0, "GP": 5.0, "GW": 5.0, "SM": 25.0, "GM": 25.0,
                      "SC": 30.0, "GC": 30.0, "ML": 60.0}
_CLAY_LIKE = {"CL", "CH", "OL", "OH", "PT", "MH"}


def crr_7p5_idriss_boulanger(n1_60cs: float) -> float:
    """CRR for M = 7.5 and sigma'v = 1 atm (Idriss & Boulanger 2014); 2.0 cap at (N1)60cs >= 37.5."""
    n = _num("n1_60cs", n1_60cs, min_value=0.0)
    if n >= 37.5:
        return 2.0
    return math.exp(n / 14.1 + (n / 126.0) ** 2 - (n / 23.6) ** 3 + (n / 25.4) ** 4 - 2.8)


def msf_idriss_boulanger(n1_60cs: float, magnitude: float) -> float:
    """Magnitude scaling factor (Idriss & Boulanger 2014)."""
    n = _num("n1_60cs", n1_60cs, min_value=0.0)
    m = _num("magnitude", magnitude, min_value=4.0, max_value=9.5)
    msf_max = min(2.2, 1.09 + (n / 31.5) ** 2)
    return 1.0 + (msf_max - 1.0) * (8.64 * math.exp(-m / 4.0) - 1.325)


def rd_idriss_boulanger(depth: float, magnitude: float) -> float:
    """Shear stress reduction factor rd (Idriss 1999, as used by Idriss & Boulanger 2014)."""
    z = _num("depth", depth, min_value=0.0, max_value=34.0)
    m = _num("magnitude", magnitude, min_value=4.0, max_value=9.5)
    a = -1.012 - 1.126 * math.sin(z / 11.73 + 5.133)
    b = 0.106 + 0.118 * math.sin(z / 11.28 + 5.142)
    return math.exp(a + b * m)


def _cb(diameter_mm: float) -> float:
    if diameter_mm <= 115.0:
        return 1.0
    if diameter_mm <= 150.0:
        return 1.0 + (diameter_mm - 115.0) / 35.0 * 0.05
    if diameter_mm <= 200.0:
        return 1.05 + (diameter_mm - 150.0) / 50.0 * 0.10
    return 1.15


def _cr(rod_length: float) -> float:
    if rod_length < 3.0:
        return 0.75
    if rod_length < 4.0:
        return 0.80
    if rod_length < 6.0:
        return 0.85
    if rod_length < 10.0:
        return 0.95
    return 1.0


def liquefaction_spt(
    *,
    spt: list[dict],
    layers: list[dict],
    gw_depth: float,
    amax_g: float,
    magnitude: float = 7.5,
    energy_ratio: float = 60.0,
    borehole_diameter_mm: float = 100.0,
    rod_extra_m: float = 1.5,
    sampler_liners: bool = False,
) -> dict:
    """Liquefaction triggering factor of safety per SPT (Idriss & Boulanger 2014).

    Layers must be continuous from the ground surface (unit weights default to 18/19 kN/m3).
    gw_depth is the water table depth during the earthquake.
    """
    tests = _parse_spt(spt)
    lay = _parse_layer_bounds(layers)
    _check_continuous(lay)
    gw = _num("gw_depth", gw_depth, min_value=0.0)
    amax = _num("amax_g", amax_g, min_value=0.0, min_exclusive=True, max_value=2.0)
    mag = _num("magnitude", magnitude, min_value=4.0, max_value=9.5)
    er = _num("energy_ratio", energy_ratio, min_value=20.0, max_value=100.0)
    dia = _num("borehole_diameter_mm", borehole_diameter_mm, min_value=0.0, min_exclusive=True)
    rod_extra = _num("rod_extra_m", rod_extra_m, min_value=0.0, max_value=10.0)
    if not isinstance(sampler_liners, bool):
        raise ValueError("sampler_liners must be true or false")

    notes: list[str] = []
    stress_layers: list[tuple[float, float, float, float]] = []
    for layer in lay:
        i = layer["_index"]
        g = _num(f"layers[{i}].gamma", 18.0 if layer.get("gamma") is None else layer.get("gamma"),
                 min_value=0.0, min_exclusive=True)
        gs = _num(f"layers[{i}].gamma_sat", 19.0 if layer.get("gamma_sat") is None else layer.get("gamma_sat"),
                  min_value=0.0, min_exclusive=True)
        if layer["base"] > gw and gs <= GAMMA_W:
            raise ValueError(f"layers[{i}]: gamma_sat must exceed 9.81 kN/m3")
        if layer.get("fines") is not None:
            _num(f"layers[{i}].fines", layer.get("fines"), min_value=0.0, max_value=100.0)
        if layer.get("pi") is not None:
            _num(f"layers[{i}].pi", layer.get("pi"), min_value=0.0, max_value=200.0)
        stress_layers.append((layer["top"], layer["base"], g, gs))
    if tests[-1][0] > lay[-1]["base"] + 1e-6:
        raise ValueError("an SPT is below the deepest layer")

    ce = er / 60.0
    cb = _cb(dia)
    cs = 1.0
    if dia < 65.0 or dia > 200.0:
        notes.append("Borehole diameter outside 65-200 mm; CB taken at the nearest end of the range.")
    if sampler_liners:
        notes.append("Sampler correction CS = 1.0 (standard sampler with liners).")
    else:
        notes.append("Sampler correction CS = 1.0 assumed; a sampler without liners may justify CS = 1.1-1.3 (1.0 is conservative).")

    rows: list[dict[str, Any]] = []
    for depth, n in tests:
        found = _layer_at(lay, depth)
        if found is None:  # cannot happen for continuous layers; kept as a guard
            raise ValueError(f"no layer defined at {depth:g} m")
        layer = found
        uscs = _uscs(layer.get("uscs"))
        primary = uscs.split("-")[0] if uscs else ""
        pi = layer.get("pi")
        sv, u, sve = _vertical_stress(stress_layers, depth, gw)
        row: dict[str, Any] = {
            "depth": _r(depth, 2), "n": _r(n, 1), "uscs": uscs,
            "sigma_v": _r(sv, 1), "u": _r(u, 1), "sigma_v_eff": _r(sve, 1),
            "CE": None, "CB": None, "CR": None, "CS": None, "N60": None, "fines": None,
            "delta_n1_60": None, "CN": None, "N1_60": None, "N1_60cs": None, "rd": None,
            "CSR": None, "CRR_7p5_1atm": None, "MSF": None, "K_sigma": None, "CRR": None,
            "FS": None, "status": "", "remark": "",
        }
        if depth > 20.0 + _TOL:
            row["status"] = "below 20 m (not evaluated)"
            rows.append(row)
            continue
        if depth < gw - _TOL:
            row["status"] = "above water table"
            rows.append(row)
            continue
        low_pi_silty_clay = uscs in ("CL-ML", "ML-CL")
        if (primary in _CLAY_LIKE and not low_pi_silty_clay) or (pi is not None and float(pi) > 7.0):
            row["status"] = "not susceptible (clay-like behaviour)"
            rows.append(row)
            continue
        if sve <= 0.0:
            raise ValueError(f"effective stress is not positive at {depth:g} m")

        if layer.get("fines") is not None:
            fc = float(layer["fines"])
        elif low_pi_silty_clay:
            fc = 60.0
            notes.append("CL-ML evaluated as sand-like (low plasticity); fines content 60% assumed.")
        elif primary in _LIQ_FINES_DEFAULT:
            fc = _LIQ_FINES_DEFAULT[primary]
            notes.append("Fines content not given for some layers; default by USCS group used.")
        else:
            fc = 5.0
            notes.append(f"USCS '{uscs or '-'}' not recognised; evaluated as clean sand (FC = 5%, conservative).")

        cr = _cr(depth + rod_extra)
        n60 = n * ce * cb * cr * cs
        dn = math.exp(1.63 + 9.7 / (fc + 0.01) - (15.7 / (fc + 0.01)) ** 2)
        n1cs = n60 + dn
        cn = 1.0
        for _ in range(100):
            m_exp = 0.784 - 0.0768 * math.sqrt(min(max(n1cs, 0.0), 46.0))
            cn = min(1.7, (PA / sve) ** m_exp)
            new = cn * n60 + dn
            if abs(new - n1cs) < 1e-6:
                n1cs = new
                break
            n1cs = new
        n1 = cn * n60
        rd = rd_idriss_boulanger(depth, mag)
        csr = 0.65 * (sv / sve) * amax * rd
        row.update({"CE": _r(ce, 3), "CB": _r(cb, 3), "CR": _r(cr, 3), "CS": _r(cs, 3),
                    "N60": _r(n60, 1), "fines": _r(fc, 1), "delta_n1_60": _r(dn, 2),
                    "CN": _r(cn, 3), "N1_60": _r(n1, 1), "N1_60cs": _r(n1cs, 1),
                    "rd": _r(rd, 3), "CSR": _r(csr, 3)})
        if n1cs >= 37.5:
            crr = 2.0
            fs = crr / csr
            row.update({"CRR_7p5_1atm": 2.0, "CRR": 2.0, "FS": _r(fs, 3),
                        "status": "not liquefiable",
                        "remark": "(N1)60cs >= 37.5: too dense to liquefy (CRR capped at 2.0)."})
            rows.append(row)
            continue
        crr75 = crr_7p5_idriss_boulanger(n1cs)
        msf = msf_idriss_boulanger(n1cs, mag)
        c_sigma = min(0.3, 1.0 / (18.9 - 2.55 * math.sqrt(n1cs)))
        k_sigma = min(1.1, 1.0 - c_sigma * math.log(sve / PA))
        crr = crr75 * msf * k_sigma
        fs = crr / csr
        status = "liquefiable" if fs < 1.0 else ("marginal" if fs < 1.3 else "not liquefiable")
        row.update({"CRR_7p5_1atm": _r(crr75, 3), "MSF": _r(msf, 3), "K_sigma": _r(k_sigma, 3),
                    "CRR": _r(crr, 3), "FS": _r(fs, 3), "status": status})
        rows.append(row)

    evaluated = [r for r in rows if r["FS"] is not None]
    liq = [r for r in rows if r["status"] == "liquefiable"]
    marginal = [r for r in rows if r["status"] == "marginal"]
    fs_values = [float(r["FS"]) for r in evaluated]
    if liq:
        notes.append("Liquefiable layers found: assess settlement, lateral spreading and loss of pile/footing support.")
    notes.append("Rod length taken as SPT depth + rod_extra_m for CR.")
    notes.append("SPTs deeper than 20 m are not evaluated.")
    notes.append(PRELIMINARY_NOTE)
    return {
        "method": "Idriss & Boulanger (2014) SPT-based liquefaction triggering procedure",
        "rows": rows,
        "summary": {
            "n_tests": len(rows),
            "n_evaluated": len(evaluated),
            "n_liquefiable": len(liq),
            "n_marginal": len(marginal),
            "shallowest_liquefiable_depth": liq[0]["depth"] if liq else None,
            "min_fs": _r(min(fs_values), 3) if fs_values else None,
        },
        "units": {"stress": "kPa", "length": "m"},
        "inputs": {"gw_depth": gw, "amax_g": amax, "magnitude": mag, "energy_ratio": er,
                   "borehole_diameter_mm": dia, "rod_extra_m": rod_extra, "sampler_liners": sampler_liners},
        "notes": _unique(notes),
    }


__all__ = [
    "bearing_capacity_factors",
    "bearing_capacity_shallow",
    "decourt_soil_class",
    "pile_capacity_decourt",
    "pile_capacity_profile",
    "consolidation_settlement",
    "crr_7p5_idriss_boulanger",
    "msf_idriss_boulanger",
    "rd_idriss_boulanger",
    "liquefaction_spt",
]
