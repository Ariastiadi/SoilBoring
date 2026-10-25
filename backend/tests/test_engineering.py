"""Tests for backend.app.engineering. Expected values are hand calculations written out
here with math, not taken from the module's own helpers."""
import json
import math

import pytest

from backend.app import engineering as eng

PRELIM = "Preliminary estimate"


def _has_prelim(result):
    return any(PRELIM in n for n in result["notes"])


def _json_ok(result):
    json.dumps(result, allow_nan=False)


# ---------------------------------------------------------------------------
# A) Bearing capacity
# ---------------------------------------------------------------------------

def test_factors_phi_30():
    f = eng.bearing_capacity_factors(30)
    assert f["Nq"] == pytest.approx(18.40, abs=0.02)
    assert f["Nc"] == pytest.approx(30.14, abs=0.02)
    assert f["Ngamma"] == pytest.approx(22.40, abs=0.02)


def test_factors_phi_0():
    f = eng.bearing_capacity_factors(0)
    assert f == {"Nc": 5.14, "Nq": 1.0, "Ngamma": 0.0}


def test_strip_undrained_surface():
    res = eng.bearing_capacity_shallow(B=1.5, L=None, Df=0, c=50, phi_deg=0, gamma=18)
    assert res["qu"] == pytest.approx(257.0, abs=0.05)
    assert res["factors"]["Nc"] == 5.14
    assert res["factors"]["Nq"] == 1.0
    assert res["factors"]["Ngamma"] == 0.0
    assert res["q_allow"] == pytest.approx(257.0 / 3, abs=0.05)
    assert res["inputs"]["footing"] == "strip"
    assert _has_prelim(res)
    _json_ok(res)


def test_square_footing_hand_calc():
    # B = L = 2, Df = 1, c = 10, phi = 30, gamma = 18, water deep.
    phi = math.radians(30)
    nq = math.exp(math.pi * math.tan(phi)) * math.tan(math.radians(60)) ** 2
    nc = (nq - 1) / math.tan(phi)
    ng = 2 * (nq + 1) * math.tan(phi)
    sc, sq, sg = 1 + nq / nc, 1 + math.tan(phi), 0.6
    k = 0.5
    dq = 1 + 2 * math.tan(phi) * (1 - math.sin(phi)) ** 2 * k
    dc = dq - (1 - dq) / (nc * math.tan(phi))
    q = 18 * 1
    qu = 10 * nc * sc * dc + q * nq * sq * dq + 0.5 * 18 * 2 * ng * sg
    res = eng.bearing_capacity_shallow(B=2, L=2, Df=1, c=10, phi_deg=30, gamma=18)
    assert res["qu"] == pytest.approx(qu, abs=0.1)
    assert res["q_overburden"] == pytest.approx(18.0)
    assert res["q_net_allow"] == pytest.approx((qu - q) / 3, abs=0.1)
    assert res["factors"]["depth"]["dq"] == pytest.approx(dq, abs=0.001)
    assert res["factors"]["shape"]["sgamma"] == 0.6


def test_deep_footing_uses_arctan():
    res = eng.bearing_capacity_shallow(B=1, L=None, Df=2, c=0, phi_deg=32, gamma=18)
    assert res["factors"]["depth"]["k"] == pytest.approx(math.atan(2), abs=0.001)
    assert any("arctan" in n for n in res["notes"])


def test_groundwater_reduces_capacity():
    common = dict(B=2, L=None, Df=1, c=0, phi_deg=32, gamma=18, gamma_sat=20)
    deep = eng.bearing_capacity_shallow(**common)
    surface = eng.bearing_capacity_shallow(**common, gw_depth=0)
    partial = eng.bearing_capacity_shallow(**common, gw_depth=2)
    assert surface["qu"] < partial["qu"] < deep["qu"]
    assert surface["q_overburden"] == pytest.approx((20 - 9.81) * 1, abs=0.05)
    assert surface["gamma_eff"] == pytest.approx(10.19, abs=0.01)
    # Water halfway through the zone below the base: gamma' + 0.5 (gamma - gamma').
    assert partial["gamma_eff"] == pytest.approx(10.19 + 0.5 * (18 - 10.19), abs=0.01)
    far = eng.bearing_capacity_shallow(**common, gw_depth=3)
    assert far["qu"] == deep["qu"]


def test_gamma_sat_default():
    res = eng.bearing_capacity_shallow(B=1, L=None, Df=1, c=0, phi_deg=30, gamma=18, gw_depth=0)
    assert res["inputs"]["gamma_sat"] == 19.0
    assert res["q_overburden"] == pytest.approx(19 - 9.81, abs=0.05)


@pytest.mark.parametrize("kwargs", [
    dict(B=-1, L=None, Df=1, c=0, phi_deg=30, gamma=18),
    dict(B=0, L=None, Df=1, c=0, phi_deg=30, gamma=18),
    dict(B=2, L=1, Df=1, c=0, phi_deg=30, gamma=18),
    dict(B=1, L=None, Df=-0.5, c=0, phi_deg=30, gamma=18),
    dict(B=1, L=None, Df=1, c=-5, phi_deg=30, gamma=18),
    dict(B=1, L=None, Df=1, c=0, phi_deg=55, gamma=18),
    dict(B=1, L=None, Df=1, c=0, phi_deg=-1, gamma=18),
    dict(B=1, L=None, Df=1, c=0, phi_deg=30, gamma=0),
    dict(B=1, L=None, Df=1, c=0, phi_deg=30, gamma=18, fs=0.5),
    dict(B=1, L=None, Df=1, c=0, phi_deg=30, gamma=18, gw_depth=-1),
    dict(B=1, L=None, Df=1, c=0, phi_deg=30, gamma=18, gamma_sat=9.0),
    dict(B=1, L=None, Df=1, c=0, phi_deg=0, gamma=18),
    dict(B="1", L=None, Df=1, c=0, phi_deg=30, gamma=18),
    dict(B=float("nan"), L=None, Df=1, c=0, phi_deg=30, gamma=18),
])
def test_bearing_invalid(kwargs):
    with pytest.raises(ValueError):
        eng.bearing_capacity_shallow(**kwargs)


# ---------------------------------------------------------------------------
# B) Decourt pile capacity
# ---------------------------------------------------------------------------

def _uniform(n, deepest=12):
    return [{"depth": float(d), "n": n} for d in range(1, deepest + 1)]


SAND = [{"top": 0, "base": 15, "uscs": "SP"}]
CLAY = [{"top": 0, "base": 15, "uscs": "CH"}]


def test_decourt_uniform_sand_driven():
    res = eng.pile_capacity_decourt(diameter=0.4, length=10, spt=_uniform(20), layers=SAND)
    ap = math.pi * 0.4 ** 2 / 4
    qp = 400 * 20
    qs = 10 * (20 / 3 + 1)
    Qp = qp * ap
    Qs = qs * math.pi * 0.4 * 10
    assert res["tip"]["Np"] == 20
    assert res["tip"]["qp"] == pytest.approx(8000.0)
    assert res["Qp"] == pytest.approx(1005.3, abs=0.05)
    assert Qp == pytest.approx(1005.3, abs=0.05)
    assert res["Qs"] == pytest.approx(963.4, abs=0.05)
    assert Qs == pytest.approx(963.4, abs=0.05)
    assert res["Qult"] == pytest.approx(Qp + Qs, abs=0.1)
    assert res["Qallow"] == pytest.approx(Qp / 2.5 + Qs / 2.5, abs=0.1)
    assert len(res["shaft"]["slices"]) == 10
    assert res["method"].startswith("Decourt")
    assert _has_prelim(res)
    _json_ok(res)


def test_decourt_uniform_clay_uses_k120():
    res = eng.pile_capacity_decourt(diameter=0.4, length=10, spt=_uniform(10), layers=CLAY)
    assert res["tip"]["K"] == 120
    assert res["tip"]["soil_class"] == "clay"
    assert res["Qp"] == pytest.approx(120 * 10 * math.pi * 0.4 ** 2 / 4, abs=0.05)
    assert res["Qs"] == pytest.approx(10 * (10 / 3 + 1) * math.pi * 0.4 * 10, abs=0.05)


def test_decourt_bored_vs_driven_ratios():
    for layers, a, b in ((SAND, 0.50, 0.50), (CLAY, 0.85, 0.80),
                         ([{"top": 0, "base": 15, "uscs": "ML"}], 0.60, 0.65)):
        d = eng.pile_capacity_decourt(diameter=0.6, length=8, spt=_uniform(15), layers=layers)
        bo = eng.pile_capacity_decourt(diameter=0.6, length=8, spt=_uniform(15), layers=layers,
                                       pile_type="bored")
        assert bo["Qp"] / d["Qp"] == pytest.approx(a, abs=0.001)
        assert bo["Qs"] / d["Qs"] == pytest.approx(b, abs=0.001)


def test_decourt_silt_k_values():
    ml = eng.pile_capacity_decourt(diameter=0.4, length=6, spt=_uniform(10),
                                   layers=[{"top": 0, "base": 15, "uscs": "ML"}])
    mh = eng.pile_capacity_decourt(diameter=0.4, length=6, spt=_uniform(10),
                                   layers=[{"top": 0, "base": 15, "uscs": "MH"}])
    assert ml["tip"]["K"] == 250 and ml["tip"]["soil_class"] == "sandy_silt"
    assert mh["tip"]["K"] == 200 and mh["tip"]["soil_class"] == "clayey_silt"


def test_decourt_layered_hand_calc():
    # Sand 0-5 m (N = 10 at 1..5 m), clay 5-12 m (N = 8 at 6..12 m). D = 0.5, L = 10.
    spt = [{"depth": float(d), "n": 10 if d <= 5 else 8} for d in range(1, 13)]
    layers = [{"top": 0, "base": 5, "uscs": "SM"}, {"top": 5, "base": 12, "uscs": "CL"}]
    p = math.pi * 0.5
    ap = math.pi * 0.25 / 4
    q10, q8 = 10 * (10 / 3 + 1), 10 * (8 / 3 + 1)
    # Slices 0-1..5-6 take N = 10 (slice 0-1 uses the nearest SPT at 1 m, slice 5-6 the SPT at 5 m);
    # slices 6-7..9-10 take N = 8 (the SPT at 10 m is used for the tip only).
    driven = eng.pile_capacity_decourt(diameter=0.5, length=10, spt=spt, layers=layers)
    assert driven["Qs"] == pytest.approx(p * (6 * q10 + 4 * q8), abs=0.1)
    assert driven["Qp"] == pytest.approx(120 * 8 * ap, abs=0.05)
    bored = eng.pile_capacity_decourt(diameter=0.5, length=10, spt=spt, layers=layers, pile_type="bored")
    # beta: sand 0.5 for the five slices above 5 m, clay 0.8 below (slice class from mid-depth).
    assert bored["Qs"] == pytest.approx(p * (5 * q10 * 0.5 + q10 * 0.8 + 4 * q8 * 0.8), abs=0.1)
    assert bored["Qp"] == pytest.approx(0.85 * 120 * 8 * ap, abs=0.05)
    classes = [s["soil_class"] for s in driven["shaft"]["slices"]]
    assert classes == ["sand"] * 5 + ["clay"] * 5


def test_decourt_shaft_n_limits_and_tip_window():
    low = eng.pile_capacity_decourt(diameter=0.4, length=5, spt=_uniform(1), layers=SAND)
    assert low["Qs"] == pytest.approx(10 * (3 / 3 + 1) * math.pi * 0.4 * 5, abs=0.05)
    assert low["tip"]["Np"] == 1
    # Large diameter: tip window 9-11 m averages N at 9, 10 and 11 m.
    spt = [{"depth": float(d), "n": d * 2} for d in range(1, 13)]
    res = eng.pile_capacity_decourt(diameter=1.0, length=10, spt=spt, layers=SAND)
    assert res["tip"]["Np"] == pytest.approx((18 + 20 + 22) / 3)


def test_decourt_nearest_spt_when_window_empty():
    spt = [{"depth": d, "n": 12} for d in (1.5, 3.0, 4.5, 6.0, 7.5, 9.0)]
    spt[-1]["n"] = 30
    res = eng.pile_capacity_decourt(diameter=0.3, length=8.5, spt=spt, layers=SAND)
    assert res["tip"]["Np"] == 30
    assert any("nearest SPT" in n for n in res["notes"])


def test_decourt_unknown_uscs_is_clay():
    res = eng.pile_capacity_decourt(diameter=0.4, length=5, spt=_uniform(10),
                                    layers=[{"top": 0, "base": 15, "uscs": "XX"}])
    assert res["tip"]["soil_class"] == "clay"
    assert any("not recognised" in n for n in res["notes"])


def test_decourt_soil_class_mapping():
    assert eng.decourt_soil_class("CL") == "clay"
    assert eng.decourt_soil_class("cl-ml") == "clay"
    assert eng.decourt_soil_class("PT") == "clay"
    assert eng.decourt_soil_class("ML") == "sandy_silt"
    assert eng.decourt_soil_class("MH") == "clayey_silt"
    for s in ("SM", "SC", "SP", "SW", "GW", "GP", "GM", "GC", "SP-SM", "GW-GC"):
        assert eng.decourt_soil_class(s) == "sand"
    assert eng.decourt_soil_class("??") is None


def test_decourt_errors():
    ok = dict(diameter=0.4, length=10, spt=_uniform(20, deepest=8), layers=SAND)
    with pytest.raises(ValueError, match="deepest SPT"):
        eng.pile_capacity_decourt(**ok)
    eng.pile_capacity_decourt(**{**ok, "length": 9})  # within 1 m of the deepest SPT
    for bad in ({"diameter": -0.4}, {"length": 0}, {"pile_type": "screw"}, {"spt": []},
                {"layers": []}, {"fs_tip": 0}, {"spt": [{"depth": -1, "n": 5}]},
                {"spt": [{"depth": 1, "n": -5}]},
                {"layers": [{"top": 5, "base": 2, "uscs": "SP"}]}):
        with pytest.raises(ValueError):
            eng.pile_capacity_decourt(**{**ok, "length": 6, **bad})


def test_pile_profile():
    res = eng.pile_capacity_profile(diameter=0.4, spt=_uniform(20, deepest=12), layers=SAND)
    lengths = [r["length"] for r in res["profile"]]
    assert lengths == [float(x) for x in range(2, 13)]
    q = [r["Qallow"] for r in res["profile"]]
    assert all(b > a for a, b in zip(q, q[1:]))
    ten = next(r for r in res["profile"] if r["length"] == 10)
    assert ten["Qp"] == pytest.approx(1005.3, abs=0.05)
    assert _has_prelim(res)
    _json_ok(res)
    with pytest.raises(ValueError):
        eng.pile_capacity_profile(diameter=0.4, spt=[{"depth": 1, "n": 5}], layers=SAND)


# ---------------------------------------------------------------------------
# C) Consolidation settlement
# ---------------------------------------------------------------------------

LAYERS_NC = [
    {"top": 0, "base": 2, "gamma": 18, "Cc": 0, "e0": 0.6},
    {"top": 2, "base": 3, "gamma": 17, "Cc": 0.3, "e0": 1.0},
]


def test_consolidation_nc_hand_calc():
    res = eng.consolidation_settlement(layers=LAYERS_NC, q=100, B=2, L=2, Df=1)
    s0 = 18 * 2 + 17 * 0.5
    ds = 100 * 2 * 2 / ((2 + 1.5) * (2 + 1.5))
    s = 0.3 * 1 / (1 + 1.0) * math.log10((s0 + ds) / s0)
    clay = [r for r in res["sublayers"] if r["layer"] == 1]
    assert len(clay) == 1
    assert clay[0]["sigma_v0_eff"] == pytest.approx(s0, abs=0.05)
    assert clay[0]["delta_sigma"] == pytest.approx(ds, abs=0.05)
    assert res["total_settlement_mm"] == pytest.approx(s * 1000, abs=0.1)
    assert s * 1000 == pytest.approx(35.8, abs=0.1)
    assert _has_prelim(res)
    _json_ok(res)


def test_consolidation_strip_with_water_two_sublayers():
    layers = [{"top": 0, "base": 2, "gamma": 18, "gamma_sat": 20, "Cc": 0.4, "e0": 1.2}]
    res = eng.consolidation_settlement(layers=layers, q=50, B=1.5, gw_depth=0.5)
    expected = 0.0
    for mid in (0.5, 1.5):
        s0 = 18 * 0.5 + (20 - 9.81) * (mid - 0.5)
        ds = 50 * 1.5 / (1.5 + mid)
        expected += 0.4 * 1 / 2.2 * math.log10((s0 + ds) / s0)
    assert len(res["sublayers"]) == 2
    assert res["total_settlement_mm"] == pytest.approx(expected * 1000, abs=0.1)


def test_consolidation_oc_less_than_nc_and_mixed_branch():
    oc_layers = [dict(LAYERS_NC[0]), dict(LAYERS_NC[1], sigma_p=200)]
    nc = eng.consolidation_settlement(layers=LAYERS_NC, q=100, B=2, L=2, Df=1)
    oc = eng.consolidation_settlement(layers=oc_layers, q=100, B=2, L=2, Df=1)
    assert oc["total_settlement_mm"] < nc["total_settlement_mm"]
    s0 = 44.5
    ds = 400 / 3.5 ** 2
    assert oc["total_settlement_mm"] == pytest.approx(0.06 / 2 * math.log10((s0 + ds) / s0) * 1000, abs=0.1)
    # sigma_p between s0 and s0 + ds: recompression then virgin compression.
    mixed_layers = [dict(LAYERS_NC[0]), dict(LAYERS_NC[1], sigma_p=60, Cr=0.05)]
    mixed = eng.consolidation_settlement(layers=mixed_layers, q=100, B=2, L=2, Df=1)
    exp = 0.05 / 2 * math.log10(60 / s0) + 0.3 / 2 * math.log10((s0 + ds) / 60)
    assert mixed["total_settlement_mm"] == pytest.approx(exp * 1000, abs=0.1)
    assert mixed["sublayers"][-1]["state"] == "OC->NC"


def test_consolidation_stress_decreases_with_depth():
    layers = [{"top": 0, "base": 10, "gamma": 17, "Cc": 0.3, "e0": 1.0}]
    res = eng.consolidation_settlement(layers=layers, q=80, B=2, L=3, Df=1)
    ds = [r["delta_sigma"] for r in res["sublayers"]]
    assert len(ds) == 9
    assert all(b < a for a, b in zip(ds, ds[1:]))
    assert all(r["thickness"] <= 1.0 for r in res["sublayers"])


def test_consolidation_zero_load_and_errors():
    res = eng.consolidation_settlement(layers=LAYERS_NC, q=0, B=2)
    assert res["total_settlement_mm"] == 0.0
    for bad in (
        dict(layers=LAYERS_NC, q=-10, B=2),
        dict(layers=LAYERS_NC, q=10, B=0),
        dict(layers=LAYERS_NC, q=10, B=2, L=1),
        dict(layers=LAYERS_NC, q=10, B=2, Df=5),
        dict(layers=[{"top": 1, "base": 3, "gamma": 18, "Cc": 0.3, "e0": 1}], q=10, B=2),
        dict(layers=[{"top": 0, "base": 1, "gamma": 18, "Cc": 0.3, "e0": 1},
                     {"top": 1.5, "base": 3, "gamma": 18, "Cc": 0.3, "e0": 1}], q=10, B=2),
        dict(layers=[{"top": 0, "base": 3, "gamma": 18, "Cc": -0.1, "e0": 1}], q=10, B=2),
        dict(layers=[{"top": 0, "base": 3, "gamma": 18, "Cc": 0.3, "e0": 0}], q=10, B=2),
        dict(layers=[{"top": 0, "base": 3, "gamma": 18, "Cc": 0.3, "e0": 1, "sigma_p": -5}], q=10, B=2),
        dict(layers=[{"top": 0, "base": 3, "gamma": 9, "Cc": 0.3, "e0": 1}], q=10, B=2, gw_depth=0),
    ):
        with pytest.raises(ValueError):
            eng.consolidation_settlement(**bad)


# ---------------------------------------------------------------------------
# D) Liquefaction (Idriss & Boulanger 2014)
# ---------------------------------------------------------------------------

def test_crr_msf_rd_values():
    n = 15.0
    expected = math.exp(n / 14.1 + (n / 126) ** 2 - (n / 23.6) ** 3 + (n / 25.4) ** 4 - 2.8)
    assert eng.crr_7p5_idriss_boulanger(15) == pytest.approx(0.156, abs=0.003)
    assert eng.crr_7p5_idriss_boulanger(15) == pytest.approx(expected, rel=1e-9)
    assert eng.crr_7p5_idriss_boulanger(40) == 2.0
    for n1 in (5, 15, 25, 35):
        assert eng.msf_idriss_boulanger(n1, 7.5) == pytest.approx(1.0, abs=0.01)
    assert eng.msf_idriss_boulanger(20, 6.0) > 1.0
    assert eng.rd_idriss_boulanger(0, 7.5) == pytest.approx(1.0, abs=0.01)
    assert eng.rd_idriss_boulanger(10, 7.5) < eng.rd_idriss_boulanger(5, 7.5) < 1.0


def _ib_hand(n, z, sv, sve, fc, amax, m=7.5, rod_extra=1.5):
    """Independent hand implementation for one SPT (CE = CB = CS = 1)."""
    rod = z + rod_extra
    cr = 0.75 if rod < 3 else 0.80 if rod < 4 else 0.85 if rod < 6 else 0.95 if rod < 10 else 1.0
    n60 = n * cr
    dn = math.exp(1.63 + 9.7 / (fc + 0.01) - (15.7 / (fc + 0.01)) ** 2)
    ncs = n60 + dn
    for _ in range(200):
        mm = 0.784 - 0.0768 * math.sqrt(min(ncs, 46))
        cn = min(1.7, (101.325 / sve) ** mm)
        ncs = cn * n60 + dn
    a = -1.012 - 1.126 * math.sin(z / 11.73 + 5.133)
    b = 0.106 + 0.118 * math.sin(z / 11.28 + 5.142)
    rd = math.exp(a + b * m)
    csr = 0.65 * sv / sve * amax * rd
    crr = math.exp(ncs / 14.1 + (ncs / 126) ** 2 - (ncs / 23.6) ** 3 + (ncs / 25.4) ** 4 - 2.8)
    msf_max = min(2.2, 1.09 + (ncs / 31.5) ** 2)
    msf = 1 + (msf_max - 1) * (8.64 * math.exp(-m / 4) - 1.325)
    cs = min(0.3, 1 / (18.9 - 2.55 * math.sqrt(ncs)))
    ks = min(1.1, 1 - cs * math.log(sve / 101.325))
    return {"ncs": ncs, "csr": csr, "fs": crr * msf * ks / csr}


def test_liquefaction_loose_sand_and_hand_calc():
    layers = [{"top": 0, "base": 10, "uscs": "SP", "gamma": 18, "gamma_sat": 19}]
    res = eng.liquefaction_spt(spt=[{"depth": 4, "n": 5}], layers=layers, gw_depth=1, amax_g=0.3)
    row = res["rows"][0]
    sv = 18 * 1 + 19 * 3
    sve = sv - 9.81 * 3
    hand = _ib_hand(5, 4.0, sv, sve, 5.0, 0.3)
    assert row["sigma_v"] == pytest.approx(sv, abs=0.05)
    assert row["sigma_v_eff"] == pytest.approx(sve, abs=0.05)
    assert row["CR"] == 0.85
    assert row["N1_60cs"] == pytest.approx(hand["ncs"], abs=0.05)
    assert row["CSR"] == pytest.approx(hand["csr"], abs=0.001)
    assert row["FS"] == pytest.approx(hand["fs"], abs=0.001)
    assert row["FS"] < 1.0
    assert row["status"] == "liquefiable"
    assert res["summary"]["n_liquefiable"] == 1
    assert res["summary"]["shallowest_liquefiable_depth"] == 4.0
    assert _has_prelim(res)
    _json_ok(res)


def test_liquefaction_skips_and_statuses():
    layers = [
        {"top": 0, "base": 3, "uscs": "SM"},
        {"top": 3, "base": 8, "uscs": "CH"},
        {"top": 8, "base": 12, "uscs": "SM", "pi": 12},
        {"top": 12, "base": 25, "uscs": "SP"},
    ]
    spt = [{"depth": 1.5, "n": 4}, {"depth": 5, "n": 3}, {"depth": 10, "n": 5},
           {"depth": 15, "n": 45}, {"depth": 22, "n": 5}]
    res = eng.liquefaction_spt(spt=spt, layers=layers, gw_depth=2, amax_g=0.3)
    status = [r["status"] for r in res["rows"]]
    assert status[0] == "above water table"
    assert status[1] == "not susceptible (clay-like behaviour)"
    assert status[2] == "not susceptible (clay-like behaviour)"
    assert status[3] == "not liquefiable"
    assert "37.5" in res["rows"][3]["remark"]
    assert status[4] == "below 20 m (not evaluated)"
    assert res["rows"][0]["FS"] is None
    assert res["summary"]["n_evaluated"] == 1
    assert res["summary"]["shallowest_liquefiable_depth"] is None


def test_liquefaction_fines_increase_resistance():
    base = {"top": 0, "base": 10, "uscs": "SP"}
    clean = eng.liquefaction_spt(spt=[{"depth": 5, "n": 10}], layers=[base], gw_depth=1, amax_g=0.25)
    silty = eng.liquefaction_spt(spt=[{"depth": 5, "n": 10}], layers=[dict(base, fines=35)],
                                 gw_depth=1, amax_g=0.25)
    assert silty["rows"][0]["N1_60cs"] > clean["rows"][0]["N1_60cs"]
    assert silty["rows"][0]["FS"] > clean["rows"][0]["FS"]
    fc = 35.0
    assert silty["rows"][0]["delta_n1_60"] == pytest.approx(
        math.exp(1.63 + 9.7 / (fc + 0.01) - (15.7 / (fc + 0.01)) ** 2), abs=0.01)


def test_liquefaction_equipment_corrections():
    layers = [{"top": 0, "base": 15, "uscs": "SP"}]
    spt = [{"depth": 10, "n": 10}]
    res = eng.liquefaction_spt(spt=spt, layers=layers, gw_depth=1, amax_g=0.2,
                               energy_ratio=75, borehole_diameter_mm=150)
    row = res["rows"][0]
    assert row["CE"] == 1.25
    assert row["CB"] == 1.05
    assert row["CR"] == 1.0
    assert row["N60"] == pytest.approx(10 * 1.25 * 1.05, abs=0.05)
    res200 = eng.liquefaction_spt(spt=spt, layers=layers, gw_depth=1, amax_g=0.2, borehole_diameter_mm=200)
    assert res200["rows"][0]["CB"] == 1.15


def test_liquefaction_errors():
    layers = [{"top": 0, "base": 10, "uscs": "SP"}]
    spt = [{"depth": 4, "n": 5}]
    for bad in (dict(amax_g=0), dict(amax_g=-0.2), dict(gw_depth=-1), dict(magnitude=12),
                dict(energy_ratio=0), dict(borehole_diameter_mm=0),
                dict(spt=[{"depth": 12, "n": 5}]),
                dict(layers=[{"top": 0, "base": 10, "uscs": "SP", "fines": 120}]),
                dict(layers=[{"top": 1, "base": 10, "uscs": "SP"}])):
        kwargs = dict(spt=spt, layers=layers, gw_depth=1, amax_g=0.3)
        kwargs.update(bad)
        with pytest.raises(ValueError):
            eng.liquefaction_spt(**kwargs)
