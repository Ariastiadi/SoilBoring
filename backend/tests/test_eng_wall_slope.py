"""Retaining wall and slope stability analyses. Expected values come from published examples
(Das; ACADS benchmark 1(a); Taylor's stability number) or are written out here by hand."""
import json
import math
import time

import pytest

from backend.app import eng_slope, eng_wall
from backend.app.calcbase import CalcError

# Das, Principles of Foundation Engineering, cantilever retaining wall example (7th ed. Example 8.1):
# H' = 7.158 m, Ka = 0.350, Pa = 161.4 kN/m, sum V = 470.45 kN/m, MR = 1128.98, MO = 379.25 kN.m/m,
# FS overturning 2.98, FS sliding 2.73 (with Pp = 215 kN/m), e = 0.406 m, q_toe = 189.2 kPa,
# q_heel = 45.99 kPa, qu = 574.07 kPa, FS bearing 3.03.
DAS_WALL = dict(H=6.7, toe=0.7, heel=2.6, t_top=0.5, t_bot=0.7, D_base=0.7, gamma_c=23.58, gamma=18, phi=30, c=0, beta=10,
                found_phi=20, found_c=40, found_gamma=19, D_front=1.5, passive="yes")


def _v(result, label):
    return next(v["value"] for v in result["values"] if v["label"] == label)


def _check(result, name, case="Static"):
    return next(c for c in result["checks"] if c["check"] == name and c["case"] == case)


def test_das_cantilever_wall_example():
    r = eng_wall.analyse(DAS_WALL)
    json.dumps(r, allow_nan=False)
    assert _v(r, "Height of the pressure plane") == pytest.approx(7.158, abs=0.002)
    assert _v(r, "Ka (c' = 0)") == pytest.approx(0.350, abs=0.001)
    assert _v(r, "Active thrust Pa") == pytest.approx(161.4, rel=0.005)
    assert _v(r, "ΣV") == pytest.approx(470.45, rel=0.003)
    assert _v(r, "ΣM resisting") == pytest.approx(1128.98, rel=0.003)
    assert _v(r, "ΣM overturning") == pytest.approx(379.25, rel=0.003)
    assert _check(r, "Overturning FS")["value"] == pytest.approx(2.98, abs=0.01)
    assert _check(r, "Sliding FS")["value"] == pytest.approx(2.73, abs=0.01)
    assert _v(r, "Passive resistance Pp") == pytest.approx(215.0, rel=0.003)
    assert _v(r, "Eccentricity e") == pytest.approx(0.406, abs=0.002)
    assert _v(r, "q_max (toe)") == pytest.approx(189.2, abs=0.5)
    assert _v(r, "q_min (heel)") == pytest.approx(45.99, abs=0.5)
    # Das takes Fcd = 1 + 0.4 D/B'; Hansen's Fcd for phi > 0 is used here, about 0.6 % lower qu.
    assert _v(r, "Ultimate bearing capacity qu") == pytest.approx(574.07, rel=0.01)
    assert _check(r, "Bearing FS = qu / q_max")["value"] == pytest.approx(3.03, abs=0.03)
    assert r["status"] == "pass" and all(c["ok"] for c in r["checks"])
    assert any("Preliminary" in n for n in r["notes"]) and r["standards"]
    assert r["section"]["polygons"] and r["charts"][0]["series"]


def test_without_passive_sliding_drops_to_das_value():
    # Das: "if Pp is ignored, FS(sliding) = 1.37"
    r = eng_wall.analyse({**DAS_WALL, "passive": "no"})
    assert _check(r, "Sliding FS")["value"] == pytest.approx(1.37, abs=0.01)
    assert not _check(r, "Sliding FS")["ok"] and r["status"] == "fail"


def test_earth_pressure_coefficients():
    assert eng_wall.rankine_ka(30, 0) == pytest.approx(1 / 3)
    assert eng_wall.rankine_kp(30) == pytest.approx(3.0)
    # Coulomb with delta = alpha = beta on a vertical back equals Rankine for sloping ground.
    assert eng_wall.coulomb_ka(30, 10, 0, 10) == pytest.approx(eng_wall.rankine_ka(30, 10), rel=1e-9)
    # Das, gravity wall example: phi' = 32, delta = 2/3 phi', theta = 15, alpha = 0 -> Ka = 0.4023
    assert eng_wall.coulomb_ka(32, 32 * 2 / 3, 15, 0) == pytest.approx(0.4023, abs=0.0002)
    # Mazindrani & Ganjali reduces to Rankine for c' = 0, and gives less pressure with c' > 0.
    assert eng_wall.mazindrani_ka(30, 10, 0, 50) * math.cos(math.radians(10)) == pytest.approx(eng_wall.rankine_ka(30, 10))
    assert eng_wall.mazindrani_ka(30, 0, 10, 50) == pytest.approx(1 / 3 - 2 * 10 * math.sqrt(1 / 3) / 50, rel=1e-6)
    # M-O with kh = kv = 0 is Coulomb.
    assert eng_wall.mononobe_okabe_kae(34, 17, 5, 5, 0, 0) == pytest.approx(eng_wall.coulomb_ka(34, 17, 5, 5))


def _trial_wedge(phi, delta, theta, alpha, kh=0.0, kv=0.0, H=1.0, gamma=1.0):
    """Largest thrust over plane failure wedges behind a back face inclined theta (soil on the face)."""
    ph, dl, th, al = (math.radians(x) for x in (phi, delta, theta, alpha))
    best = 0.0
    for k in range(1, 4000):
        rho = math.radians(k * 90 / 4000)
        bx, by = -H * math.tan(th), H
        # failure plane from (0,0) at rho meets the ground y = H + (x - bx) tan(alpha)
        den = math.sin(rho) - math.cos(rho) * math.tan(al)
        if den <= 1e-9:
            continue
        s = (H - bx * math.tan(al)) / den
        cx, cy = s * math.cos(rho), s * math.sin(rho)
        area = 0.5 * abs(bx * cy - cx * by)
        W = gamma * area
        a11, a12, b1 = math.cos(th + dl), -math.sin(rho - ph), kh * W
        a21, a22, b2 = math.sin(th + dl), math.cos(rho - ph), (1 - kv) * W
        det = a11 * a22 - a12 * a21
        P = (b1 * a22 - a12 * b2) / det
        best = max(best, P)
    return 2 * best / (gamma * H * H)


@pytest.mark.parametrize("phi,delta,theta,alpha,kh,kv", [
    (30, 20, 0, 0, 0, 0), (32, 21.33, 15, 0, 0, 0), (30, 15, 10, 10, 0, 0), (35, 17.5, 0, 5, 0.2, 0), (34, 22, 8, 0, 0.15, 0.05),
])
def test_coulomb_and_mononobe_okabe_match_trial_wedge(phi, delta, theta, alpha, kh, kv):
    k = eng_wall.mononobe_okabe_kae(phi, delta, theta, alpha, kh, kv) * (1 - kv)
    assert k == pytest.approx(_trial_wedge(phi, delta, theta, alpha, kh, kv), rel=2e-3)


def test_wall_cohesion_tension_zone_and_water():
    base = {**DAS_WALL, "beta": 0}
    dry = eng_wall.analyse(base)
    coh = eng_wall.analyse({**base, "c": 10})
    # tension zone depth zc = 2c / (gamma sqrt(Ka)) for level ground and q = 0
    assert _v(coh, "Depth of the tension zone") == pytest.approx(2 * 10 / (18 * math.sqrt(1 / 3)), abs=0.03)
    assert _v(coh, "Active thrust Pa") < _v(dry, "Active thrust Pa")
    wet = eng_wall.analyse({**base, "gw": 2.0})
    assert _check(wet, "Overturning FS")["value"] < _check(dry, "Overturning FS")["value"]
    assert any("Groundwater behind the wall" in n for n in wet["notes"])
    # surcharge q adds q Ka H to the thrust (Rankine, level ground, c = 0)
    sur = eng_wall.analyse({**base, "q": 20})
    assert _v(sur, "Active thrust Pa") - _v(dry, "Active thrust Pa") == pytest.approx(20 / 3 * 6.7, rel=0.01)


def test_wall_seismic_and_coulomb_and_errors():
    r = eng_wall.analyse({**DAS_WALL, "kh": 0.15})
    assert _check(r, "Overturning FS", "Seismic")["value"] < _check(r, "Overturning FS")["value"]
    assert _v(r, "K_AE (Mononobe–Okabe)") > _v(r, "Ka (c' = 0)")
    assert "FS overturning, seismic" in r["summary"]
    g = eng_wall.analyse({**DAS_WALL, "method": "coulomb", "wall_type": "gravity", "heel": 0.0, "t_top": 0.6, "t_bot": 2.4,
                          "back_batter": 0.8, "toe": 0.6, "beta": 0})
    assert _v(g, "Plane inclination from vertical θ") == pytest.approx(math.degrees(math.atan2(0.8, 6.7)), abs=0.01)
    json.dumps(g, allow_nan=False)
    with pytest.raises(CalcError):
        eng_wall.analyse({**DAS_WALL, "beta": 30})
    with pytest.raises(CalcError):
        eng_wall.analyse({**DAS_WALL, "kh": 0.5})  # phi - beta - psi < 0
    with pytest.raises(CalcError):
        eng_wall.analyse({**DAS_WALL, "t_bot": 0.3})
    tiny = eng_wall.analyse({**DAS_WALL, "heel": 0.0, "toe": 0.0, "passive": "no"})
    assert tiny["status"] == "fail" and any("overturns" in n for n in tiny["notes"])
    json.dumps(tiny, allow_nan=False)


# ---------------------------------------------------------------------------
# Slopes
# ---------------------------------------------------------------------------

def test_infinite_slope_hand_calcs():
    # Das: seepage with the water table at the surface (m = 1):
    # FS = c'/(gsat z cos^2 b tan b) + g' tan phi' / (gsat tan b)
    b, z, gs, c, phi = math.radians(20), 5.0, 20.0, 10.0, math.radians(25)
    expected = c / (gs * z * math.cos(b) ** 2 * math.tan(b)) + (gs - 9.81) * math.tan(phi) / (gs * math.tan(b))
    r = eng_slope.analyse({"mode": "infinite", "beta": 20, "z": 5, "m": 1, "gamma": 18, "gamma_sat": 20, "c": 10, "phi": 25})
    assert r["checks"][0]["value"] == pytest.approx(expected, abs=0.001)
    assert expected == pytest.approx(0.964, abs=0.001)
    dry = eng_slope.infinite_slope(c=0, phi_deg=35, gamma=18, gamma_sat=20, beta_deg=30, z=4, m=0)
    assert dry["FS"] == pytest.approx(math.tan(math.radians(35)) / math.tan(math.radians(30)))
    # pseudo-static, dry, c' = 0: FS = (cos b - kh sin b) tan phi / (sin b + kh cos b)
    eq = eng_slope.infinite_slope(c=0, phi_deg=35, gamma=18, gamma_sat=20, beta_deg=30, z=4, m=0, kh=0.1)
    b30 = math.radians(30)
    assert eq["FS"] == pytest.approx((math.cos(b30) - 0.1 * math.sin(b30)) * math.tan(math.radians(35)) / (math.sin(b30) + 0.1 * math.cos(b30)))
    assert r["status"] == "fail" and "Failure expected" in r["classification"]


ACADS_1A = {"mode": "circular", "geometry": "points",
            "surface": [{"x": 20, "y": 25}, {"x": 30, "y": 25}, {"x": 50, "y": 35}, {"x": 70, "y": 35}],
            "layers": [{"gamma": 20, "c": 3, "phi": 19.6}], "depth_limit": 10}


def test_acads_benchmark_1a_bishop():
    # Giam & Donald (1989) ACADS problem 1(a): referee FS = 1.00 (Bishop programs report 0.98-1.00).
    t0 = time.perf_counter()
    r = eng_slope.analyse(ACADS_1A)
    assert time.perf_counter() - t0 < 2.0
    fs_b = r["checks"][0]["value"]
    fs_o = next(row for row in r["tables"][0]["rows"] if row[0] == 1)[5]
    assert fs_b == pytest.approx(1.00, abs=0.03)
    assert fs_o < fs_b  # ordinary method of slices is conservative here
    assert len(r["tables"][2]["rows"]) == 40
    json.dumps(r, allow_nan=False)


def test_simple_geometry_matches_points_geometry():
    simple = eng_slope.analyse({"mode": "circular", "H": 10, "beta": math.degrees(math.atan(0.5)),
                                "layers": [{"gamma": 20, "c": 3, "phi": 19.6}], "depth_limit": 10})
    assert simple["checks"][0]["value"] == pytest.approx(eng_slope.analyse(ACADS_1A)["checks"][0]["value"], abs=0.01)


def test_taylor_undrained_toe_circle():
    # Taylor (1937) stability number for phi = 0 and beta = 60 deg: m = c / (F gamma H) = 0.191 (toe circle).
    r = eng_slope.analyse({"mode": "circular", "H": 10, "beta": 60, "layers": [{"gamma": 20, "c": 40, "phi": 0}]})
    assert r["checks"][0]["value"] == pytest.approx(40 / (0.191 * 20 * 10), rel=0.02)


def test_cohesionless_slope_tends_to_infinite_slope():
    r = eng_slope.analyse({"mode": "circular", "H": 10, "beta": 30, "layers": [{"gamma": 20, "c": 0, "phi": 35}]})
    inf = math.tan(math.radians(35)) / math.tan(math.radians(30))
    assert inf <= r["checks"][0]["value"] <= inf * 1.06


def test_water_surcharge_and_seismic_lower_the_fs():
    base = {"mode": "circular", "H": 10, "beta": 35, "bench_w": 3,
            "layers": [{"bottom": 5, "gamma": 18, "c": 10, "phi": 25}, {"gamma": 19, "c": 20, "phi": 28}]}
    dry = eng_slope.analyse(base)["checks"][0]["value"]
    wet = eng_slope.analyse({**base, "water": "phreatic", "phreatic": [{"x": 0, "y": 0}, {"x": 30, "y": 6}, {"x": 60, "y": 7}]})["checks"][0]["value"]
    ru = eng_slope.analyse({**base, "water": "ru", "ru": 0.3})["checks"][0]["value"]
    loaded = eng_slope.analyse({**base, "q": 30})["checks"][0]["value"]
    t0 = time.perf_counter()
    quake = eng_slope.analyse({**base, "kh": 0.15, "q": 30, "water": "ru", "ru": 0.2})
    assert time.perf_counter() - t0 < 2.0
    assert wet < dry and ru < dry and loaded < dry and quake["checks"][0]["value"] < loaded
    assert quake["checks"][0]["required"] == "≥ 1.1"


def test_classification_bands():
    assert eng_slope.classify(1.6, False).startswith("Stable")
    assert eng_slope.classify(1.3, False).startswith("Marginal")
    assert eng_slope.classify(1.1, False).startswith("Unsafe")
    assert eng_slope.classify(0.9, False).startswith("Failure")
    assert eng_slope.classify(1.12, True).startswith("Stable")


def test_slope_input_errors():
    with pytest.raises(CalcError):
        eng_slope.analyse({"mode": "circular", "H": 10, "beta": 30, "layers": []})
    with pytest.raises(CalcError):
        eng_slope.analyse({"mode": "circular", "H": 10, "beta": 30,
                           "layers": [{"bottom": 2, "gamma": 18, "c": 5, "phi": 30}, {"bottom": 4, "gamma": 18, "c": 5, "phi": 30}]})
    with pytest.raises(CalcError):
        eng_slope.analyse({**ACADS_1A, "surface": [{"x": 0, "y": 10}, {"x": 10, "y": 0}, {"x": 20, "y": 0}]})
    with pytest.raises(CalcError):
        eng_slope.analyse({"mode": "circular", "H": 10, "beta": 30, "layers": [{"gamma": 18, "c": 0, "phi": 0}]})


def test_api_runs_and_saves_new_analyses(client, admin_headers):
    res = client.post("/api/analyses/run", json={"type": "retaining_wall", "inputs": DAS_WALL}, headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json()["summary"].startswith("FS overturning = 2.98")
    res = client.post("/api/analyses/run", json={"type": "slope", "inputs": {**ACADS_1A, "n_slices": 30}}, headers=admin_headers)
    assert res.status_code == 200 and len(res.json()["tables"][2]["rows"]) == 30
    bad = client.post("/api/analyses/run", json={"type": "slope", "inputs": {"mode": "circular", "H": 10, "beta": 30}}, headers=admin_headers)
    assert bad.status_code == 422 and "soil layer" in bad.json()["detail"]
    saved = client.post("/api/records/analyses", json={"title": "Dinding penahan STA 1+200", "type": "retaining_wall", "inputs": DAS_WALL},
                        headers=admin_headers)
    assert saved.status_code == 201, saved.text
    assert saved.json()["results"]["status"] == "pass" and saved.json()["summary"].startswith("FS overturning")
