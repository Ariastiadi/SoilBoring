"""Daily report upgrade, sand cone, DCP, pre-drilling checklist and monitoring instruments.
Expected numbers are worked out by hand in the comments."""
import math

import pytest

from backend.app import calc_qc as cq
from backend.app import calc_field as cf
from backend.app import monitor, records, sheets
from backend.app.calcbase import CalcError
from backend.app.entities import ENTITIES

from .conftest import login_headers, make_user


def val(out, label):
    for v in out["values"]:
        if v["label"] == label:
            return v["value"]
    raise KeyError(label)


def rows_of(out, title):
    tb = next(t for t in out["tables"] if t["title"] == title)
    return [dict(zip(tb["columns"], r)) for r in tb["rows"]]


def clean(key, data):
    return records._clean_value(ENTITIES["field_activities"].field("data"), data, "Worksheet", {"method": key}, lambda *_: True)


# --------------------------------------------------------------------------- #
# Catalogue and numbering
# --------------------------------------------------------------------------- #

def test_new_sheets_are_numbered_and_their_examples_calculate():
    codes = {s.key: s.code for s in sheets.all_sheets()}
    assert codes["predrill_checklist"] == "01.05" and codes["sand_cone"] == "03.09" and codes["dcp"] == "03.10"
    assert codes["monitoring_page"] == "03.11" and sheets.get("page", "monitoring_page").link == "monitoring"
    for key in ("predrill_checklist", "sand_cone", "dcp", "daily_report"):
        sheet = sheets.get("field", key)
        out = sheets.calculate("field", key, clean(key, sheet.example))
        assert out["summary"] and out["method"], key
        assert any(c for c, _ in sheet.standards) or key == "daily_report"
    methods = {o[0] for o in ENTITIES["field_activities"].field("method").options}
    assert {"predrill_checklist", "sand_cone", "dcp"} <= methods


# --------------------------------------------------------------------------- #
# Daily report
# --------------------------------------------------------------------------- #

def test_daily_report_old_record_still_valid_and_new_fields_optional():
    old = {"report_no": 3, "weather_morning": "clear", "weather_day": "drizzle", "weather_afternoon": "heavy_rain",
           "drilling": [{"borehole": "BH-1", "plan_depth": 30, "prev_depth": 10, "today_depth": 5}]}
    data = clean("daily_report", old)
    out = cf.daily_report(data)
    assert val(out, "Drilled today") == 5 and "Hours lost" not in out["summary"]


def test_daily_report_delays_materials_crew_and_direction():
    data = clean("daily_report", {
        "weather_morning": "storm", "ground": "muddy", "access": "difficult", "rainfall": 35, "fit_for_work": "no",
        "manpower": [{"role": "Driller", "qty": 2}, {"role": "Helper", "qty": 4}], "crew_count": 7,
        "delays": [{"cause": "weather", "hours": 3}, {"cause": "breakdown", "hours": 1.5}, {"cause": "weather", "hours": 0.5}],
        "materials": [{"material": "Bentonite", "qty": 2, "unit": "sack"}],
        "pm_direction": "Move the rig to BH-2 tomorrow", "pm_direction_by": "PM@example.com", "pm_direction_date": "2026-10-21"})
    assert data["pm_direction_by"] == "pm@example.com"
    out = cf.daily_report(data)
    # hours lost 3 + 1.5 + 0.5 = 5; weather 3.5 h = 70 %
    assert val(out, "Hours lost") == 5 and val(out, "Manpower") == 7 and val(out, "Site fit for work") == "No"
    by_cause = rows_of(out, "Hours lost by cause")
    assert by_cause[0]["Delay cause"] == "Weather (rain, lightning)" and by_cause[0]["Share (%)"] == 70
    assert "The crew on site differs from the total of the manpower table; check both." in out["notes"]
    assert "Give the reason why the site was not fully fit for work." in out["notes"]
    with pytest.raises(records.RecordError):
        clean("daily_report", {"ground": "swampy"})


# --------------------------------------------------------------------------- #
# Sand cone
# --------------------------------------------------------------------------- #

def test_sand_cone_hand_calculation():
    data = {"calibration": [{"mass": 3962, "volume": 2830}], "cone_mass": 1600, "mdd": 1.85, "omc": 14, "spec_min": 95,
            "moisture_tolerance": 2,
            "points": [{"point": "A", "mass_before": 6000, "mass_after": 2400, "wet_soil": 2850, "w_tin": 20, "w_wet": 132, "w_dry": 120},
                       {"point": "B", "mass_before": 6000, "mass_after": 2400, "wet_soil": 2850, "w": 17},
                       {"point": "C", "mass_before": 6000, "mass_after": 2400, "wet_soil": 2850, "speedy": 20}]}
    out = cq.sand_cone(data)
    r = rows_of(out, "Field density")
    # ρ sand = 3962 / 2830 = 1.400; sand in hole = 3600 − 1600 = 2000 g; V = 1428.6 cm³; ρ = 2850 / 1428.6 = 1.995
    assert r[0]["Hole volume (cm³)"] == pytest.approx(1428.6, abs=0.5) and r[0]["Wet density (g/cm³)"] == pytest.approx(1.995, abs=1e-3)
    # w = 12 / 100 = 12 %; ρd = 1.995 / 1.12 = 1.781; RC = 96.3 % → pass (w − OMC = −2, within ± 2)
    assert r[0]["Water content (%)"] == 12 and r[0]["Relative compaction (%)"] == pytest.approx(96.28, abs=0.01) and r[0]["Result"] == "Pass"
    assert r[0]["Dry unit weight (kN/m³)"] == pytest.approx(1.78125 * 9.80665, abs=0.01)
    # B: ρd = 1.995 / 1.17 = 1.705 → RC 92.2 % → fail; C: speedy 20 % wet basis → w = 25 %
    assert r[1]["Result"] == "Fail" and r[2]["Water content (%)"] == 25 and r[2]["Moisture from"] == "Speedy"
    assert val(out, "Points passed") == 1 and val(out, "Points failed") == 2
    assert cq.speedy_to_dry_basis(20) == pytest.approx(25.0)
    with pytest.raises(CalcError):
        cq.sand_cone({**data, "cone_mass": 3700})  # cone takes more sand than was used at every point
    bad = cq.sand_cone({**data, "points": data["points"] + [{"point": "D", "mass_before": 6000, "mass_after": 4500, "wet_soil": 100, "w": 9}]})
    assert rows_of(bad, "Field density")[3]["Remark"] == "No sand left in the hole: check the masses" and val(bad, "Points failed") == 2
    oven = cq.sand_cone({**data, "points": [{"point": "E", "mass_before": 6000, "mass_after": 2400, "wet_soil": 2850, "w_tin": 20, "w_wet": 100, "w_dry": 120}]})
    assert rows_of(oven, "Field density")[0]["Remark"] == "Oven masses not valid: wet ≥ dry > container"
    with pytest.raises(CalcError):
        cq.sand_cone({**data, "calibration": [], "cone_mass": 1600})


def test_sand_cone_cone_trials_and_small_hole():
    out = cq.sand_cone({"sand_density": 1.4, "cone_trials": [{"before": 6500, "after": 4905}, {"before": 6480, "after": 4875}],
                        "max_particle": "25", "points": [{"point": "P", "mass_before": 6000, "mass_after": 2400, "wet_soil": 2850, "w": 10}]})
    assert val(out, "Sand in the cone") == 1600  # (1595 + 1605) / 2
    assert rows_of(out, "Field density")[0]["Remark"] == "Hole below the minimum volume"  # 1428.6 < 2125 cm³ for 25 mm
    assert "Enter the maximum dry density of the Proctor test to get the relative compaction." in out["notes"]


# --------------------------------------------------------------------------- #
# DCP
# --------------------------------------------------------------------------- #

def test_dcp_correlations():
    # ASTM D6951: CBR = 292 / DPI^1.12 (10^2.465 = 291.7)
    assert cq.cbr_from_dpi(10, "astm") == pytest.approx(10 ** 2.465 / 10 ** 1.12, rel=1e-9)
    assert cq.cbr_from_dpi(10, "astm") == pytest.approx(22.13, abs=0.01)
    assert cq.cbr_from_dpi(30, "cl") == pytest.approx(1 / (0.017019 * 30) ** 2, rel=1e-9)  # 3.84
    assert cq.cbr_from_dpi(30, "ch") == pytest.approx(11.61, abs=0.01)  # 1 / (0.002871 × 30)
    assert cq.cbr_from_dpi(10, "binamarga") == pytest.approx(10 ** (2.8135 - 1.313), rel=1e-9)  # 31.66


def test_dcp_layers_hammer_factor_and_cumulative_blows():
    readings = [{"blows": 0, "reading": 100}, {"blows": 5, "reading": 150}, {"blows": 5, "reading": 190}, {"blows": 10, "reading": 240}]
    out = cq.dcp({"readings": readings, "layers": [{"top": 0, "bottom": 90, "description": "L1"}, {"top": 90, "bottom": 140}]})
    layers = rows_of(out, "Layers")
    # L1: 90 mm in 10 blows → 9 mm/blow; L2: 50 mm in 10 blows → 5 mm/blow
    assert layers[0]["DCP index (mm/blow)"] == 9 and layers[1]["DCP index (mm/blow)"] == 5
    assert layers[0]["CBR (%)"] == pytest.approx(cq.cbr_from_dpi(9, "astm"), rel=1e-3)
    assert val(out, "Final depth") == 140 and val(out, "Total blows") == 20
    # The same readings with the 4.6 kg hammer: DCP index doubled.
    heavy = rows_of(cq.dcp({"readings": readings, "hammer": "4.6"}), "Layers")
    assert heavy[0]["Layer"] == "Whole test" and heavy[0]["DCP index (mm/blow)"] == 14  # 140 / 20 × 2
    # Cumulative blows column, no zero row: zero reading entered separately, test surface 50 mm down.
    cum = cq.dcp({"blows_mode": "cumulative", "zero_reading": 100, "start_depth": 50,
                  "readings": [{"blows": 5, "reading": 150}, {"blows": 10, "reading": 190}]})
    assert rows_of(cum, "Readings")[0]["From (mm)"] == 50 and rows_of(cum, "Readings")[1]["DCP index (mm/blow)"] == 8
    with pytest.raises(CalcError):
        cq.dcp({"readings": [{"blows": 0, "reading": 100}, {"blows": 5, "reading": 90}]})


# --------------------------------------------------------------------------- #
# Pre-drilling checklist
# --------------------------------------------------------------------------- #

def _all_yes():
    return {key: "yes" for key, _, _, _ in cq.CHECK_ITEMS}


def test_checklist_fit_to_start_rules_and_excavation_slope():
    jsa = [{"step": "Drilling", "hazard": "Rotating rods", "risk": "high", "control": "Guards"}]
    assert val(cq.predrill_checklist({**_all_yes(), "jsa": jsa}), "Result") == "Fit to start"
    assert val(cq.predrill_checklist({**_all_yes(), "housekeeping": "no", "jsa": jsa}), "Result") == "Fit to start, with actions"
    out = cq.predrill_checklist({**_all_yes(), "utility_scan": "no", "jsa": jsa})
    assert val(out, "Result") == "Not fit to start"
    assert rows_of(out, "Items to resolve")[0]["Kind"] == "Stops the work"
    unanswered = _all_yes()
    unanswered.pop("ppe")
    assert val(cq.predrill_checklist({**unanswered, "jsa": jsa}), "Result") == "Checklist incomplete"
    # A high-risk JSA step without a control keeps the checklist incomplete.
    assert val(cq.predrill_checklist({**_all_yes(), "jsa": [{"step": "Drilling", "risk": "high"}]}), "Result") == "Checklist incomplete"
    # A critical "other" item answered No stops the work.
    other = [{"item": "Gas test in the pit", "answer": "no", "critical": True}]
    assert val(cq.predrill_checklist({**_all_yes(), "other_checks": other, "jsa": jsa}), "Result") == "Not fit to start"
    # 2.0 m pit in type B soil: 1H:1V (45°), set-back 2.0 m; type C: 1.5H:1V (33.7°), set-back 3.0 m
    b = cq.predrill_checklist({**_all_yes(), "jsa": jsa, "excavation_depth": 2.0, "soil_type": "B"})
    assert val(b, "Maximum slope (H:V)") == "1 : 1" and val(b, "Slope angle") == 45 and val(b, "Set-back of the top edge each side") == 2
    c = cq.predrill_checklist({**_all_yes(), "jsa": jsa, "excavation_depth": 2.0, "soil_type": "C"})
    assert val(c, "Slope angle") == pytest.approx(33.7, abs=0.05) and val(c, "Set-back of the top edge each side") == 3
    assert val(cq.predrill_checklist({**_all_yes(), "jsa": jsa, "excavation_depth": 2.0}), "Result") == "Checklist incomplete"
    with pytest.raises(CalcError):
        cq.predrill_checklist({})


# --------------------------------------------------------------------------- #
# Monitoring instruments
# --------------------------------------------------------------------------- #

def test_piezometer_series_alarm_and_rate():
    rec = {"type": "standpipe", "unit": "m", "elevation": 25.0, "reading_is_depth": True, "alarm_on": "below",
           "alert_level": 2.0, "action_level": 1.5,
           "readings": [{"date": "2026-10-10", "value": 2.4}, {"date": "2026-10-01", "value": 3.0}, {"date": "2026-10-05", "value": 2.8}]}
    monitor.compute_instrument(rec)
    # sorted: 3.0 (base), 2.8, 2.4; last interval 2.8 → 2.4 over 5 days = −0.08 m/day; still above the 2.0 alert level
    assert [r["date"] for r in rec["readings"]] == ["2026-10-01", "2026-10-05", "2026-10-10"]
    assert rec["latest_value"] == 2.4 and rec["change"] == pytest.approx(-0.6) and rec["rate_per_day"] == pytest.approx(-0.08)
    assert rec["alarm_state"] == "normal" and val(rec["results"], "Water level") == pytest.approx(22.6)
    rec["readings"].append({"date": "2026-10-12", "value": 1.9})
    monitor.compute_instrument(rec)
    assert rec["alarm_state"] == "alert"
    rec["readings"].append({"date": "2026-10-13", "value": 1.5})
    monitor.compute_instrument(rec)
    assert rec["alarm_state"] == "action" and val(rec["results"], "Alert level first reached on") == "2026-10-12"


def test_settlement_change_basis_and_rate_alert():
    rec = {"type": "settlement_plate", "base_value": 0, "alert_level": 50, "action_level": 100, "rate_alert": 5,
           "readings": [{"date": "2026-09-01", "value": 0}, {"date": "2026-09-11", "value": 20}, {"date": "2026-09-13", "value": 32}]}
    monitor.compute_instrument(rec)
    # change 32 mm < 50 alert, but rate (32 − 20) / 2 = 6 mm/day ≥ 5 → alert
    assert rec["change"] == 32 and rec["rate_per_day"] == 6 and rec["alarm_state"] == "alert"
    rec2 = {"type": "extensometer", "readings": []}
    monitor.compute_instrument(rec2)
    assert rec2["alarm_state"] == "no_data" and rec2["results"] == {}


def test_inclinometer_incremental_profile():
    # Two surveys, increments 1 mm at each of 3 depths (A) → cumulative at the top 3 mm; B 4 mm at the top only.
    rows = [{"date": "2026-10-01", "depth": z, "a": 0, "b": 0} for z in (0.5, 1.0, 1.5)]
    rows += [{"date": "2026-10-11", "depth": 1.5, "a": 1, "b": 0}, {"date": "2026-10-11", "depth": 1.0, "a": 1, "b": 0},
             {"date": "2026-10-11", "depth": 0.5, "a": 1, "b": 4}]
    rec = {"type": "inclinometer", "incl_input": "incremental", "alert_level": 4, "action_level": 10, "profile": rows}
    monitor.compute_instrument(rec)
    prof = monitor.incline_profiles(rows, True)["2026-10-11"]
    assert prof == [(0.5, 3.0, 4.0), (1.0, 2.0, 0.0), (1.5, 1.0, 0.0)]
    # top resultant √(3² + 4²) = 5 mm at 0.5 m, over 10 days → 0.5 mm/day; 5 ≥ 4 → alert
    assert rec["latest_value"] == 5 and rec["rate_per_day"] == 0.5 and rec["alarm_state"] == "alert"
    assert val(rec["results"], "At depth") == 0.5 and rec["reading_count"] == 2


def test_instruments_roles_and_api(client, admin_headers):
    field = login_headers(client, *make_user("crew@example.com", role="general"))
    lab = login_headers(client, *make_user("lab@example.com", role="lab"))
    body = {"code": "PZ-01", "type": "vw_piezometer", "unit": "kPa", "alarm_on": "above", "alert_level": 40, "action_level": 60,
            "readings": [{"date": "2026-10-01", "value": 20}, {"date": "2026-10-03", "value": 45}]}
    res = client.post("/api/records/instruments", json=body, headers=field)
    assert res.status_code == 201, res.text
    rec = res.json()
    assert rec["alarm_state"] == "alert" and rec["latest_date"] == "2026-10-03" and rec["rate_per_day"] == 12.5
    assert client.post("/api/records/instruments", json={**body, "code": "PZ-02"}, headers=lab).status_code == 403
    assert client.get("/api/records/instruments", headers=lab).status_code == 200
    assert client.post("/api/records/instruments", json={**body, "readings": [{"date": "01/10/2026", "value": 1}]},
                       headers=field).status_code == 422
    schema = client.get("/api/schemas", headers=lab).json()["instruments"]
    assert schema["can_read"] and not schema["can_create"]
    assert math.isclose(rec["results"]["values"][0]["value"], 45)
