"""Laboratory worksheets: calculations checked against the laboratory's example data."""
import copy
import math

import pytest

from backend.app import calc_lab, records, sheets
from backend.app.calcbase import CalcError
from backend.app.entities import ENTITIES
from backend.app.sheets_lab import EXAMPLES, LAB_RESULTS, LAB_TESTS, _bounded

KGCM2 = 98.0665


def ex(key, **changes):
    data = copy.deepcopy(EXAMPLES[key])
    data.update(changes)
    return data


def val(out, label):
    for v in out["values"]:
        if v["label"] == label:
            return v["value"]
    raise AssertionError(f"no value {label!r} in {[v['label'] for v in out['values']]}")


def rows_of(out, title):
    return next(t for t in out["tables"] if t["title"] == title)["rows"]


# --------------------------------------------------------------------------- #
# Catalogue and examples
# --------------------------------------------------------------------------- #

def test_catalogue_examples_and_result_fields():
    keys = [k for k, _ in LAB_TESTS]
    for key in ("moisture", "density", "specific_gravity", "grain_size", "atterberg", "compaction", "cbr_lab", "ucs",
                "triaxial", "triaxial_cu", "direct_shear", "consolidation", "swelling", "la_abrasion", "soundness",
                "slake_durability"):
        assert key in keys and key in LAB_RESULTS
    pages = {s.code: s for s in sheets.all_sheets("page") if s.group == "lab"}
    assert pages["05.01"].link == "samples" and pages["05.02"].link == "samples" and pages["05.03"].link == "labsummary"
    raw_field = ENTITIES["lab_tests"].field("raw")
    assert raw_field is not None
    codes = []
    for sheet in sheets.all_sheets("lab"):
        codes.append(sheet.code)
        assert sheet.standards and sheet.help and sheet.calc and sheet.example
        # The example is already in the cleaned shape: cleaning it changes nothing that matters.
        clean = records._clean_value(raw_field, sheet.example, "Test data", {"test_type": sheet.key}, lambda *_: True)
        for name, value in sheet.example.items():
            if isinstance(value, list):
                assert [{k: row[k] for k in ex_row} for row, ex_row in zip(clean[name], value)] == value, (sheet.key, name)
            else:
                assert clean[name] == value, (sheet.key, name)
        if sheet.key == "triaxial_cu":
            clean["ring_factor"] = 0.35  # the template gives no calibration for this ring
        out = sheets.calculate("lab", sheet.key, clean)
        assert out and out["summary"] and out["values"] and out["method"]
        allowed = {f.name for f in LAB_RESULTS[sheet.key]}
        assert set(out["lab"]) <= allowed, sheet.key
    assert codes == sorted(codes) and codes[0] == "05.04" and codes[-1] == "05.23"


def test_out_of_range_lab_values_are_not_copied_into_results():
    run = _bounded("direct_shear", lambda data: {"summary": "", "lab": {"c": -3.0, "phi": 25.0, "junk": 1}})
    assert run({})["lab"] == {"phi": 25.0}


# --------------------------------------------------------------------------- #
# 05.04 Water content and density
# --------------------------------------------------------------------------- #

def test_water_content_and_density():
    out = calc_lab.moisture(ex("moisture"))
    assert out["lab"]["w"] == pytest.approx(37.66, abs=0.01)
    assert val(out, "Dry density ρd") == pytest.approx(1.302, abs=0.001)
    assert val(out, "Bulk density ρ") == pytest.approx(1.792, abs=0.001)
    assert out["lab"]["gamma_bulk"] == pytest.approx(1.792 * 9.81, abs=0.02)
    second = calc_lab.moisture({"specimens": [{"m_wet": 87.16, "m_dry": 65.09, "m_tare": 32.64, "volume": 35.41}], "gs": 2.65})
    assert second["lab"]["w"] == pytest.approx(68.01, abs=0.01)
    assert val(second, "Dry density ρd") == pytest.approx(0.916, abs=0.001)
    assert val(second, "Bulk density ρ") == pytest.approx(1.540, abs=0.001)
    assert val(second, "Void ratio e") == pytest.approx(2.65 / 0.9164 - 1, abs=0.002)
    # Water content only: no density, averages ignore nothing.
    only_w = calc_lab.moisture({"specimens": [{"m_wet": 100.27, "m_dry": 82.18, "m_tare": 34.15}, {}]})
    assert only_w["lab"] == {"w": 37.66}
    with pytest.raises(CalcError, match="Enter the wet and the dry mass"):
        calc_lab.moisture({"specimens": [{"m_wet": 10.0}]})
    with pytest.raises(CalcError, match="dry soil mass must be greater"):
        calc_lab.moisture({"specimens": [{"m_wet": 10.0, "m_dry": 5.0, "m_tare": 6.0}]})
    with pytest.raises(CalcError, match="at least one specimen"):
        calc_lab.moisture({"specimens": []})


# --------------------------------------------------------------------------- #
# 05.05 Specific gravity
# --------------------------------------------------------------------------- #

def test_specific_gravity_and_pycnometer_calibration():
    out = calc_lab.specific_gravity(ex("specific_gravity"))
    g20 = [r[-1] for r in rows_of(out, "Determinations")]
    assert g20 == [pytest.approx(2.6354, abs=0.0006), pytest.approx(2.6350, abs=0.0006)]  # table: 4 digits
    assert out["lab"]["gs"] == pytest.approx(2.635, abs=0.001)
    assert val(out, "Standard deviation of Vp") == pytest.approx(0.0549, abs=0.0002)
    assert any("repeat the calibration" in n for n in out["notes"])
    second = calc_lab.specific_gravity({"determinations": [
        {"temp": 26.0, "m_ps": 52.854, "m_p": 42.612, "m_pw": 98.119, "m_pws": 104.465},
        {"temp": 26.0, "m_ps": 55.328, "m_p": 45.291, "m_pw": 102.692, "m_pws": 108.906}]})
    assert second["lab"]["gs"] == pytest.approx(2.623, abs=0.001)
    # Pycnometer + water from the calibrated volume when it was not weighed.
    cal = {"determinations": [{"pycnometer_no": "1", "temp": 25.0, "m_ps": 55.68, "m_p": 45.68, "m_pws": 109.3}],
           "calibration": [{"pycnometer_no": "1", "temp": 25.0, "m_p": 45.68, "m_pw": 103.0}]}
    expected = 10.0 / (10.0 + 103.0 - 109.3) * calc_lab.water_density(25) / calc_lab.water_density(20)
    assert calc_lab.specific_gravity(cal)["lab"]["gs"] == pytest.approx(expected, abs=0.001)
    with pytest.raises(CalcError, match="Temperature is required"):
        calc_lab.specific_gravity({"determinations": [{"m_ps": 60.0, "m_p": 40.0, "m_pw": 90.0, "m_pws": 102.0}]})
    with pytest.raises(CalcError, match="between 15 and 35"):
        calc_lab.specific_gravity({"determinations": [{"temp": 50.0, "m_ps": 60.0, "m_p": 40.0, "m_pw": 90.0, "m_pws": 102.0}]})


# --------------------------------------------------------------------------- #
# 05.06 Grain size
# --------------------------------------------------------------------------- #

def test_grain_size_template_method_matches_the_laboratory():
    out = calc_lab.grain_size(ex("grain_size", hydro_method="template"))
    passing = {r[1]: r[-1] for r in rows_of(out, "Sieve analysis")}
    assert passing[0.297] == pytest.approx(99.84, abs=0.01)
    assert passing[0.149] == pytest.approx(98.78, abs=0.01)
    assert passing[0.074] == pytest.approx(96.26, abs=0.01)
    hyd = {r[0]: r for r in rows_of(out, "Hydrometer analysis")}
    # columns: time, temp, R, R + k, L, K, D, P
    assert hyd[0.5][4] == pytest.approx(9.162, abs=0.002)
    assert hyd[0.5][5] == pytest.approx(0.012655, abs=0.00001)
    assert hyd[0.5][6] == pytest.approx(0.05417, abs=0.00002)
    assert hyd[0.5][7] == pytest.approx(83.90, abs=0.01)
    assert hyd[15.0][4] == pytest.approx(12.077, abs=0.01) and hyd[15.0][6] == pytest.approx(0.01135, abs=0.00002)
    assert hyd[15.0][7] == pytest.approx(48.4, abs=0.05)
    assert hyd[1440.0][4] == pytest.approx(14.78, abs=0.01) and hyd[1440.0][6] == pytest.approx(0.00128, abs=0.00001)
    assert hyd[1440.0][7] == pytest.approx(16.13, abs=0.01)
    lab = out["lab"]
    assert lab["gravel"] == 0 and lab["fines"] == pytest.approx(96.31, abs=0.05)
    assert lab["gravel"] + lab["sand"] + lab["silt"] + lab["clay"] == pytest.approx(100, abs=0.05)
    assert out["charts"][0]["x"]["log"] and out["charts"][0]["x"]["reverse"]


def test_grain_size_astm_method_and_classification():
    out = calc_lab.grain_size(ex("grain_size", ll=27.0, pi=11.2))
    hyd = {r[0]: r for r in rows_of(out, "Hydrometer analysis")}
    # ASTM D422: percent finer from R − composite (0.003) + k; depth from R + Cm (0.0005) with Table 2.
    assert hyd[0.5][2] == pytest.approx(1.029)
    assert hyd[0.5][7] == pytest.approx(2.63 / 1.63 * 2000 * 0.0269, abs=0.01)
    assert hyd[0.5][4] == pytest.approx(16.295 - 264.5 * 0.0295, abs=0.002)
    # Without Cm the typical 0.0005 is used and said so; 152H uses its own scale.
    out2 = calc_lab.grain_size(ex("grain_size", meniscus=None))
    assert {r[0]: r for r in rows_of(out2, "Hydrometer analysis")}[0.5][4] == pytest.approx(hyd[0.5][4]) and any("Meniscus" in n for n in out2["notes"])
    assert out["lab"]["uscs"] == "CL"
    # Sieve-only analysis of a sand, no fine specimen: cumulative on the whole sample.
    sand = {"m_dry_total": 1000.0, "sieves": [
        {"opening": 4.75, "retained": 20.0}, {"opening": 2.0, "retained": 180.0}, {"opening": 0.85, "retained": 300.0},
        {"opening": 0.425, "retained": 250.0}, {"opening": 0.25, "retained": 150.0}, {"opening": 0.15, "retained": 60.0},
        {"opening": 0.075, "retained": 30.0}]}
    res = calc_lab.grain_size(sand)
    assert res["lab"]["fines"] == pytest.approx(1.0) and res["lab"]["gravel"] == pytest.approx(2.0)
    assert res["lab"]["d10"] is not None and res["lab"]["cu"] == pytest.approx(res["lab"]["d60"] / res["lab"]["d10"], rel=0.01)
    assert res["lab"]["uscs"] in ("SP", "SW")
    with pytest.raises(CalcError, match="at least one sieve"):
        calc_lab.grain_size({})
    with pytest.raises(CalcError, match="Specific gravity"):
        calc_lab.grain_size(ex("grain_size", gs=None))
    with pytest.raises(CalcError, match="exceed the dry mass"):
        calc_lab.grain_size({"m_dry_total": 10.0, "sieves": [{"opening": 4.75, "retained": 20.0}]})


def test_uscs_symbols():
    u = calc_lab.uscs_symbol
    assert u(80, 15, 5, 45, 25) == "CL"
    assert u(80, 15, 5, 60, 35) == "CH"
    assert u(80, 15, 5, 40, 5) == "ML"  # below the A-line
    assert u(80, 15, 5, 60, 10) == "MH"
    assert u(80, 15, 5, 22, 5) == "CL-ML"
    assert u(80, 15, 5, None, 0) == "ML"  # non-plastic
    assert u(80, 15, 5, None, None) == ""
    assert u(3, 90, 7, None, None, cu=8, cc=1.5) == "SW"
    assert u(3, 90, 7, None, None, cu=3, cc=1.0) == "SP"
    assert u(3, 30, 67, None, None, cu=5, cc=2) == "GW"
    assert u(20, 70, 10, 30, 3) == "SM"
    assert u(20, 70, 10, 35, 15) == "SC"
    assert u(20, 70, 10, 22, 5) == "SC-SM"
    assert u(8, 80, 12, 30, 2, cu=3, cc=1) == "SP-SM"
    assert u(8, 80, 12, 35, 15, cu=7, cc=2) == "SW-SC"
    assert u(30, 20, 50, 40, 20) == "GC"
    assert calc_lab.plasticity_symbol(27.0, 11.2) == "CL"


# --------------------------------------------------------------------------- #
# 05.07 Atterberg limits
# --------------------------------------------------------------------------- #

def test_atterberg_limits():
    out = calc_lab.atterberg(ex("atterberg"))
    assert out["lab"] == {"ll": pytest.approx(27.00, abs=0.01), "pl": pytest.approx(15.80, abs=0.01), "pi": pytest.approx(11.20, abs=0.01)}
    ws = [r[3] for r in rows_of(out, "Trials") if r[0] == "LL"]
    assert ws == [pytest.approx(v, abs=0.01) for v in (29.20, 27.55, 26.34, 26.01)]
    assert val(out, "Flow index") == pytest.approx(4.44, abs=0.01)
    assert val(out, "Plasticity chart") == "CL"
    assert val(out, "A-line PI at this LL") == pytest.approx(0.73 * 7, abs=0.02)
    assert val(out, "Plasticity") == "Medium plasticity"
    assert val(out, "Liquidity index LI") == pytest.approx((28.6 - 15.8) / 11.2, abs=0.01)
    assert [c["title"] for c in out["charts"]] == ["Flow curve", "Plasticity chart"] and out["charts"][0]["x"]["log"]
    np_ = calc_lab.atterberg(ex("atterberg", pl_trials=[], non_plastic=True))
    assert np_["lab"] == {"ll": pytest.approx(27.0, abs=0.01), "pi": 0.0} and val(np_, "Plastic limit PL") == "NP"
    one = calc_lab.atterberg({"ll_trials": [{"blows": 25.0, "m_wet": 30.0, "m_dry": 25.0, "m_tare": 5.0}]})
    assert one["lab"]["ll"] == pytest.approx(25.0)
    with pytest.raises(CalcError, match="liquid limit trial"):
        calc_lab.atterberg({"ll_trials": []})


# --------------------------------------------------------------------------- #
# 05.08 Compaction
# --------------------------------------------------------------------------- #

def test_proctor_compaction():
    out = calc_lab.compaction(ex("compaction"))
    pts = rows_of(out, "Compaction points")
    assert [r[1] for r in pts] == [pytest.approx(v, abs=0.01) for v in (10.45, 13.13, 15.73, 18.32, 20.69)]
    assert [r[3] for r in pts] == [pytest.approx(v, abs=0.001) for v in (1.6889, 1.7707, 1.7951, 1.7262, 1.6053)]
    assert [r[4] for r in pts] == [pytest.approx(v, abs=0.001) for v in (2.0632, 1.9549, 1.8605, 1.7750, 1.7033)]
    assert out["lab"]["omc"] == pytest.approx(14.99, abs=0.02)
    assert out["lab"]["mdd"] == pytest.approx(1.792, abs=0.001)
    assert val(out, "95 % of MDD") == pytest.approx(0.95 * 1.792, abs=0.002)
    para = calc_lab.compaction(ex("compaction", curve_fit="parabola"))
    assert para["lab"]["omc"] == pytest.approx(15.0, abs=0.6) and para["lab"]["mdd"] == pytest.approx(1.795, abs=0.01)
    manual = calc_lab.compaction(ex("compaction", mdd_manual=1.797, omc_manual=14.89))
    assert manual["lab"] == {"mdd": 1.797, "omc": 14.89}
    with pytest.raises(CalcError, match="three compaction points"):
        calc_lab.compaction(ex("compaction", points=ex("compaction")["points"][:2]))
    with pytest.raises(CalcError, match="Mold volume"):
        calc_lab.compaction(ex("compaction", mold_volume=None))


# --------------------------------------------------------------------------- #
# 05.09 CBR
# --------------------------------------------------------------------------- #

def test_cbr_specimens_rules_swell_and_design_value():
    out = calc_lab.cbr_lab(ex("cbr_lab"))
    spec = rows_of(out, "Specimens")
    assert [r[3] for r in spec] == [pytest.approx(v, abs=0.001) for v in (1.4263, 1.6267, 1.7325)]
    assert [r[2] for r in spec] == [pytest.approx(v, abs=0.01) for v in (22.42, 21.64, 19.44)]
    assert [r[4] for r in spec] == [pytest.approx(v, abs=0.01) for v in (0.68, 3.50, 8.22)]
    assert [r[5] for r in spec] == [pytest.approx(v, abs=0.01) for v in (0.60, 3.37, 10.14)]
    # ASTM rule: 2.54 mm value unless the 5.08 mm value is higher.
    assert [r[6] for r in spec] == [pytest.approx(v, abs=0.01) for v in (0.68, 3.50, 10.14)]
    assert [r[7] for r in spec] == [pytest.approx(v, abs=0.01) for v in (4.0, 6.02, 1.4)]
    assert all(r[8] == 0 for r in spec)  # no concave-up start in these curves
    comp = rows_of(out, "Compaction points")
    assert [r[1] for r in comp] == [pytest.approx(v, abs=0.01) for v in (11.97, 14.46, 16.99, 19.47, 22.07)]
    assert out["lab"]["omc"] == pytest.approx(16.56, abs=0.02) and out["lab"]["mdd"] == pytest.approx(1.776, abs=0.001)
    target = 0.95 * 1.776
    assert val(out, "Target dry density") == pytest.approx(target, abs=0.002)
    design = 3.50 + (10.14 - 3.50) * (target - 1.6267) / (1.7325 - 1.6267)
    assert out["lab"]["cbr"] == pytest.approx(design, abs=0.15)
    assert out["lab"]["condition"] == "soaked"
    avg = calc_lab.cbr_lab(ex("cbr_lab", cbr_rule="average"))
    assert [r[6] for r in rows_of(avg, "Specimens")] == [pytest.approx(v, abs=0.01) for v in (0.64, 3.44, 9.18)]
    low = calc_lab.cbr_lab(ex("cbr_lab", cbr_rule="min"))
    assert [r[6] for r in rows_of(low, "Specimens")] == [pytest.approx(v, abs=0.01) for v in (0.60, 3.37, 8.22)]
    # The same ring factor in newtons gives the same CBR.
    si = calc_lab.cbr_lab(ex("cbr_lab", ring_factor=3.38 * 4.4482216 / 1000, ring_unit="kN"))
    assert [r[4] for r in rows_of(si, "Specimens")] == [r[4] for r in spec]
    titles = [c["title"] for c in out["charts"]]
    assert titles[:3] == ["Load–penetration curves", "CBR versus dry density", "Swell during soaking"]


def test_cbr_origin_correction_and_errors():
    concave = [{"pen": p, "load_1": d} for p, d in [(0.0, 0.0), (0.025, 2.0), (0.05, 10.0), (0.075, 22.0), (0.1, 32.0),
                                                   (0.15, 48.0), (0.2, 60.0), (0.3, 75.0)]]
    out = calc_lab.cbr_lab({"penetration": concave, "ring_factor": 3.38})
    shift = rows_of(out, "Specimens")[0][8]
    assert shift == pytest.approx((0.05 - 10.0 / ((22.0 - 10.0) / 0.025)) * 25.4, abs=0.01)
    manual = calc_lab.cbr_lab({"penetration": concave, "ring_factor": 3.38, "specimens": [{"zero_corr": 0.0}]})
    assert rows_of(manual, "Specimens")[0][8] == 0
    assert rows_of(out, "Specimens")[0][4] > rows_of(manual, "Specimens")[0][4]
    with pytest.raises(CalcError, match="penetration readings"):
        calc_lab.cbr_lab({"ring_factor": 3.38})
    with pytest.raises(CalcError, match="reach 2.54 mm"):
        calc_lab.cbr_lab({"penetration": concave[:3], "ring_factor": 3.38})
    with pytest.raises(CalcError, match="ring factor must be greater"):
        calc_lab.cbr_lab({"penetration": concave, "ring_factor": 0.0})


# --------------------------------------------------------------------------- #
# 05.10 UCS
# --------------------------------------------------------------------------- #

def test_unconfined_compression():
    out = calc_lab.ucs(ex("ucs"))
    assert val(out, "Initial area A0") == pytest.approx(19.635, abs=0.001)
    assert out["lab"]["qu"] == pytest.approx(1.084 * KGCM2, abs=0.1)
    assert val(out, "qu") == pytest.approx(1.084, abs=0.001)
    assert out["lab"]["strain"] == pytest.approx(3.5)
    assert val(out, "Remolded strength qu,r") == pytest.approx(0.630 * KGCM2, abs=0.1)
    assert out["lab"]["st"] == pytest.approx(1.72, abs=0.01)
    assert out["lab"]["su"] == pytest.approx(0.542 * KGCM2, abs=0.1)
    assert val(out, "Water content w") == pytest.approx(90.20, abs=0.01)
    assert val(out, "Bulk density ρ") == pytest.approx(1.477, abs=0.001)
    assert val(out, "Dry density ρd") == pytest.approx(0.777, abs=0.001)
    assert val(out, "Consistency") == "Stiff"
    # Deformation entered as 0.01 mm dial divisions gives the same result.
    readings = [dict(r, deformation=r["deformation"] * 100) for r in ex("ucs")["readings"]]
    assert calc_lab.ucs(ex("ucs", readings=readings, axial_unit="0.01mm"))["lab"] == out["lab"]
    with pytest.raises(CalcError, match="Diameter is required"):
        calc_lab.ucs(ex("ucs", diameter=None))
    with pytest.raises(CalcError, match="undisturbed specimen"):
        calc_lab.ucs(ex("ucs", readings=[{"deformation": 0.2, "dial_remolded": 3.0}]))


# --------------------------------------------------------------------------- #
# 05.11 / 05.12 Triaxial
# --------------------------------------------------------------------------- #

def test_uu_triaxial():
    out = calc_lab.triaxial(ex("triaxial"))
    spec = rows_of(out, "Specimens")
    assert [r[2] / KGCM2 for r in spec] == [pytest.approx(v, abs=0.002) for v in (2.364, 2.808, 3.417)]
    assert [r[3] for r in spec] == [pytest.approx(v) for v in (11.0, 11.0, 10.0)]
    assert [r[6] for r in spec] == [pytest.approx(v, abs=0.01) for v in (48.00, 48.68, 51.55)]
    assert [r[7] for r in spec] == [pytest.approx(v, abs=0.001) for v in (1.700, 1.701, 1.707)]
    assert out["lab"]["test"] == "UU"
    assert out["lab"]["c"] / KGCM2 == pytest.approx(0.860, abs=0.002)
    assert out["lab"]["phi"] == pytest.approx(10.2, abs=0.05)
    assert out["lab"]["cu"] / KGCM2 == pytest.approx(1.431, abs=0.002)
    mohr = next(c for c in out["charts"] if c["title"] == "Mohr circles")
    assert len(mohr["series"]) == 4 and mohr["series"][-1]["name"] == "Failure envelope"
    in_kpa = ex("triaxial", stress_unit="kpa")
    for s in in_kpa["specimens"]:
        s["cell_pressure"] *= KGCM2
    assert calc_lab.triaxial(in_kpa)["lab"] == out["lab"]
    with pytest.raises(CalcError, match="Cell pressure is required"):
        calc_lab.triaxial(ex("triaxial", specimens=[{"height": 10.0, "diameter": 5.0}]))


def test_cu_triaxial_needs_the_ring_factor_and_gives_total_and_effective_strength():
    with pytest.raises(CalcError, match="Proving ring factor is required"):
        calc_lab.triaxial_cu(ex("triaxial_cu"))
    out = calc_lab.triaxial_cu(ex("triaxial_cu", ring_factor=0.35))
    fail = rows_of(out, "Failure")
    # Specimen 2 by hand: consolidated length and area, peak load 111 divisions.
    ev = 14.0 / (math.pi * 25 / 4 * 10)
    lc, ac = 100 * (1 - ev / 3), math.pi * 25 / 4 * (1 - 2 * ev / 3)
    candidates = [111 * 0.35 * 9.80665 / (ac / (1 - a / 100 / lc)) * 10 for a in range(950, 1501, 50)]
    assert fail[1][4] == pytest.approx(max(candidates), abs=0.2)
    assert fail[1][5] == pytest.approx((2.9 - 2.74) * KGCM2, abs=0.2)  # σ3' = cell − u
    lab = out["lab"]
    assert set(lab) == {"c", "phi", "c_eff", "phi_eff"}
    assert 0 <= lab["phi"] < lab["phi_eff"] < 60 and lab["c"] >= 0 and lab["c_eff"] >= 0
    ratio = calc_lab.triaxial_cu(ex("triaxial_cu", ring_factor=0.35, failure="max_ratio"))
    assert set(ratio["lab"]) == set(lab)
    with pytest.raises(CalcError, match="pore pressure readings"):
        rows = [{k: v for k, v in r.items() if not k.startswith("u_")} for r in ex("triaxial_cu")["readings"]]
        calc_lab.triaxial_cu(ex("triaxial_cu", ring_factor=0.35, readings=rows))


def test_strength_fit_edge_cases():
    fit = calc_lab.strength_fit([(100.0, 60.0), (200.0, 110.0), (300.0, 160.0)])
    assert fit["phi"] == pytest.approx(math.degrees(math.asin(0.5))) and fit["c"] == pytest.approx(10 / math.cos(math.radians(30)))
    flat = calc_lab.strength_fit([(100.0, 60.0), (200.0, 55.0)])
    assert flat["phi"] == 0 and flat["c"] == pytest.approx(57.5)
    origin = calc_lab.strength_fit([(100.0, 40.0), (200.0, 90.0)])
    assert origin["c"] == 0 and origin["case"] == "origin"
    with pytest.raises(CalcError, match="valid strength envelope"):
        calc_lab.strength_fit([(100.0, 10.0), (110.0, 30.0)])


# --------------------------------------------------------------------------- #
# 05.13 Direct shear
# --------------------------------------------------------------------------- #

def test_direct_shear_standard_and_template_conversion():
    out = calc_lab.direct_shear(ex("direct_shear"))
    spec = rows_of(out, "Specimens")
    assert [r[2] for r in spec] == [pytest.approx(v, abs=0.01) for v in (36.22, 52.87)]
    assert [r[3] for r in spec] == [4.8, 5.7]  # first reading at the peak
    assert [r[5] for r in spec] == [pytest.approx(v, abs=0.01) for v in (51.30, 52.64)]
    assert [r[6] for r in spec] == [pytest.approx(v, abs=0.001) for v in (1.682, 1.722)]
    assert out["lab"]["c"] == pytest.approx(19.56, abs=0.06)
    assert out["lab"]["phi"] == pytest.approx(18.76, abs=0.06)
    tpl = calc_lab.direct_shear(ex("direct_shear", conversion="template"))
    assert [r[2] for r in rows_of(tpl, "Specimens")] == [pytest.approx(v, abs=0.01) for v in (37.67, 54.99)]
    assert [r[1] for r in rows_of(tpl, "Specimens")] == [pytest.approx(49.05, abs=0.06), pytest.approx(98.1)]
    assert any("Template conversion" in n for n in tpl["notes"])
    with pytest.raises(CalcError, match="different normal stresses"):
        calc_lab.direct_shear(ex("direct_shear", specimens=ex("direct_shear")["specimens"][:1]))
    with pytest.raises(CalcError, match="Normal stress is required"):
        calc_lab.direct_shear(ex("direct_shear", specimens=[{"area": 28.27}, {"area": 28.27}]))


# --------------------------------------------------------------------------- #
# 05.14 Consolidation
# --------------------------------------------------------------------------- #

def test_consolidation():
    out = calc_lab.consolidation(ex("consolidation"))
    assert val(out, "Height of solids Hs") == pytest.approx(7.3462, abs=0.0002)
    assert out["lab"]["e0"] == pytest.approx(1.6966, abs=0.0002)
    inc = rows_of(out, "Load increments")
    assert [r[3] for r in inc[:8]] == [pytest.approx(v, abs=0.0006) for v in
                                       (1.6927, 1.6780, 1.6384, 1.5609, 1.4507, 1.3132, 1.1659, 1.0106)]  # table: 4 digits
    assert [r[3] for r in inc[8:]] == [pytest.approx(v, abs=0.0006) for v in (1.0771, 1.1487, 1.2218, 1.2491)]
    assert [r[4] for r in inc[:8]] == [pytest.approx(v, abs=0.0002) for v in
                                       (0.98977, 0.98635, 0.97637, 0.95487, 0.9204, 0.8749, 0.8226, 0.76702)]
    assert out["lab"]["cc"] == pytest.approx(0.516, abs=0.001)
    assert out["lab"]["cr"] == pytest.approx(0.120, abs=0.001)
    assert out["lab"]["pc"] / KGCM2 == pytest.approx(0.44, abs=0.02)
    assert val(out, "Initial water content w0") == pytest.approx(64.18, abs=0.01)
    assert val(out, "Final water content wf") == pytest.approx(65.76, abs=0.01)
    assert val(out, "Initial bulk density ρ0") == pytest.approx(1.632, abs=0.001)
    assert val(out, "Initial dry density ρd0") == pytest.approx(0.994, abs=0.001)
    # cv for the summary: first increment above σ'p (0.8 kg/cm², entered cv), in m²/year.
    assert out["lab"]["cv"] == pytest.approx(0.0003742 * 3153.6, rel=0.01)
    with_ocr = calc_lab.consolidation(ex("consolidation", sigma_v0=0.2))
    assert val(with_ocr, "Overconsolidation ratio OCR") == pytest.approx(out["lab"]["pc"] / (0.2 * KGCM2), abs=0.02)
    manual = calc_lab.consolidation(ex("consolidation", pc_manual=0.5))
    assert manual["lab"]["pc"] == pytest.approx(0.5 * KGCM2, abs=0.1)
    # Without an entered cv the time readings give it (Taylor, double drainage).
    incs = [dict(r, cv=None) for r in ex("consolidation")["increments"]]
    timed = calc_lab.consolidation(ex("consolidation", increments=incs))
    row = next(r for r in rows_of(timed, "Load increments") if r[0] == pytest.approx(0.8 * KGCM2, abs=0.1))
    assert row[7] == pytest.approx(23.4, abs=0.2)
    assert row[8] == pytest.approx(0.848 * 0.9204 ** 2 / (23.37 * 60), rel=0.02)
    with pytest.raises(CalcError, match="Specific gravity Gs is required"):
        calc_lab.consolidation(ex("consolidation", gs=None))
    with pytest.raises(CalcError, match="load increments"):
        calc_lab.consolidation(ex("consolidation", increments=[]))


def test_time_curve_fitting():
    t = [0, 0.1, 0.1667, 0.25, 0.5, 1, 2.25, 4, 6.25, 9, 12.25, 16, 20.25, 25, 36, 64, 100, 196, 400]
    d = [1.163, 1.216, 1.223, 1.23, 1.245, 1.265, 1.296, 1.343, 1.383, 1.418, 1.45, 1.475, 1.498, 1.518, 1.549, 1.597,
         1.634, 1.69, 1.737]
    tay = calc_lab.taylor_t90(t, d)
    assert tay is not None and tay["t90"] == pytest.approx(23.4, abs=0.2) and tay["d0"] == pytest.approx(1.1875, abs=0.001)
    cas = calc_lab.casagrande_t50(t, d)
    assert cas is not None and cas["t50"] == pytest.approx(7.5, abs=0.1)
    # Settlement read as a decreasing dial gives the same times.
    flipped = [10 - x for x in d]
    assert calc_lab.taylor_t90(t, flipped)["t90"] == pytest.approx(tay["t90"])  # type: ignore[index]
    assert calc_lab.casagrande_t50(t, flipped)["t50"] == pytest.approx(cas["t50"])  # type: ignore[index]
    assert calc_lab.taylor_t90([1, 2], [1.0, 1.1]) is None


# --------------------------------------------------------------------------- #
# 05.15 Swelling
# --------------------------------------------------------------------------- #

def test_swelling():
    out = calc_lab.swelling(ex("swelling"))
    assert val(out, "Height of solids Hs") == pytest.approx(11.8123, abs=0.0002)
    assert val(out, "Height before wetting h1") == pytest.approx(20.076, abs=0.001)
    assert val(out, "Height after wetting h2") == pytest.approx(20.332, abs=0.001)
    assert out["lab"]["swell"] == pytest.approx(1.275, abs=0.002)
    assert out["lab"]["swell_pressure"] == pytest.approx(73.6, abs=0.3)
    steps = rows_of(out, "Load steps")
    assert [r[5] for r in steps] == [pytest.approx(v, abs=0.0002) for v in
                                     (0.7016, 0.7008, 0.6996, 0.7213, 0.7196, 0.7125, 0.6978, 0.6743)]
    assert steps[2][4] == pytest.approx(0.024 / 20.1 * 100, abs=0.001)  # strain over H0, not 20 mm
    assert val(out, "Initial water content") == pytest.approx(30.60, abs=0.01)
    assert val(out, "Final water content") == pytest.approx(31.04, abs=0.01)
    assert val(out, "Initial bulk density") == pytest.approx(1.911, abs=0.001)
    assert val(out, "Final bulk density") == pytest.approx(1.949, abs=0.001)
    assert [c["title"] for c in out["charts"]] == ["Void ratio versus stress", "Swell versus time"]
    steps_no_phase = [dict(s, phase="load") for s in ex("swelling")["steps"]]
    with pytest.raises(CalcError, match="before wetting"):
        calc_lab.swelling(ex("swelling", steps=steps_no_phase))


# --------------------------------------------------------------------------- #
# 05.16 – 05.18 Aggregate and rock
# --------------------------------------------------------------------------- #

def test_los_angeles_abrasion():
    out = calc_lab.la_abrasion(ex("la_abrasion"))
    assert rows_of(out, "Trials")[0][1] == pytest.approx(5073)
    assert out["lab"]["loss"] == pytest.approx(29.15, abs=0.01)
    assert "The total mass differs from the mass required by the grading." in out["notes"]
    two = ex("la_abrasion", retained_2=3700.0)
    for f in two["fractions"]:
        f["mass_2"] = 1250.0
    assert calc_lab.la_abrasion(two)["lab"]["loss"] == pytest.approx((29.154 + 26.0) / 2, abs=0.01)
    assert "The size fractions do not match the chosen grading." in calc_lab.la_abrasion(ex("la_abrasion", grading="B"))["notes"]
    with pytest.raises(CalcError, match="No. 12"):
        calc_lab.la_abrasion(ex("la_abrasion", retained_1=None))


def test_sulfate_soundness():
    assert calc_lab.soundness(ex("soundness"))["lab"]["loss"] == pytest.approx(20.44, abs=0.01)
    coarse = {"aggregate": "coarse", "fractions": [{"grading": g, "mass_before": b, "mass_after": a} for g, b, a in [
        (36.39, 1046.0, 1027.13), (18.12, 521.0, 481.09), (23.36, 671.5, 514.85), (11.58, 333.0, 193.96), (10.54, 303.0, 214.9)]]}
    assert calc_lab.soundness(coarse)["lab"]["loss"] == pytest.approx(15.39, abs=0.01)
    # A fraction that was not tested takes the average loss of its neighbours.
    gap = {"fractions": [{"grading": 50.0, "mass_before": 100.0, "mass_after": 90.0}, {"grading": 4.0},
                         {"grading": 46.0, "mass_before": 100.0, "mass_after": 70.0}]}
    assert calc_lab.soundness(gap)["lab"]["loss"] == pytest.approx(5.0 + 0.8 + 13.8)
    with pytest.raises(CalcError, match="must not exceed"):
        calc_lab.soundness({"fractions": [{"grading": 50.0, "mass_before": 100.0, "mass_after": 120.0}]})


def test_slake_durability():
    out = calc_lab.slake_durability(ex("slake_durability"))
    assert out["lab"]["w"] == pytest.approx(15.96, abs=0.01)
    assert val(out, "Slake durability index Id3") == pytest.approx(68.70, abs=0.01)
    assert "id2" not in out["lab"]
    two = calc_lab.slake_durability(ex("slake_durability", cycles=[{"cycle": 1.0, "m_after": 2740.0}, {"cycle": 2.0, "m_after": 2725.0}]))
    assert two["lab"]["id2"] == pytest.approx((2725.0 - 2517.08) / 239.34 * 100, abs=0.01)
    assert val(two, "Durability (Gamble)") == "Medium high"
    with pytest.raises(CalcError, match="Drum mass is required"):
        calc_lab.slake_durability(ex("slake_durability", m_drum=None))


# --------------------------------------------------------------------------- #
# Through the API: saving a lab test calculates it and fills in its results
# --------------------------------------------------------------------------- #

def _lab(client, headers, test_type, raw, **extra):
    body = {"borehole_id": "BH-1", "sample_ref": "UDS-1", "depth_top": 2, "test_type": test_type, "status": "done", "raw": raw, **extra}
    return client.post("/api/records/lab_tests", json=body, headers=headers)


def test_saving_a_lab_test_calculates_its_results(client, admin_headers):
    res = _lab(client, admin_headers, "atterberg", EXAMPLES["atterberg"], results={"ll": 99})
    assert res.status_code == 201, res.text
    rec = res.json()
    assert "LL = 27" in rec["calc"]["summary"] and rec["summary"] == rec["calc"]["summary"]
    assert rec["results"]["ll"] == pytest.approx(27.0) and rec["results"]["pl"] == pytest.approx(15.8)
    assert rec["results"]["pi"] == pytest.approx(11.2)
    # Saved again unchanged: still valid.
    again = client.put(f"/api/records/lab_tests/{rec['id']}", json=dict(rec, expected_updated_at=rec["updated_at"]), headers=admin_headers)
    assert again.status_code == 200, again.text
    moist = _lab(client, admin_headers, "moisture", EXAMPLES["moisture"]).json()
    assert moist["results"]["w"] == pytest.approx(37.66) and moist["results"]["gamma_bulk"] == pytest.approx(17.58, abs=0.01)
    grain = _lab(client, admin_headers, "grain_size", dict(EXAMPLES["grain_size"], ll=27, pi=11.2)).json()
    assert grain["results"]["fines"] == pytest.approx(96.31, abs=0.05) and grain["calc"]["charts"]
    # A half-filled worksheet is stored with the error instead of being refused.
    half = _lab(client, admin_headers, "direct_shear", {"specimens": [{"normal_stress": 0.5}], "readings": [{"displacement": 1, "dial_1": 10}]})
    assert half.status_code == 201 and half.json()["calc"]["error"]
    # Invalid raw input is refused by the field rules.
    assert _lab(client, admin_headers, "moisture", {"specimens": [{"m_wet": "abc"}]}).status_code == 422


def test_worksheet_preview_endpoint(client, admin_headers):
    res = client.post("/api/worksheets/calc", json={"kind": "lab", "key": "ucs", "data": EXAMPLES["ucs"]}, headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json()["lab"]["qu"] == pytest.approx(106.3, abs=0.1)
    bad = client.post("/api/worksheets/calc", json={"kind": "lab", "key": "ucs", "data": {"height": 10}}, headers=admin_headers)
    assert bad.status_code == 422 and bad.json()["detail"] == "Diameter is required"
