"""Coordinates, KML export, CPT interpretation, seismic site class, bearing table, sample register."""
import math

import pytest

from backend.app import cpt_calc, geo, seismic
from backend.app.calcbase import CalcError


def test_utm_round_trip_and_known_point():
    u = geo.to_utm(-6.2, 106.8)
    assert u["zone"] == 48 and u["hemisphere"] == "S"
    assert abs(u["easting"] - 699163.4) < 1 and abs(u["northing"] - 9314349.0) < 1
    back = geo.from_utm(u["easting"], u["northing"], 48, "S")
    assert abs(back["latitude"] + 6.2) < 1e-7 and abs(back["longitude"] - 106.8) < 1e-7
    assert geo.utm_zone(-7.25, 112.75) == 49
    with pytest.raises(ValueError):
        geo.to_utm(-85, 100)
    assert "6° 12' 0.00\" S" in geo.describe(-6.2, 106.8)["dms"]


def test_kml_escapes_names():
    text = geo.kml("P & Q", [("BH-<1>", -6.2, 106.8, 12.0, "Boreholes", "a & b")])
    assert "BH-&lt;1&gt;" in text and "106.80000000,-6.20000000,12" in text and "P &amp; Q" in text


def _cpt(**extra):
    readings = [{"depth": round(0.2 * i, 2), "qc": 5 + i * 0.5 if i < 40 else 120, "fs": 0.3 if i < 40 else 1.0} for i in range(1, 60)]
    return {"readings": readings, "gw_depth": 1.0, "qc_unit": "kgcm2", **extra}


def test_cpt_interpretation_zones_and_dissipation():
    out = cpt_calc.interpret(_cpt())
    assert "Maximum qt" in out["summary"]
    zones = {row[0] for row in out["tables"][0]["rows"]}
    assert 3 in zones or 4 in zones  # soft clay part
    assert any(z in zones for z in (5, 6, 7))  # sand at the bottom
    record = _cpt(dissipation_depth=8.0, dissipation=[{"time": t, "u2": 70 + 300 * math.exp(-t / 120)} for t in (1, 5, 10, 30, 60, 120, 300, 600, 1200)])
    out = cpt_calc.interpret(record)
    labels = {v["label"]: v["value"] for v in out["values"]}
    assert labels["t50"] and 30 < labels["t50"] < 200
    assert labels["ch (Teh & Houlsby)"] > 0
    with pytest.raises(CalcError):
        cpt_calc.interpret({"readings": [{"depth": 1, "qc": 2}]})


def test_site_class_and_spectrum():
    assert seismic.classify(n=10) == "SE" and seismic.classify(n=30) == "SD" and seismic.classify(vs=400) == "SC"
    d = seismic.design("SD", pga=0.4, ss=0.8, s1=0.4)
    assert abs(d["fa"] - 1.18) < 1e-9 and abs(d["fv"] - 1.9) < 1e-9 and abs(d["fpga"] - 1.2) < 1e-9
    assert abs(d["sds"] - 2 / 3 * 1.18 * 0.8) < 1e-9
    avg, _ = seismic.average_over_30m([(0, 10, 100), (10, 30, 300)])
    assert abs(avg - 30 / (10 / 100 + 20 / 300)) < 1e-9
    out = seismic.site_class_analysis({"pga": 0.3, "ss": 0.7, "s1": 0.3}, [(1.5, 4), (3, 6), (6, 8)])
    assert out["summary"].startswith("Site class = SE")
    with pytest.raises(CalcError):
        seismic.site_class_analysis({"pga": 0.3}, [])


def test_analyses_endpoint_new_types(client, admin_headers):
    res = client.post("/api/analyses/run", json={"type": "bearing_table", "inputs": {
        "B_list": "1 2", "Df_list": "1", "c": 5, "phi_deg": 30, "gamma": 18, "fs": 2.5}}, headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["tables"][0]["rows"][0]) == 3 and "SNI 8460" in body["notes"][0]
    res = client.post("/api/analyses/run", json={"type": "site_class", "inputs": {
        "pga": 0.4, "ss": 0.9, "s1": 0.4, "vs_layers": [{"top": 0, "base": 30, "vs": 250}]}}, headers=admin_headers)
    assert res.status_code == 200 and "SD" in res.json()["summary"]
    assert client.post("/api/analyses/run", json={"type": "bearing_table", "inputs": {"B_list": "x"}}, headers=admin_headers).status_code == 422


def test_coordinates_endpoint_and_kml(client, admin_headers):
    res = client.post("/api/tools/coordinates", json={"rows": [
        {"name": "A", "latitude": -6.2, "longitude": 106.8},
        {"name": "B", "easting": 699163.391, "northing": 9314348.962, "zone": 48, "hemisphere": "S"},
        {"name": "C"},
    ]}, headers=admin_headers)
    rows = res.json()
    assert rows[0]["zone"] == 48 and abs(rows[1]["latitude"] + 6.2) < 1e-6 and "error" in rows[2]
    res = client.post("/api/tools/kml", json={"name": "Titik", "points": [{"name": "A", "latitude": -6.2, "longitude": 106.8}]}, headers=admin_headers)
    assert res.status_code == 200 and "<kml" in res.text and "attachment" in res.headers["content-disposition"]


def test_project_kml_and_sample_register(client, admin_headers):
    c = client.post("/api/records/clients", json={"name": "Klien", "type": "private"}, headers=admin_headers).json()
    p = client.post("/api/records/projects", json={"code": "K-1", "name": "Proyek Peta", "client_id": c["id"], "status": "ongoing"}, headers=admin_headers).json()
    assert client.get(f"/api/export/kml?project_id={p['id']}", headers=admin_headers).status_code == 422
    report = {"BoreholeID": "BH-K1", "ProjectName": "Proyek Peta", "SiteName": "A", "StartDate": "2026-10-01", "EndDate": "2026-10-02",
              "DrillingMethod": "Coring + SPT", "FinalDepth_m": "10", "Contractor": "X", "Latitude": "-6.3", "Longitude": "106.9"}
    assert client.post("/api/reports", json=report, headers=admin_headers).status_code == 201
    details = {"layers": [], "spt": [], "core": [], "photos": [],
               "samples": [{"top": 2.0, "base": 2.5, "type": "U", "ref": "UDS-1"}, {"top": 5.0, "base": 5.45, "type": "D", "ref": "D-2"}]}
    assert client.put("/api/details/BH-K1", json=details, headers=admin_headers).status_code == 200
    cpt = {"test_id": "S-1", "project_id": p["id"], "date": "2026-10-03", "latitude": -6.301, "longitude": 106.901,
           "readings": [{"depth": 0.2, "qc": 5, "fs": 0.2}, {"depth": 0.4, "qc": 8, "fs": 0.3}]}
    saved = client.post("/api/records/cpt", json=cpt, headers=admin_headers).json()
    assert saved["utm"]["zone"] == 48 and "Maximum qt" in saved["summary"]
    res = client.get(f"/api/export/kml?project_id={p['id']}", headers=admin_headers)
    assert res.status_code == 200 and "BH-K1" in res.text and "S-1" in res.text
    lab = {"borehole_id": "BH-K1", "sample_ref": "UDS-1", "depth_top": 2.0, "test_type": "moisture", "status": "requested"}
    assert client.post("/api/records/lab_tests", json=lab, headers=admin_headers).status_code == 201
    samples = client.get("/api/samples?project=Proyek%20Peta", headers=admin_headers).json()
    assert [s["ref"] for s in samples] == ["UDS-1", "D-2"]
    assert samples[0]["tests"][0]["status"] == "requested" and samples[1]["tests"] == []
    assert client.get("/api/samples?project=Other", headers=admin_headers).json() == []


def test_rate_buildup_tiers_and_quote_price_checks(client, admin_headers):
    rate = {"code": "FLD-01", "description": "Bor tanah", "unit": "m", "price": 300000, "internal_price": 250000, "min_price": 200000,
            "buildup": [
                {"section": "equipment", "description": "Rig", "qty": 1, "unit_cost": 180_000_000, "life_hours": 46720, "coef": 0.667},
                {"section": "labour", "description": "Crew per day", "qty": 1, "unit_cost": 1_466_743, "life_hours": 8, "coef": 0.667},
            ],
            "contingency_pct": 5, "risk_pct": 3, "margin_internal_pct": 30, "margin_client_pct": 60, "rounding": "1000"}
    res = client.post("/api/records/rates", json=rate, headers=admin_headers)
    assert res.status_code == 201, res.text
    r = res.json()
    hpj = 180_000_000 / 46720 * 0.667 + 1_466_743 / 8 * 0.667
    assert abs(r["cost_unit"] - round(hpj)) <= 1
    base = hpj * 1.05 * 1.03
    assert r["suggested_internal"] == math.ceil(base * 1.3 / 1000) * 1000
    assert r["suggested_client"] == math.ceil(base * 1.6 / 1000) * 1000
    c = client.post("/api/records/clients", json={"name": "Grup", "type": "private", "pricing_tier": "internal"}, headers=admin_headers).json()
    p = client.post("/api/records/projects", json={"code": "Q-1", "name": "Q", "client_id": c["id"], "status": "tender"}, headers=admin_headers).json()
    item = {"rate_id": r["id"], "description": "Bor", "unit": "m", "qty": 10}
    q = client.post("/api/records/quotes", json={"project_id": p["id"], "date": "2026-10-01", "status": "draft",
                                                  "items": [{**item, "unit_price": 240000}]}, headers=admin_headers).json()
    assert "FLD-01" in q["price_check"]
    res = client.post("/api/records/quotes", json={"project_id": p["id"], "date": "2026-10-01", "status": "draft",
                                                    "items": [{**item, "unit_price": 150000}]}, headers=admin_headers)
    assert res.status_code == 422 and "minimum selling price" in res.json()["detail"]


def test_spt_correction_analysis_uses_borehole(client, admin_headers):
    report = {"BoreholeID": "BH-S1", "ProjectName": "Proyek SPT", "SiteName": "A", "StartDate": "2026-10-01", "EndDate": "2026-10-02",
              "DrillingMethod": "Coring + SPT", "FinalDepth_m": "30", "Contractor": "X", "Latitude": "-6.3", "Longitude": "106.9",
              "GroundwaterEncountered": "true", "GroundwaterDepth_m": "2"}
    assert client.post("/api/reports", json=report, headers=admin_headers).status_code == 201
    details = {"layers": [{"top": 0, "base": 6, "uscs": "CH", "description": "Lempung"}, {"top": 6, "base": 30, "uscs": "SM", "description": "Pasir"}],
               "spt": [{"depth": 3, "seat": 2, "inc1": 3, "inc2": 4}, {"depth": 10, "seat": 8, "inc1": 10, "inc2": 12},
                       {"depth": 27, "seat": 20, "inc1": 50, "penetration_mm": 100}], "core": [], "photos": [], "samples": []}
    assert client.put("/api/details/BH-S1", json=details, headers=admin_headers).status_code == 200
    res = client.post("/api/analyses/run", json={"type": "spt_correction", "inputs": {
        "borehole_id": "BH-S1", "energy_ratio": "72", "borehole_diameter_mm": "100", "rod_extra_m": "1.5", "sampler_liners": "no"}},
        headers=admin_headers)
    assert res.status_code == 200, res.text
    rows = res.json()["tables"][0]["rows"]
    assert [r[5] for r in rows] == ["Clay", "Sand", "Sand"]
    assert rows[0][16] is None and rows[1][16] is not None  # (N1)60 only for sand
    assert abs(rows[0][15] - 7 * 1.2 * 1.0 * 1.2 * 0.85) < 0.01  # N60 = N·CE·CB·CS·CR, rod 4.5 m
    assert rows[2][4] == "Refusal" and abs(rows[2][3] - 150) < 1e-6
