"""Field worksheets: calculations checked against the template examples and hand calculations."""
import math

import pytest

from backend.app import calc_field as cf
from backend.app import records, sheets
from backend.app.calcbase import CalcError
from backend.app.entities import ENTITIES


def close(a, b, rel=1e-3, abs_=1e-9):
    return a is not None and abs(a - b) <= max(abs_, rel * abs(b))


def val(out, label, unit=None):
    for v in out["values"]:
        if v["label"] == label and (unit is None or v["unit"] == unit):
            return v["value"]
    raise KeyError(label)


def rows_of(out, title):
    tb = next(t for t in out["tables"] if t["title"] == title)
    return [dict(zip(tb["columns"], r)) for r in tb["rows"]]


def example(key):
    sheet = sheets.get("field", key)
    assert sheet is not None and sheet.example, key
    data_field = ENTITIES["field_activities"].field("data")
    return records._clean_value(data_field, sheet.example, "Worksheet", {"method": key}, lambda *_: True)


# --------------------------------------------------------------------------- #
# Catalogue
# --------------------------------------------------------------------------- #

def test_catalogue_and_examples_validate_and_calculate():
    keys = {s.key for s in sheets.all_sheets("field")}
    assert {"coordinates", "work_instruction", "daily_report", "hse_report", "gps_point", "gps_logsheet", "topographic",
            "traverse", "levelling", "benchmark", "pocket_penetrometer", "spt_corrected", "fvst", "perm_falling",
            "perm_constant", "perm_rising", "lugeon", "test_pit", "cbr_field", "plt", "resistivity_1d", "resistivity_2d",
            "downhole", "crosshole", "thermal_resistivity"} <= keys
    pages = {s.key: s for s in sheets.all_sheets("page")}
    assert pages["boreholes_page"].link == "boreholes" and pages["cpt_page"].link == "cpt" and pages["cptu_page"].code == "03.05"
    groups = {g for g, _, _ in sheets.FIELD_GROUPS}
    methods = {o[0] for o in ENTITIES["field_activities"].field("method").options}
    for s in sheets.all_sheets("field"):
        assert s.group in groups and s.calc is not None and s.help and s.key in methods
        if s.example:
            out = sheets.calculate("field", s.key, example(s.key))
            assert out and out["summary"], s.key
    assert "name removed" not in repr(sheets.catalog())  # examples carry no personal names


# --------------------------------------------------------------------------- #
# General
# --------------------------------------------------------------------------- #

def test_coordinate_table_total_depth_and_conversion():
    out = cf.coordinates(example("coordinates"))
    assert val(out, "Total planned depth") == 470 and val(out, "Points") == 10
    # Template converter example: 48S 716358.179 / 9322876.989 -> -6.122348019, 106.9550619
    out = cf.coordinates({"zone": 48, "hemisphere": "S", "points": [{"point": "BH-01", "easting": 716358.179, "northing": 9322876.989},
                                                                   {"point": "LL", "latitude": -6.122348019, "longitude": 106.9550619}]})
    r = rows_of(out, "Coordinates")
    assert close(float(r[0]["Latitude (°)"]), -6.122348019, abs_=2e-7) and close(float(r[0]["Longitude (°)"]), 106.9550619, abs_=2e-7)
    assert abs(float(r[1]["Easting (m)"]) - 716358.179) < 0.05 and abs(float(r[1]["Northing (m)"]) - 9322876.989) < 0.05
    with pytest.raises(CalcError):  # seven-digit easting typo from the template
        cf.coordinates({"zone": 48, "points": [{"point": "X", "easting": 7162417.326, "northing": 9322876.0}]})
    with pytest.raises(CalcError):
        cf.coordinates({"points": [{"point": "X", "easting": 716358.0, "northing": 9322876.0}]})


def test_work_instruction_totals():
    out = cf.work_instruction(example("work_instruction"))
    assert val(out, "Points") == 13 and val(out, "Total planned depth") == 380


def test_daily_report_progress():
    data = {"drilling": [{"borehole": "DB-1", "plan_depth": 50, "prev_depth": 43, "today_depth": 7.45, "prev_spt": 21, "today_spt": 4},
                         {"borehole": "DB-2", "plan_depth": 50, "prev_depth": 44.45, "today_depth": 5.67, "prev_spt": 22, "today_spt": 3}]}
    r = rows_of(cf.daily_report(data), "Drilling progress")
    assert close(r[0]["Cumulative depth (m)"], 50.45) and close(r[0]["Progress (%)"], 100.9) and r[0]["SPT cumulative"] == 25
    assert close(r[1]["Progress (%)"], 100.24) and r[2]["Borehole"] == "Total" and close(r[2]["Today (m)"], 13.12)
    out = cf.daily_report(example("daily_report"))
    assert val(out, "Manpower") == 8
    progress = [x["Progress (%)"] for x in rows_of(out, "Work summary")]
    assert progress == pytest.approx([80, 50, 100, 100, 0, 0, 100, 100, 6.25])


def test_hse_rates_without_double_count():
    out = cf.hse_report(example("hse_report"))
    assert val(out, "Man-hours today") == 70 and val(out, "Project man-hours") == 2640 and val(out, "LTIFR") == 0
    data = {"manhours": [{"position": "Driller", "nw_manpower": 4, "nw_hours": 10, "ot_manpower": 2, "ot_hours": 2}],
            "previous_manhours": 99956,
            "lagging": [{"item": "lwdc", "today": 0, "previous": 1}, {"item": "mtc", "today": 1, "previous": 0},
                        {"item": "near_miss", "today": 3, "previous": 4}]}
    out = cf.hse_report(data)
    assert val(out, "Man-hours today") == 44 and val(out, "Project man-hours") == 100000
    assert val(out, "Lost time injuries (LTI)") == 1 and val(out, "Recordable cases") == 2
    assert close(val(out, "LTIFR"), 2.0) and close(val(out, "TRIR"), 4.0)
    assert close(val(cf.hse_report(dict(data, trir_basis="template")), "TRIR"), 6.0)
    assert close(val(cf.hse_report(dict(data, rate_base="1000000")), "LTIFR"), 10.0)
    zero = cf.hse_report({"lagging": [{"item": "fatality", "today": 1}], "manhours": [{"position": "x", "nw_manpower": 0, "nw_hours": 8}]})
    assert val(zero, "LTIFR") is None


# --------------------------------------------------------------------------- #
# Survey
# --------------------------------------------------------------------------- #

def test_gps_point_and_logsheet():
    out = cf.gps_point(example("gps_point"))
    assert close(val(out, "Latitude"), -6.13409708, abs_=1e-7) and close(val(out, "Longitude"), 106.89360378, abs_=1e-7)
    assert cf.parse_angle("6 8 2.74947 LS", "N", "S") == pytest.approx(-6.13409708, abs=1e-7)
    out = cf.gps_logsheet(example("gps_logsheet"))
    assert val(out, "Session duration") == 9 and val(out, "Day of year (UTC)") == 293
    assert val(out, "Start (UTC)") == "2025-10-20 01:00" and val(out, "Antenna height difference") == 0
    with pytest.raises(CalcError):
        cf.gps_logsheet({"start_date": "2025-10-20", "start_time": "25:00"})


def test_topographic_and_benchmark():
    out = cf.topographic({"points": [{"point": "1", "easting": 100, "northing": 200, "elevation": 10.5, "code": "TREE"},
                                     {"point": "2", "easting": 150, "northing": 260, "elevation": 12.25, "code": "ROAD"},
                                     {"point": "3", "easting": 120, "northing": 230, "elevation": 9.75, "code": "ROAD"}]})
    assert val(out, "Points") == 3 and val(out, "Easting range") == 50 and val(out, "Lowest elevation") == 9.75
    assert rows_of(out, "Points per feature code")[0] == {"Code": "ROAD", "Points": 2}
    r = rows_of(cf.benchmark(example("benchmark")), "Between benchmarks")
    assert r[0]["From"] == "BM.01" and float(r[0]["Horizontal distance (m)"]) == pytest.approx(math.hypot(1.774, 190.297), abs=1e-3)
    assert float(r[1]["Height difference (m)"]) == pytest.approx(1.541, abs=1e-6)


SQUARE = [{"station": "B", "angle_d": 270, "distance": 100}, {"station": "P1", "angle_d": 270, "distance": 100},
          {"station": "P2", "angle_d": 270, "distance": 100}, {"station": "P3", "angle_d": 270, "distance": 100},
          {"station": "B", "angle_d": 0}]


def _loop(stations, **kw):
    return cf.traverse({"traverse_type": "closed", "start_ref_e": 1000, "start_ref_n": 800, "start_e": 1000, "start_n": 1000,
                        "stations": stations, **kw})


def test_traverse_closed_loop_hand_checked():
    exact = _loop(SQUARE)
    assert val(exact, "Angular misclosure") == 0 and val(exact, "Linear misclosure") == 0
    # 10″ angle error: misclosure 10″ spread as −2″ on each of the five angles; tolerance 10√5.
    st = [dict(s) for s in SQUARE]
    st[1]["angle_s"] = 10
    out = _loop(st)
    assert val(out, "Angular misclosure") == 10 and close(val(out, "Angular tolerance"), 10 * math.sqrt(5), rel=3e-3)
    assert all(r["Angle correction (″)"] == -2 for r in rows_of(out, "Adjusted traverse"))
    # Leg P2-P3 measured 2 cm too long: fE = −0.02, fN = 0, precision 400.02 / 0.02.
    st = [dict(s) for s in SQUARE]
    st[2]["distance"] = 100.02
    out = _loop(st)
    assert close(val(out, "Misclosure in easting fE"), -0.02, abs_=1e-6) and abs(val(out, "Misclosure in northing fN")) < 1e-6
    assert val(out, "Linear misclosure") == pytest.approx(0.02, abs=1e-6) and val(out, "Precision (1 : X)") == 20001
    last = rows_of(out, "Adjusted traverse")[-1]
    assert float(last["Easting (m)"]) == pytest.approx(1000, abs=1e-3) and float(last["Northing (m)"]) == pytest.approx(1000, abs=1e-3)
    # Bowditch: each leg gets fE × d / Σd back.
    assert float(rows_of(out, "Adjusted traverse")[0]["Correction E (m)"]) == pytest.approx(0.02 * 100 / 400.02, abs=1e-4)
    # Counter-clockwise angles of the same loop.
    left = [dict(s, angle_d=90 if s["angle_d"] == 270 else 0) for s in SQUARE]
    assert val(_loop(left, angle_direction="left"), "Angular misclosure") == 0


def test_traverse_link_and_errors():
    # A(0,-100) -> B(0,0) -> P(0,100) -> C(0,200) -> D(0,300): straight line, all angles 180°.
    data = {"start_ref_e": 0, "start_ref_n": -100, "start_e": 0, "start_n": 0, "end_e": 0, "end_n": 200,
            "end_ref_e": 0, "end_ref_n": 300,
            "stations": [{"station": "B", "angle_d": 180, "distance": 100}, {"station": "P", "angle_d": 180, "distance": 100.01},
                         {"station": "C", "angle_d": 179, "angle_m": 59, "angle_s": 50}]}
    out = cf.traverse(data)
    assert val(out, "Angular misclosure") == -10 and close(val(out, "Misclosure in northing fN"), 0.01, abs_=1e-6)
    assert val(out, "Angular check") == "Within tolerance"
    with pytest.raises(CalcError):
        cf.traverse({"start_e": 0, "start_n": 0, "stations": SQUARE})


def test_levelling_rise_and_fall_hand_checked():
    readings = [{"point": "BM1", "bs": 1.5}, {"point": "CP1", "fs": 1.2, "bs": 1.8, "distance": 100},
                {"point": "A", "is_reading": 2.0, "distance": 50}, {"point": "CP2", "fs": 1.6, "bs": 1.3, "distance": 50},
                {"point": "BM1", "fs": 1.805, "distance": 200}]
    out = cf.levelling({"start_elevation": 100.0, "closure": "loop", "readings": readings})
    assert val(out, "ΣBS") == 4.6 and val(out, "ΣFS") == 4.605 and val(out, "Arithmetic check") == "Correct"
    assert val(out, "Misclosure") == -5.0 and close(val(out, "Allowable misclosure"), 8 * math.sqrt(0.4))
    assert val(out, "Closure check") == "Within tolerance" and val(out, "Set-ups") == 3
    book = rows_of(out, "Level book (rise and fall)")
    assert book[2]["Fall (m)"] == "0.200" and book[2]["Reduced level (m)"] == "100.100"
    assert float(book[1]["Correction (m)"]) == pytest.approx(0.00125, abs=1e-4) and book[-1]["Adjusted level (m)"] == "100.000"
    # Without distances the misclosure is spread by set-up: CP1 is read from the first of three set-ups.
    no_dist = [{k: v for k, v in r.items() if k != "distance"} for r in readings]
    book = rows_of(cf.levelling({"start_elevation": 100.0, "readings": no_dist}), "Level book (rise and fall)")
    assert float(book[1]["Correction (m)"]) == pytest.approx(0.005 / 3, abs=1e-4)
    link = cf.levelling({"start_elevation": 100.0, "end_elevation": 100.010, "closure": "link", "readings": readings,
                         "allowable_factor": 12})
    assert val(link, "Misclosure") == -15.0 and val(link, "Closure check") == "Exceeds tolerance"
    with pytest.raises(CalcError):
        cf.levelling({"start_elevation": 100.0, "readings": [{"point": "A", "fs": 1.0}, {"point": "B", "fs": 1.2}]})


# --------------------------------------------------------------------------- #
# Geotechnical
# --------------------------------------------------------------------------- #

def test_pocket_penetrometer_and_test_pit():
    out = cf.pocket_penetrometer(example("pocket_penetrometer"))
    r = rows_of(out, "Pocket penetrometer")
    assert len(r) == 15 and close(r[0]["qu (kPa)"], 98.07) and r[0]["Consistency"] == "Medium stiff"
    assert r[10]["Consistency"] == "Stiff"
    out = cf.test_pit(example("test_pit"))
    assert val(out, "Layers") == 4 and val(out, "Logged depth") == 2.0 and close(val(out, "Maximum qu"), 3.0 * 98.0665)
    assert not any("not continuous" in n for n in out["notes"])


def _spt_example_rows():
    data = example("spt_corrected")
    return data, data["tests"]


SPT_EXPECTED = [  # template results: depth, sigma_v_eff, cn, cr, n60, n1_60
    (1, 19, 1.7, 0.75, 177.589, 301.902), (2.5, 43, 1.7, 0.85, 11.971, None), (4, 65.5, 1.5267, 0.85, 7.367, None),
    (5.5, 88, 1.1364, 0.95, 7.204, None), (7, 110.5, 0.905, 0.95, 5.146, None), (8.5, 133, 0.7519, 1.0, 8.667, None),
    (10, 147.5, 0.678, 1.0, 6.5, None), (11.5, 155, 0.6452, 1.0, 7.583, None), (13, 162.5, 0.6154, 1.0, 9.75, None),
    (14.5, 171.5, 0.5831, 1.0, 11.917, None), (16, 180.5, 0.577, 1.0, 10.833, None), (17.5, 188, 0.577, 1.0, 9.75, None),
    (19, 197, 0.577, 1.0, 15.167, None), (20.5, 210.5, 0.6164, 1.0, 138.125, 85.145), (22, 224, 0.592, 1.0, 184.167, 109.031),
    (23, 0, 0, 1.0, 241.429, 139.318),
]


def test_spt_template_options_reproduce_template():
    data, rows = _spt_example_rows()
    out = cf.spt_correction(dict(data, gamma_w=10, cn_method="template"), rows)
    got = rows_of(out, "SPT corrections")
    assert len(got) == len(SPT_EXPECTED)
    for g, (depth, sve, cn, cr, n60, n160) in zip(got, SPT_EXPECTED):
        assert g["Depth (m)"] == depth and g["CR"] == cr and close(g["N60"], n60, rel=6e-4)
        if sve:
            assert close(g["σ'v (kPa)"], sve, rel=6e-4) and close(g["CN"], cn, rel=1e-3)
        if n160 is None:
            assert g["(N1)60"] is None and g["N corrected"] == g["N60"]
        else:
            assert close(g["(N1)60"], n160, rel=6e-4)
    assert val(out, "Refusals") == 4 and got[0]["Remark"] == "Refusal"


def test_spt_default_corrections_hand_checked():
    data, rows = _spt_example_rows()
    got = rows_of(cf.spt_correction(data, rows), "SPT corrections")
    sand = next(g for g in got if g["Depth (m)"] == 20.5)
    sv = 323.5  # same unit weights as the template
    sve = sv - 9.81 * (20.5 - 9.2)
    cn = math.sqrt(100 / sve)
    n60 = 51 * 30 / 12 * 65 / 60
    assert close(sand["σ'v (kPa)"], sve, rel=6e-4) and close(sand["CN"], cn, rel=1e-3) and close(sand["(N1)60"], n60 * cn, rel=1e-3)
    clay = next(g for g in got if g["Depth (m)"] == 10)
    assert clay["CN"] is None and clay["Consistency / density"] == "Medium stiff"
    # Corrections fixed against the template: small holes are CB = 1.0, short rods CR = 0.75, long rods CR = 1.0.
    assert cf._cb(60) == 1.0 and cf._cb(115) == 1.0 and cf._cb(150) == 1.05 and cf._cb(200) == 1.15
    assert cf._cb(132.5) == pytest.approx(1.025) and cf._cb(175) == pytest.approx(1.10) and cf._cb(250) == 1.15
    assert cf._cr(0.5) == 0.75 and cf._cr(3.5) == 0.80 and cf._cr(5) == 0.85 and cf._cr(8) == 0.95 and cf._cr(35) == 1.0
    # Borehole-page style rows: depth, n, uscs, penetration in mm.
    out = cf.spt_correction({"energy_ratio": 60, "stick_up": 0}, [{"depth": 2, "n": 10, "uscs": "SM"}, {"depth": 4, "n": 50, "penetration_mm": 150, "uscs": "CL"}])
    r = rows_of(out, "SPT corrections")
    assert r[0]["Soil"] == "Sand" and r[0]["N60"] == pytest.approx(7.5) and r[1]["N (300 mm)"] == 100
    # Stick-up not recorded: 1.5 m is assumed, so the 2 m test has 3.5 m of rod (CR 0.80).
    out = cf.spt_correction({"energy_ratio": 60}, [{"depth": 2, "n": 10, "uscs": "SM"}])
    assert rows_of(out, "SPT corrections")[0]["N60"] == pytest.approx(8.0) and any("1.5 m" in n for n in out["notes"])
    from backend.app import sheets_field
    assert sheets_field.spt_correction is cf.spt_correction
    with pytest.raises(CalcError):
        cf.spt_correction({}, [])


FVST_EXPECTED = [  # template input sheet: f_uc, t_uc, su_uc_kpa, su_rc_kpa, sensitivity
    (59.328, 711.936, 88.2864, 54.057, 1.6332), (56.042, 672.504, 83.3969, 49.167, 1.6962),
    (54.399, 652.788, 80.9517, 46.7223, 1.7326), (52.756, 633.072, 78.5069, 44.277, 1.7731),
]


def test_fvst_against_template_and_bjerrum_cap():
    import json
    base = example("fvst")
    out = cf.fvst(base)
    f, torque, su, su_r, st = FVST_EXPECTED[0]
    assert close(val(out, "Peak force"), f, rel=1e-4) and close(val(out, "Peak torque"), torque, rel=1e-4)
    assert close(val(out, "su peak", "kPa"), su, rel=2e-4) and close(val(out, "su remoulded", "kPa"), su_r, rel=2e-4)
    assert close(val(out, "Sensitivity St"), st, rel=1e-3)
    # PI 14 gives μ = 1.08 in the template; it is limited to one.
    assert val(out, "Bjerrum μ") == 1.0 and val(out, "Corrected su peak") == val(out, "su peak", "kPa")
    # The other template rows: same dial series shifted by −2, −3, −4 divisions (rows 2–4).
    for shift, (f, torque, su, su_r, st) in zip((2, 3, 4), FVST_EXPECTED[1:]):
        rows = [dict(r, dial_uc=r["dial_uc"] - shift, dial_rc=r["dial_rc"] - shift) for r in base["readings"]]
        out = cf.fvst(dict(base, readings=rows, plasticity_index=40))
        assert close(val(out, "su peak", "kPa"), su, rel=2e-4) and close(val(out, "Sensitivity St"), st, rel=1e-3)
        mu = 1.7 - 0.54 * math.log10(40)
        assert close(val(out, "Bjerrum μ"), mu, abs_=1e-3) and close(val(out, "Corrected su peak"), mu * val(out, "su peak", "kPa"), rel=1e-3)
    # Process sheet: the template converts with 30.54 cm per foot (87.89 kPa); 30.48 gives 88.24 kPa.
    proc = {"vane_size": "2.5", "torque_arm": "12", "calib_a": 1.64259166666667, "calib_b": 3.44622222222222,
            "readings": [{"rotation": 5 * (i + 1), "dial_uc": u, "dial_rc": r} for i, (u, r) in enumerate(zip(
                [26, 28, 34, 29, 27.5, 25, 24, 23, 23, 23, 23.5, 22, 22, 21.5, 21], [12, 14, 16, 20, 17, 17, 16.5, 16.5, 15, 14, 13, 11, 10.5, 10.5, 10]))]}
    out = cf.fvst(proc)
    assert close(val(out, "su peak", "psf"), 1842.87, rel=1e-5) and close(val(out, "su peak", "kPa"), 1842.87 * 0.04788026, rel=1e-4)
    assert "Enter the plasticity index to apply the Bjerrum correction." in out["notes"]
    # Vane from its dimensions: 2.5 × 5 in vane, K = 144 / (π D² (H/2 + D/6)).
    out = cf.fvst(dict(proc, vane_size="custom", vane_diameter_mm=63.5, vane_height_mm=127))
    assert close(val(out, "Vane constant K"), 144 / (math.pi * 6.25 * (2.5 + 2.5 / 6)), rel=1e-3)
    assert json.dumps(out)


def test_permeability_constant_falling_rising():
    out = cf.perm_constant(example("perm_constant"))
    f = 2 * math.pi * 0.5 / math.asinh(0.5 / 0.115)
    k1 = 7e-3 / 60 / (f * 1.70)
    first = rows_of(out, "Constant head readings")[0]
    assert close(first["k (m/s)"], k1, rel=1e-3) and close(val(out, "Shape factor F"), f, rel=1e-3)
    # Head computed when not entered: water at the casing top (0.5 m) + groundwater depth 1.3 m.
    data = example("perm_constant")
    data.pop("head")
    assert val(cf.perm_constant(data), "Head H") == 1.8
    assert cf.shape_factor("casing_end", None, 0.1) == pytest.approx(0.275)
    assert cf.shape_factor("casing_end_boundary", None, 0.1) == pytest.approx(0.2)
    assert cf.shape_factor("section_boundary", 1.0, 0.1) == pytest.approx(2 * math.pi / math.asinh(20))
    # Falling and rising head built from k = 1e-5 m/s.
    f = 2 * math.pi * 1.0 / math.asinh(1.0 / 0.1)
    area = math.pi * 0.05 ** 2 / 4
    eq = 0.5 + 3.0
    geo = {"test_top": 5, "test_length": 1, "hole_diameter": 100, "casing_diameter": 50, "stick_up": 0.5, "gwl": 3}
    for rising, fn in ((False, cf.perm_falling), (True, cf.perm_rising)):
        sign = 1 if rising else -1
        rows = [{"time_min": t, "depth_to_water": eq + sign * 2.0 * math.exp(-1e-5 * f / area * t * 60)} for t in (0, 1, 2, 5, 10, 20)]
        out = fn(dict(geo, readings=rows))
        assert close(val(out, "k", "m/s"), 1e-5, rel=1e-3)
    with pytest.raises(CalcError):
        cf.perm_falling(dict(geo, readings=[{"time_min": 0, "depth_to_water": 1}]))


def test_lugeon_values_and_flow_behaviour():
    def run(flows):
        stages = [{"stage": s, "pressure": p, "flow_lpm": q} for s, p, q in zip("ABCBA", (2, 4, 6, 4, 2), flows)]
        return cf.lugeon({"test_top": 10, "test_bottom": 15, "gauge_height": 1, "gwl": 5, "stages": stages})
    out = run([10.6, 20.9, 31.2, 20.9, 10.6])
    p_w = 9.81 * (1 + 5) / 100
    first = rows_of(out, "Pressure stages")[0]
    assert close(first["Lugeon (Lu)"], 10.6 / 5 * 10 / (2 + p_w), rel=1e-3) and close(val(out, "Water column pressure"), p_w)
    assert val(out, "Flow behaviour") == "Laminar"
    assert close(val(out, "Lugeon value"), sum(r["Lugeon (Lu)"] for r in rows_of(out, "Pressure stages")) / 5, rel=2e-3)
    assert val(run([10, 20, 60, 20, 10]), "Flow behaviour") == "Dilation"
    assert val(run([30, 40, 45, 40, 30]), "Flow behaviour") == "Turbulent"
    assert val(run([5, 15, 30, 30, 25]), "Flow behaviour") == "Wash-out"
    assert val(run([25, 30, 30, 15, 5]), "Flow behaviour") == "Void filling"
    # Volume over the stage duration and a pressure in kg/cm².
    out = cf.lugeon({"test_top": 0, "test_bottom": 5, "pressure_unit": "kgcm2", "stages": [
        {"pressure": 1, "volume_l": 100, "duration_min": 10}, {"pressure": 2, "volume_l": 200}, {"pressure": 1, "volume_l": 100}]})
    assert close(rows_of(out, "Pressure stages")[0]["Effective pressure (bar)"], 0.980665 + 9.81 * 2.5 / 100, rel=1e-3)
    with pytest.raises(CalcError):
        cf.lugeon({"test_top": 5, "test_bottom": 5, "stages": []})


def test_field_cbr_template_example_and_rules():
    data = example("cbr_field")
    out = cf.cbr_field(data)
    expected_psi = [0.0, 112.8, 231.867, 325.867, 404.2, 470.0, 554.6, 629.8, 726.933, 836.6, 924.333]
    got = [r["Pressure A (psi)"] for r in rows_of(out, "Pressure readings")]
    assert got == pytest.approx(expected_psi, rel=1e-3)
    assert close(val(out, "CBR Test A at 0.1 in"), 40.42) and close(val(out, "CBR Test A at 0.2 in"), 48.46, rel=2e-3)
    assert close(val(out, "CBR Test A"), 48.46, rel=2e-3)  # 0.2 in is higher: reported, retest advised
    assert close(val(cf.cbr_field(dict(data, report_rule="average")), "CBR Test A"), (40.42 + 48.46) / 2, rel=2e-3)
    shifted = cf.cbr_field(dict(data, zero_a=0.025))
    assert close(val(shifted, "CBR Test A at 0.1 in"), 47.0)  # pressure read at 0.125 in
    with pytest.raises(CalcError):
        cf.cbr_field({"ring_factor": 9.4, "readings": [{"penetration": 0.1}, {"penetration": 0.2}, {"penetration": 0.3}]})


PLT_EXPECTED = [(1, 281.65, 0.17164, 1.0867), (2, 563.3, 0.34329, 2.4967), (3, 844.95, 0.51493, 3.7233), (4, 1126.6, 0.68657, 4.76),
                (5, 1408.25, 0.85822, 5.91), (6, 1689.9, 1.02986, 7.2267), (7, 1971.55, 1.20151, 8.5267), (8, 2253.2, 1.37315, 10.1833),
                (9, 2534.85, 1.54479, 12.0233), (10, 2816.5, 1.71644, 13.9933), (11, 3098.15, 1.88808, 15.85),
                (12, 3379.8, 2.05972, 17.79), (13, 2816.5, 1.71644, 15.62)]


def test_plate_load_test():
    data = example("plt")
    out = cf.plt(data)
    steps = {r["Step"]: r for r in rows_of(out, "Pressure and settlement")}
    for step, kg, p, s in PLT_EXPECTED:
        assert close(steps[step]["Load (kg)"], kg, rel=6e-4) and close(steps[step]["Settlement (mm)"], s, rel=6e-4)
        assert close(steps[step]["Pressure (kg/cm²)"], p, rel=1e-3)  # template uses π = 3.14
    assert steps[13]["Branch"] == "Unloading" and steps[12]["Branch"] == "Loading"
    assert close(val(out, "Plate area"), math.pi * 45.72 ** 2 / 4, rel=1e-4)
    q_allow = 1.1 * 98.0665 / 2
    assert close(val(out, "Allowable pressure"), q_allow, rel=1e-3)
    s_allow = val(out, "Settlement at the allowable pressure")
    p3, p4 = 844.95 * 9.80665 / 1000 / (math.pi * 0.4572 ** 2 / 4), 1126.6 * 9.80665 / 1000 / (math.pi * 0.4572 ** 2 / 4)
    assert close(s_allow, 3.7233 + (q_allow - p3) / (p4 - p3) * (4.76 - 3.7233), rel=1e-3)
    e = math.pi / 4 * (1 - 0.42 ** 2) * q_allow * 457.2 / s_allow / 1000
    assert close(val(out, "Elastic modulus E"), e, rel=2e-3)
    p1 = 281.65 * 9.80665 / 1000 / (math.pi * 0.4572 ** 2 / 4)
    p2 = 563.3 * 9.80665 / 1000 / (math.pi * 0.4572 ** 2 / 4)
    p125 = p1 + (1.25 - 1.0867) / (2.4967 - 1.0867) * (p2 - p1)
    assert close(val(out, "k at 1.25 mm (plate tested)"), p125 / 1.25, rel=2e-3)
    auto = cf.plt({k: v for k, v in data.items() if k != "yield_pressure"})
    q = val(auto, "Yield pressure", "kPa")
    assert q is not None and 0 < q < 2.06 * 98.0665 and val(auto, "Yield pressure from") == "Two-line fit on the log–log curve"


# --------------------------------------------------------------------------- #
# Geophysics
# --------------------------------------------------------------------------- #

def test_resistivity_1d_k_factors_and_repeat_error():
    r = rows_of(cf.resistivity_1d({"array": "wenner", "readings": [{"a": 10, "v1": 100, "i1": 200}]}), "Apparent resistivity")[0]
    assert close(r["K (m)"], 2 * math.pi * 10) and close(r["ρa mean (Ω·m)"], 2 * math.pi * 10 * 0.5) and r["AB/2 (m)"] == 15
    out = cf.resistivity_1d({"readings": [{"ab2": 10, "mn2": 1, "v1": 100, "i1": 100, "v2": 110, "i2": 100}]})
    r = rows_of(out, "Apparent resistivity")[0]
    k = math.pi * (100 - 1) / 2
    assert close(r["K (m)"], k) and close(r["Repeat error (%)"], 10 / 105 * 100) and r["Check"] == ""
    flagged = cf.resistivity_1d({"repeat_limit": 5, "readings": [{"ab2": 10, "mn2": 1, "v1": 100, "i1": 100, "v2": 110, "i2": 100}]})
    assert val(flagged, "Readings to repeat") == 1
    with pytest.raises(CalcError):
        cf.resistivity_1d({"readings": [{"ab2": 1, "mn2": 2, "v1": 1, "i1": 1}]})


def test_resistivity_2d_arrays_and_pseudo_section():
    expected_k = {"wenner": 2 * math.pi * 10, "dipole_dipole": math.pi * 2 * 3 * 4 * 5,
                  "wenner_schlumberger": math.pi * 2 * 3 * 5, "pole_dipole": 2 * math.pi * 2 * 3 * 5}
    for array, k in expected_k.items():
        out = cf.resistivity_2d({"array": array, "spacing": 5, "readings": [{"n": 2, "v": 10, "i": 100}, {"n": 2, "v": 12, "i": 100}]})
        r = rows_of(out, "Apparent resistivity")
        assert close(r[0]["K (m)"], k) and close(r[0]["ρa (Ω·m)"], k * 0.1) and r[1]["C1 (m)"] == r[0]["C1 (m)"] + 5
    out = cf.resistivity_2d({"array": "wenner", "spacing": 5, "line_start": 0, "readings": [{"n": 1, "v": 10, "i": 100}]})
    r = rows_of(out, "Apparent resistivity")[0]
    assert (r["C1 (m)"], r["P1 (m)"], r["P2 (m)"], r["C2 (m)"]) == (0, 5, 10, 15) and r["Datum x (m)"] == 7.5
    assert close(r["Pseudo-depth (m)"], 0.519 * 5)
    pseudo = out["charts"][0]
    assert pseudo["kind"] == "value" and pseudo["points"][0][:2] == [7.5, pytest.approx(2.595)] and pseudo["y"]["reverse"]
    assert close(cf._pseudo_depth("dipole_dipole", 1, 1), 0.416) and cf._pseudo_depth("dipole_dipole", 10, 1) > 2.236


def _downhole_rows(x=2.0):
    rows, t, prev = [], 0.0, 0.0
    for z in range(1, 11):
        slant = math.hypot(z, x)
        t += (slant - prev) / (150 if z <= 5 else 300)
        prev = slant
        rows.append({"depth": z, "ts": t * 1000, "tp": t * 1000 / 2.5})
    return rows


def test_downhole_interval_velocity_and_vs30():
    out = cf.downhole({"source_offset": 2.0, "unit_weight": 18, "readings": _downhole_rows()})
    r = rows_of(out, "Downhole velocities")
    assert close(r[0]["Slant distance (m)"], math.hypot(1, 2)) and close(r[2]["Vs interval (m/s)"], 150) and close(r[7]["Vs interval (m/s)"], 300)
    assert close(r[7]["Vp interval (m/s)"], 750) and r[7]["Vs apparent (m/s)"] < 300  # template's average is lower
    assert close(r[7]["Gmax (MPa)"], 18 / 9.81 * 300 ** 2 / 1000)
    nu = (2.5 ** 2 - 2) / (2 * (2.5 ** 2 - 1))
    assert close(r[7]["ν"], nu) and close(r[7]["E (MPa)"], 2 * 18 / 9.81 * 300 ** 2 / 1000 * (1 + nu))
    assert close(val(out, "Vs30"), 30 / (5 / 150 + 25 / 300)) and val(out, "Site class (SNI 1726:2019)").startswith("SD")
    assert r[0]["Check"] == "Close to the source" and r[9]["Check"] == ""
    with pytest.raises(CalcError):
        cf.downhole({"readings": _downhole_rows()})


def test_crosshole_direct_and_interval():
    rows = [{"depth": d, "tp1": 2.0, "ts1": 10.0, "tp2": 4.0, "ts2": 20.0} for d in (2, 4, 6)]
    out = cf.crosshole({"spacing_r1": 3, "spacing_r2": 6, "unit_weight": 19, "readings": rows})
    r = rows_of(out, "Crosshole velocities")[0]
    assert close(r["Vs direct R1 (m/s)"], 300) and close(r["Vp interval (m/s)"], 1500) and close(r["Vs interval (m/s)"], 300)
    nu = (1500 ** 2 - 2 * 300 ** 2) / (2 * (1500 ** 2 - 300 ** 2))
    g = 19 / 9.81 * 300 ** 2 / 1000
    assert close(r["ν"], nu) and close(r["Gmax (MPa)"], g) and close(r["E (MPa)"], 2 * g * (1 + nu))
    assert close(val(out, "Vs30"), 300)


def test_thermal_needle_probe():
    q, lam = 10.0, 1.5
    s = q / (4 * math.pi * lam)
    rows = [{"time": t, "temperature": 25 + s * math.log(t)} for t in range(1, 61)]
    rows += [{"time": t, "temperature": 25 + s * math.log(t / (t - 60)), "phase": "cooling"} for t in range(61, 121)]
    out = cf.thermal_resistivity({"heat_input": q, "readings": rows})
    assert close(val(out, "λ heating"), 1.5) and close(val(out, "λ cooling"), 1.5)
    assert close(val(out, "Thermal resistivity R", "m·K/W"), 1 / 1.5) and close(val(out, "Thermal resistivity R", "°C·cm/W"), 66.67)
    # Q = E I / L: 4 V × 0.5 A over 0.1 m = 20 W/m, twice the heat for the same slope.
    out = cf.thermal_resistivity({"current": 0.5, "voltage": 4, "probe_length": 100, "readings": rows[:60]})
    assert close(val(out, "Heat input Q"), 20) and close(val(out, "Thermal conductivity λ"), 3.0)
    with pytest.raises(CalcError):
        cf.thermal_resistivity({"readings": rows})


# --------------------------------------------------------------------------- #
# Through the API
# --------------------------------------------------------------------------- #

def test_field_worksheet_round_trip(client, admin_headers):
    body = {"code": "BH-21", "type": "geotechnical", "method": "spt_corrected", "date": "2026-10-01",
            "data": sheets.get("field", "spt_corrected").example}
    res = client.post("/api/records/field_activities", json=body, headers=admin_headers)
    assert res.status_code == 201, res.text
    rec = res.json()
    assert rec["results_calc"]["summary"] and rec["summary"].startswith("Tests = 16")
    assert rec["results_calc"]["tables"][0]["title"] == "SPT corrections"
    # A half-filled worksheet is stored with the calculation error.
    res = client.post("/api/records/field_activities", json={"code": "T-1", "type": "survey", "method": "traverse", "date": "2026-10-01",
                                                            "data": {"stations": [{"station": "A", "angle_d": 90}]}}, headers=admin_headers)
    assert res.status_code == 201 and res.json()["results_calc"]["error"]
    # Preview without saving, and the catalogue lists the pages and standards.
    res = client.post("/api/worksheets/calc", json={"kind": "field", "key": "levelling", "data": {"start_elevation": 10, "readings": [
        {"point": "BM", "bs": 1.0}, {"point": "BM", "fs": 1.002, "distance": 100}]}}, headers=admin_headers)
    assert res.status_code == 200 and res.json()["summary"].startswith("Misclosure = -2")
    cat = {s["key"]: s for s in client.get("/api/worksheets", headers=admin_headers).json()}
    assert cat["fvst"]["standards"][0][0] == "ASTM D2573" and cat["cpt_page"]["link"] == "cpt"
