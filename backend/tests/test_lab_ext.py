"""Lab tests 05.19-05.23: chemistry, permeability, point load, relative density, dispersivity.

Expected numbers are worked by hand in the comments.
"""
import copy
import math

import pytest

from backend.app import analysis_runner, calc_lab_ext as c, records, sheets
from backend.app.calcbase import CalcError
from backend.app.sheets_lab import EXAMPLES, LAB_RESULTS, LAB_TESTS

from .conftest import sample_report


def val(out, label):
    for v in out["values"]:
        if v["label"] == label:
            return v["value"]
    raise AssertionError(f"no value {label!r} in {[v['label'] for v in out['values']]}")


def ex(key, **changes):
    data = copy.deepcopy(EXAMPLES[key])
    data.update(changes)
    return data


def test_new_sheets_are_registered_after_05_18():
    keys = [k for k, _ in LAB_TESTS]
    codes = {s.key: s.code for s in sheets.all_sheets("lab")}
    for key, code in (("chemistry", "05.19"), ("permeability_lab", "05.20"), ("point_load", "05.21"),
                      ("relative_density", "05.22"), ("dispersivity", "05.23")):
        assert key in keys and key in LAB_RESULTS and codes[key] == code
    assert keys.index("chemistry") == keys.index("slake_durability") + 1


# --------------------------------------------------------------------------- #
# 05.19 Chemistry
# --------------------------------------------------------------------------- #

def test_chemistry_example_by_hand():
    out = c.chemistry(ex("chemistry"))
    lab = out["lab"]
    # SO4 = 0.0365 g BaSO4 × 96.06/233.39 / 10 g × 100 = 0.1502 %  -> S1 (0.10 ≤ SO4 < 0.20)
    assert lab["so4_soil"] == pytest.approx(0.150, abs=0.001)
    # Cl = (2.85 − 0.15) mL × 0.0141 N × 35 450 / 50 mL = 26.99 mg/L
    assert lab["cl_water"] == pytest.approx(26.99, abs=0.05)  # stored to 0.1 mg/L
    # water 420 mg/L -> S1 as well; S1: w/cm 0.50, f'c 28 MPa (ACI 318-19 Table 19.3.2.1)
    assert lab["exposure"] == "S1"
    assert val(out, "Maximum w/cm (governing)") == 0.5 and val(out, "Minimum f'c (governing)") == 28.0
    # LOI: (45.00 − 43.60) / (45.00 − 20.00) = 5.6 %
    assert lab["organic"] == pytest.approx(5.6)
    # Resistivity 1800 Ω·cm < 2000: aggressive to steel; pH 6.6, Cl 180 ppm, SO4 1502 ppm are not.
    assert lab["steel"] == "aggressive" and val(out, "Corrosion criteria met") == "1 / 4"
    assert lab["ph_soil"] == 6.6 and lab["resistivity"] == 1800


@pytest.mark.parametrize("pct,cls", [(0.0, "S0"), (0.099, "S0"), (0.10, "S1"), (0.199, "S1"), (0.20, "S2"), (2.0, "S2"), (2.01, "S3")])
def test_sulfate_classes_soil(pct, cls):
    assert c.sulfate_class_soil(pct) == cls


@pytest.mark.parametrize("ppm,cls", [(149, "S0"), (150, "S1"), (1499, "S1"), (1500, "S2"), (10000, "S2"), (10001, "S3")])
def test_sulfate_classes_water(ppm, cls):
    assert c.sulfate_class_water(ppm) == cls


def test_chemistry_worst_value_seawater_and_chloride():
    out = c.chemistry({"soil": [{"so4_pct": 0.05, "ph": 7.2}, {"so4_pct": 2.5, "ph": 5.0}], "water": [{"cl": 600, "so4": 100}]})
    assert out["lab"]["exposure"] == "S3"  # 2.5 % governs over 0.05 %
    assert val(out, "Chloride exposure class (reinforced concrete)") == "C2"  # 600 > 500 ppm
    # S3 w/cm 0.45 and C2 w/cm 0.40 -> 0.40; f'c max(31, 35) = 35 MPa
    assert val(out, "Maximum w/cm (governing)") == 0.4 and val(out, "Minimum f'c (governing)") == 35.0
    # pH 5.0 < 5.5, Cl 600 > 500, SO4 25 000 ppm > 2000: three of three measured indicators
    assert out["lab"]["steel"] == "aggressive" and val(out, "Corrosion criteria met") == "3 / 3"
    sea = c.chemistry({"water": [{"so4": 50, "ph": 7.8}], "seawater": True})
    assert sea["lab"]["exposure"] == "S1" and val(sea, "Chloride exposure class (reinforced concrete)") == "C2"
    clean = c.chemistry({"soil": [{"ph": 7, "so4_pct": 0.02, "cl": 50, "resistivity": 5000}]})
    assert clean["lab"]["exposure"] == "S0" and clean["lab"]["steel"] == "not_aggressive"
    assert val(clean, "Maximum w/cm (governing)") == "No limit"


def test_chemistry_input_checks():
    with pytest.raises(CalcError):
        c.chemistry({})
    with pytest.raises(CalcError):
        c.chemistry({"soil": [{"ph": 15}]})
    with pytest.raises(CalcError):
        c.chemistry({"soil": [{"baso4": 0.1}]})  # no aliquot mass
    with pytest.raises(CalcError):
        c.chemistry({"loi": [{"m_dish": 20, "m_dry": 30, "m_ash": 31}]})  # ash heavier than the dry soil


# --------------------------------------------------------------------------- #
# 05.20 Permeability
# --------------------------------------------------------------------------- #

def test_constant_head_by_hand():
    out = c.permeability_lab({"method": "constant", "diameter": 10, "length": 15,
                              "constant_trials": [{"head": 60, "volume": 250, "time": 120, "temp": 25}]})
    # A = π·10²/4 = 78.540 cm²; kT = 250·15 / (78.540·60·120) = 6.6314e-3 cm/s
    # η25/η20 = 0.00895/0.01009 = 0.88702 -> k20 = 5.882e-3 cm/s
    assert out["lab"]["k"] == pytest.approx(5.882e-3, rel=1e-3)
    assert val(out, "Degree of permeability") == "Medium"  # 1e-3 < k ≤ 1e-1 (Terzaghi & Peck)


def test_falling_head_by_hand():
    out = c.permeability_lab({"method": "falling", "diameter": 10, "length": 12, "standpipe": 1.0,
                              "falling_trials": [{"h1": 100, "h2": 80, "time": 600, "temp": 20}] * 3})
    # a/A = (1/10)² = 0.01; k = 0.01·12/600 · ln(100/80) = 2e-4 · 0.22314 = 4.463e-5 cm/s
    assert out["lab"]["k"] == pytest.approx(4.463e-5, rel=1e-3)
    assert val(out, "Degree of permeability") == "Low"
    assert c.permeability_class(5e-8) == "Practically impermeable"


def test_permeability_example_and_checks():
    out = c.permeability_lab(ex("permeability_lab"))
    assert out["lab"]["k"] == pytest.approx(5.824e-3, rel=2e-3)  # mean of 5.882, 5.765 and 5.824 e-3
    assert out["lab"]["e"] == pytest.approx(0.656, abs=0.001)  # ρd = 1885/1178.1 = 1.600; e = 2.65/1.600 − 1
    with pytest.raises(CalcError):
        c.permeability_lab({"method": "falling", "diameter": 10, "length": 12, "standpipe": 1,
                            "falling_trials": [{"h1": 50, "h2": 80, "time": 60}]})
    with pytest.raises(CalcError):
        c.permeability_lab({"method": "constant", "diameter": 10, "length": 12, "constant_trials": [{"head": 10, "volume": 5, "time": 6, "temp": 50}]})


# --------------------------------------------------------------------------- #
# 05.21 Point load
# --------------------------------------------------------------------------- #

def test_point_load_by_hand():
    out = c.point_load({"specimens": [{"type": "diametral", "d": 50, "load": 5}]})
    # Is = 5000 N / 50² mm² = 2.0 MPa; F = (50/50)^0.45 = 1; UCS = 22 × 2.0 = 44 MPa
    assert out["lab"]["is50"] == 2.0 and out["lab"]["ucs"] == 44.0
    assert val(out, "Strength (ISRM 1985)") == "High"  # 1–3 MPa
    assert val(out, "Rock strength grade (ISRM 1981)") == "R3 – Medium strong"  # 25–50 MPa
    axial = c.point_load({"k_factor": 24, "specimens": [{"type": "axial", "d": 40, "w": 50, "load": 6}]})
    # De² = 4·50·40/π = 2546.5 mm²; Is = 6000/2546.5 = 2.3562; De = 50.463; F = 1.00415; Is(50) = 2.366
    assert axial["lab"]["is50"] == pytest.approx(2.37, abs=0.005)
    assert axial["lab"]["ucs"] == pytest.approx(24 * 2.366, abs=0.1)


def test_point_load_mean_drops_extremes():
    assert c.trimmed_mean([float(x) for x in range(1, 11)]) == (5.5, 4)  # 3..8
    assert c.trimmed_mean([1, 2, 3, 4, 5, 100]) == (3.5, 2)  # without 1 and 100
    assert c.trimmed_mean([1, 2, 6]) == (3.0, 0)
    out = c.point_load({"specimens": [{"d": 50, "load": 5}, {"d": 50, "load": 50, "valid": "invalid"}]})
    assert out["lab"]["n"] == 1 and out["lab"]["is50"] == 2.0  # the invalid test is left out
    with pytest.raises(CalcError):
        c.point_load({"specimens": [{"type": "axial", "d": 40, "load": 6}]})  # no width
    with pytest.raises(CalcError):
        c.point_load({"specimens": [{"d": 50, "load": 5, "valid": "invalid"}]})


# --------------------------------------------------------------------------- #
# 05.22 Relative density
# --------------------------------------------------------------------------- #

def test_relative_density_by_hand():
    out = c.relative_density({"rho_min_manual": 1.40, "rho_max_manual": 1.75, "gs": 2.65, "field": [{"rho_d": 1.60}]})
    # Dr = 1.75 (1.60 − 1.40) / (1.60 (1.75 − 1.40)) = 0.35 / 0.56 = 62.5 %
    assert out["lab"]["dr"] == 62.5
    # emax = 2.65/1.40 − 1 = 0.893; emin = 2.65/1.75 − 1 = 0.514; (0.893 − 0.656)/(0.893 − 0.514) = 0.625
    assert out["lab"]["e_max"] == pytest.approx(0.893, abs=0.001) and out["lab"]["e_min"] == pytest.approx(0.514, abs=0.001)
    assert val(out, "Density") == "Medium dense"
    assert val(out, "Friction angle φ' estimate (Meyerhof 1956)") == pytest.approx(37.4, abs=0.05)  # 28 + 0.15 × 62.5
    by_gamma = c.relative_density({"rho_min_manual": 1.40, "rho_max_manual": 1.75, "field": [{"gamma_d": 1.60 * 9.81}]})
    assert by_gamma["lab"]["dr"] == 62.5


def test_relative_density_example_trials():
    out = c.relative_density(ex("relative_density"))
    # ρmin = (8462 − 4500)/2830 = 1.400; ρmax = (9450 − 4500)/(2830 − 182.4·0.2) = 4950/2793.52 = 1.772
    assert out["lab"]["rho_min"] == pytest.approx(1.400, abs=0.0005)
    assert out["lab"]["rho_max"] == pytest.approx(1.772, abs=0.0005)
    assert out["lab"]["dr"] == pytest.approx(59.5, abs=0.1)
    with pytest.raises(CalcError):
        c.relative_density({"rho_min_manual": 1.7, "rho_max_manual": 1.5})
    loose = sheets.calculate("lab", "relative_density", {"rho_min_manual": 1.4, "rho_max_manual": 1.75, "field": [{"rho_d": 1.35}]})
    assert loose["summary"].startswith("Dr = -18.5") and "dr" not in loose["lab"]  # below zero: shown, not stored


# --------------------------------------------------------------------------- #
# 05.23 Dispersivity
# --------------------------------------------------------------------------- #

def test_dispersivity_governing_indicator():
    out = c.dispersivity(ex("dispersivity"))
    # crumb 2 -> intermediate; ND3 -> intermediate; 9/36 = 25 % dispersion -> non-dispersive
    assert out["lab"] == {"crumb_grade": 2, "pinhole_class": "ND3", "dispersion_pct": 25.0, "verdict": "intermediate"}
    worst = c.dispersivity({"crumbs": [{"g_2min": 1, "g_1h": 1, "g_6h": 1}], "pinhole_class": "D1"})
    assert worst["lab"]["verdict"] == "dispersive"
    dht = c.dispersivity({"finer_without": 20, "finer_with": 30})  # 66.7 % > 50 %
    assert dht["lab"]["verdict"] == "dispersive"
    assert c.dispersion_verdict(30) == "intermediate" and c.dispersion_verdict(29.9) == "non_dispersive"
    with pytest.raises(CalcError):
        c.dispersivity({})
    with pytest.raises(CalcError):
        c.dispersivity({"crumbs": [{"g_2min": 5}]})


# --------------------------------------------------------------------------- #
# Saved records and the analysis hook
# --------------------------------------------------------------------------- #

def test_saved_lab_test_copies_results(client, admin_headers):
    body = {"borehole_id": "BH-001", "sample_ref": "UDS-1", "depth_top": 2, "test_type": "chemistry",
            "status": "done", "raw": EXAMPLES["chemistry"]}
    res = client.post("/api/records/lab_tests", json=body, headers=admin_headers)
    assert res.status_code == 201, res.text
    assert res.json()["results"]["exposure"] == "S1" and res.json()["summary"].startswith("Class = S1")


def test_pile_analysis_gets_chemistry_notes(client, admin_headers):
    assert client.post("/api/reports", json=sample_report(BoreholeID="BH-P"), headers=admin_headers).status_code == 201
    depth = {"layers": [{"top": 0, "base": 30, "uscs": "CL"}],
             "spt": [{"depth": d, "seat": 3, "inc1": 6, "inc2": 8} for d in (2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22)]}
    assert client.put("/api/details/BH-P", json=depth, headers=admin_headers).status_code == 200
    records.save("lab_tests", {"borehole_id": "BH-P", "sample_ref": "S1", "depth_top": 3, "test_type": "chemistry",
                               "status": "done", "raw": {"soil": [{"so4_pct": 0.5, "resistivity": 900}]}}, "admin@example.com")
    out = analysis_runner.run("pile", {"borehole_id": "BH-P", "diameter": 0.6, "length": 12})
    assert c.PILE_SULFATE_NOTES["S2"] in out["notes"] and c.PILE_STEEL_NOTE in out["notes"]
    assert math.isfinite(out["Qallow"])
