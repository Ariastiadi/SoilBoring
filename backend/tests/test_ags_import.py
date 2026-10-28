"""AGS4 import: parse, validate, preview, duplicates and the export -> import round trip."""
from backend.app import ags_import, details, docstore, records, storage
from backend.app.ags import build_ags

from .conftest import login_headers, make_user, sample_report

PROJECT = "Jembatan Kali"


def _texts(messages):
    return [m["text"] for m in messages]


def _seed(client, headers):
    """Two logs with depth data, as a user would enter them."""
    logs = [
        sample_report(BoreholeID="BH-01", ProjectName=PROJECT, SiteName="Abutment A", Latitude="-6.176", Longitude="106.865",
                      GroundElevation_mRL="8.5", BoreholeDiameter_mm="150", CasingInstalled_mm="100", DrillRig="Rig 3",
                      SoilDescription="Lempung lanau abu-abu", USCS_Class="CH", Avg_SPT_N60="27.5", LoggingGeologist="Geolog A",
                      GroundwaterDepth_m="3.2"),
        sample_report(BoreholeID="BH-02", ProjectName=PROJECT, SiteName="Pier 1", DrillingMethod="Coring + SPT", CoreSize="HQ",
                      GroundwaterEncountered=False, GroundwaterDepth_m="", FinalDepth_m="12", Remarks="Batuan lapuk"),
    ]
    for log in logs:
        assert client.post("/api/reports", json=log, headers=headers).status_code == 201
    depth = {
        "BH-01": {
            "layers": [{"top": 0, "base": 3.5, "uscs": "CH", "description": "Lempung lunak abu-abu"},
                       {"top": 3.5, "base": 30, "uscs": "SM", "description": "Pasir lanauan"}],
            "spt": [{"depth": 2, "seat": 1, "inc1": 2, "inc2": 3}, {"depth": 4.5, "seat": 8, "inc1": 12, "inc2": 15, "remarks": "keras"},
                    {"depth": 27, "seat": 20, "inc1": 50, "penetration_mm": 80}, {"depth": 29, "seat": 15, "inc1": 30, "inc2": 20,
                                                                                     "penetration_mm": 230}],
            "samples": [{"top": 1.5, "base": 2, "type": "U", "ref": "UDS-1"}, {"top": 6, "type": "D", "ref": "D1"}],
            "core": [],
        },
        "BH-02": {
            "layers": [{"top": 0, "base": 12, "uscs": "XX", "description": "Batuan lapuk"}],
            "spt": [],
            "samples": [],
            "core": [{"top": 6, "base": 9, "tcr": 95, "scr": 80, "rqd": 60, "remarks": "retak"}],
        },
    }
    for bid, body in depth.items():
        assert client.put(f"/api/details/{bid}", json=body, headers=headers).status_code == 200
    return logs


def _export():
    return build_ags(PROJECT, storage.load_reports(), depth_data=details.all_details())[1]


def _post(client, headers, text, path="/api/import/ags/preview", **opts):
    return client.post(path, json={"filename": "test.ags", "content": text, **opts}, headers=headers)


def _same_number(a, b):
    if a in ("", None) or b in ("", None):
        return a in ("", None) and b in ("", None)
    return abs(float(a) - float(b)) < 1e-4


def test_round_trip_export_import_gives_the_same_data(client, admin_headers):
    _seed(client, admin_headers)
    before_logs = {r["BoreholeID"]: r for r in storage.load_reports()}
    before_depth = details.all_details()
    text = _export()
    docstore.reset_all_for_tests()  # a fresh install
    headers = login_headers(client, *make_user("admin@example.com", role="admin"))
    preview = _post(client, headers, text)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["errors"] == [] and body["format"] == "AGS4" and body["project"]["file"] == PROJECT
    assert {b["id"]: b["action"] for b in body["boreholes"]} == {"BH-01": "create", "BH-02": "create"}
    assert {g["group"]: g["use"] for g in body["groups"]}["GEOL"] == "Strata"
    res = _post(client, headers, text, path="/api/import/ags")
    assert res.status_code == 200, res.text
    assert res.json()["created"] == 2
    after_logs = {r["BoreholeID"]: r for r in storage.load_reports()}
    numeric = ("Latitude", "Longitude", "GroundElevation_mRL", "BoreholeDiameter_mm", "TargetDepth_m", "FinalDepth_m",
               "CasingInstalled_mm", "GroundwaterDepth_m", "Avg_SPT_N60")
    for bid, old in before_logs.items():
        new = after_logs[bid]
        for key in storage.HEADERS:
            if key == "SubmittedBy":
                continue
            if key in numeric:
                assert _same_number(old[key], new[key]), (bid, key, old[key], new[key])
            else:
                assert old[key] == new[key], (bid, key, old[key], new[key])
    after_depth = details.all_details()
    for bid, old in before_depth.items():
        for part in ("layers", "spt", "samples", "core"):
            assert old[part] == after_depth[bid][part], (bid, part)
    # Exporting again gives the same file (apart from the date line).
    assert _export().replace("\r\n", "\n").split("\n")[10:] == text.replace("\r\n", "\n").split("\n")[10:]


def test_duplicates_are_skipped_or_overwritten(client, admin_headers):
    _seed(client, admin_headers)
    text = _export().replace("Lempung lunak abu-abu", "Lempung sangat lunak")
    skip = _post(client, admin_headers, text).json()
    assert {b["action"] for b in skip["boreholes"]} == {"skip"} and not skip["can_import"]
    assert _post(client, admin_headers, text, path="/api/import/ags").status_code == 409
    over = _post(client, admin_headers, text, on_duplicate="overwrite").json()
    assert {b["action"] for b in over["boreholes"]} == {"overwrite"}
    res = _post(client, admin_headers, text, path="/api/import/ags", on_duplicate="overwrite").json()
    assert res["updated"] == 2
    assert details.get_details("BH-01")["layers"][0]["description"] == "Lempung sangat lunak"
    # The owner of a log stays the person who submitted it.
    assert storage.get_report("BH-01")["SubmittedBy"] == "admin@example.com"


def test_general_user_cannot_overwrite_someone_elses_log_and_lab_cannot_import(client, admin_headers):
    _seed(client, admin_headers)
    text = _export()
    worker = login_headers(client, *make_user("worker@example.com", role="general"))
    plan = _post(client, worker, text, on_duplicate="overwrite").json()
    assert {b["action"] for b in plan["boreholes"]} == {"skip"}
    assert any("Only the person who submitted" in m["text"] for b in plan["boreholes"] for m in b["messages"])
    lab = login_headers(client, *make_user("lab@example.com", role="lab"))
    assert _post(client, lab, text).status_code == 403


def test_validation_messages():
    text = "\r\n".join([
        '"GROUP","PROJ"', '"HEADING","PROJ_ID","PROJ_NAME"', '"UNIT","",""', '"TYPE","ID","X"', '"DATA","P1","Proyek Uji"', "",
        '"GROUP","LOCA"', '"HEADING","LOCA_ID","LOCA_FDEP","LOCA_STAR"', '"UNIT","","ft",""', '"TYPE","ID","2DP","DT"',
        '"DATA","BH-A","32.81","2026-01-05"', '"DATA","BH-A","10","2026-01-05"', '"DATA","BH-B","5"', "",
        '"GROUP","GEOL"', '"HEADING","LOCA_ID","GEOL_TOP","GEOL_BASE","GEOL_DESC"', '"UNIT","","m","m",""', '"TYPE","ID","2DP","2DP","X"',
        '"DATA","BH-A","0","10","Pasir (SP)"', '"DATA","BH-Z","0","1","Orphan"', "",
        '"GROUP","XXXX"', '"HEADING","LOCA_ID"', '"UNIT",""', '"TYPE","ID"', '"DATA","BH-A"', "",
        'BAD,"LINE"',
    ]) + "\r\n"
    plan = ags_import.run(text)
    errors, warnings = _texts(plan["errors"]), _texts(plan["warnings"])
    assert any("same key fields" in e for e in errors)  # BH-A twice (rule 10a)
    assert any("DATA row has {n} fields" in e for e in errors)  # BH-B row is short (rule 4)
    assert any("instead of GROUP" in e for e in errors)  # rule 3
    assert any("not in LOCA" in w for w in warnings)  # orphan GEOL row (rule 10c)
    assert any("Group {group} is not imported" in w for w in warnings)  # XXXX
    assert any("converted from {unit}" in w for w in warnings)  # ft -> m
    bh = plan["boreholes"][0]
    assert bh["id"] == "BH-A" and bh["action"] == "create"
    assert float(bh["report"]["FinalDepth_m"]) == 10.0  # 32.81 ft
    assert bh["depth"]["layers"][0]["uscs"] == "SP"  # from "(SP)" in the description
    assert any("No contractor" in m["text"] for m in bh["messages"])


def test_not_an_ags_file(client, admin_headers):
    res = _post(client, admin_headers, "BoreholeID,ProjectName\nBH-1,X\n")
    assert res.status_code == 422 and "not an AGS4 file" in res.json()["detail"]


LAB_FILE = "\r\n".join([
    '"GROUP","PROJ"', '"HEADING","PROJ_ID","PROJ_NAME","PROJ_CONT"', '"UNIT","","",""', '"TYPE","ID","X","X"',
    '"DATA","P2","Gudang Pelabuhan","PT Contoh Geoteknik"', "",
    '"GROUP","LOCA"', '"HEADING","LOCA_ID","LOCA_TYPE","LOCA_FDEP","LOCA_STAR","LOCA_ENDD"', '"UNIT","","","m","yyyy-mm-dd","yyyy-mm-dd"',
    '"TYPE","ID","PA","2DP","DT","DT"', '"DATA","BH-L1","RC","20.00","2026-02-01","2026-02-03"', "",
    '"GROUP","ISPT"', '"HEADING","LOCA_ID","ISPT_TOP","ISPT_SEAT","ISPT_NVAL","ISPT_INC3","ISPT_INC4","ISPT_INC5","ISPT_INC6",'
    '"ISPT_PEN3","ISPT_PEN4","ISPT_PEN5","ISPT_PEN6"', '"UNIT","","m","","","","","","","mm","mm","mm","mm"',
    '"TYPE","ID","2DP","0DP","0DP","0DP","0DP","0DP","0DP","0DP","0DP","0DP","0DP"',
    '"DATA","BH-L1","3.00","4","22","5","5","6","6","75","75","75","75"', "",
    '"GROUP","SAMP"', '"HEADING","LOCA_ID","SAMP_TOP","SAMP_REF","SAMP_TYPE","SAMP_ID","SAMP_BASE"', '"UNIT","","m","","","","m"',
    '"TYPE","ID","2DP","X","PA","ID","2DP"', '"DATA","BH-L1","2.00","UDS-1","U","S1","2.50"', '"DATA","BH-L1","5.00","W-1","W","S2",""', "",
    '"GROUP","LLPL"', '"HEADING","LOCA_ID","SAMP_TOP","SAMP_REF","SAMP_TYPE","SAMP_ID","LLPL_LL","LLPL_PL","LLPL_PI","LLPL_METH"',
    '"UNIT","","m","","","","%","%","",""', '"TYPE","ID","2DP","X","PA","ID","0DP","XN","0DP","X"',
    '"DATA","BH-L1","2.00","UDS-1","U","S1","62","28","34","ASTM D4318"', "",
    '"GROUP","LNMC"', '"HEADING","LOCA_ID","SAMP_TOP","SAMP_REF","SAMP_TYPE","SAMP_ID","LNMC_MC"', '"UNIT","","m","","","","%"',
    '"TYPE","ID","2DP","X","PA","ID","X"', '"DATA","BH-L1","2.00","UDS-1","U","S1","41.5"', "",
    '"GROUP","GRAG"', '"HEADING","LOCA_ID","SAMP_TOP","SAMP_REF","SAMP_TYPE","SAMP_ID","GRAG_GRAV","GRAG_SAND","GRAG_SILT","GRAG_CLAY","GRAG_FINE"',
    '"UNIT","","m","","","","%","%","%","%","%"', '"TYPE","ID","2DP","X","PA","ID","1DP","1DP","1DP","1DP","1DP"',
    '"DATA","BH-L1","2.00","UDS-1","U","S1","0.0","12.5","45.0","42.5","87.5"', "",
    '"GROUP","LDEN"', '"HEADING","LOCA_ID","SAMP_TOP","SAMP_REF","SAMP_TYPE","SAMP_ID","LDEN_BDEN","LDEN_DDEN"', '"UNIT","","m","","","","g/cm3","Mg/m3"',
    '"TYPE","ID","2DP","X","PA","ID","2DP","2DP"', '"DATA","BH-L1","2.00","UDS-1","U","S1","1.75","1.24"', "",
    '"GROUP","GCHM"', '"HEADING","LOCA_ID","SAMP_TOP","SAMP_REF","SAMP_TYPE","SAMP_ID","GCHM_CODE","GCHM_METH","GCHM_TTYP","GCHM_RESL","GCHM_UNIT"',
    '"UNIT","","m","","","","","","","",""', '"TYPE","ID","2DP","X","PA","ID","PA","X","PA","U","PU"',
    '"DATA","BH-L1","5.00","W-1","W","S2","pH","","LAB","6.4",""', '"DATA","BH-L1","5.00","W-1","W","S2","SO4","","LAB","1650","mg/l"',
    '"DATA","BH-L1","5.00","W-1","W","S2","Cl","","LAB","320","mg/l"', "",
    '"GROUP","MCVG"', '"HEADING","LOCA_ID","SAMP_TOP"', '"UNIT","","m"', '"TYPE","ID","2DP"', '"DATA","BH-L1","2.00"',
]) + "\r\n"


def test_lab_groups_become_lab_results(client, admin_headers):
    plan = _post(client, admin_headers, LAB_FILE).json()
    bh = plan["boreholes"][0]
    assert bh["action"] == "create" and bh["lab"] == 5 and bh["spt"] == 1
    assert any(w["params"].get("group") == "MCVG" for w in plan["warnings"])
    assert not any(w["params"].get("group") == "LDEN" for w in plan["warnings"])  # g/cm3 is the same as Mg/m3
    res = _post(client, admin_headers, LAB_FILE, path="/api/import/ags").json()
    assert res["created"] == 1 and res["lab_created"] == 5, res
    spt = details.get_details("BH-L1")["spt"][0]
    assert (spt["seat"], spt["inc1"], spt["inc2"], spt["penetration_mm"]) == (4, 10, 12, None)  # 75 mm increments summed
    tests = {t["test_type"]: t for t in records.list_records("lab_tests")}
    assert tests["atterberg"]["results"] == {"ll": 62.0, "pl": 28.0, "pi": 34.0}
    assert tests["atterberg"]["standard"] == "ASTM D4318" and tests["atterberg"]["depth_base"] == 2.5
    assert tests["moisture"]["results"]["w"] == 41.5
    assert tests["grain_size"]["results"]["fines"] == 87.5
    assert tests["density"]["results"] == {"gamma_bulk": 17.17, "gamma_dry": 12.16}  # 1.75 and 1.24 Mg/m³ × 9.81
    chem = tests["chemistry"]["results"]
    assert chem["ph_water"] == 6.4 and chem["so4_water"] == 1650 and chem["cl_water"] == 320
    assert storage.get_report("BH-L1")["DrillingMethod"] == "Coring + SPT"  # LOCA_TYPE RC
    # A second import finds the results and skips them; with overwrite they are updated.
    again = _post(client, admin_headers, LAB_FILE).json()
    assert again["totals"]["lab_create"] == 0
    over = _post(client, admin_headers, LAB_FILE.replace('"62","28","34"', '"64","28","36"'), path="/api/import/ags",
                 on_duplicate="overwrite").json()
    assert over["lab_updated"] == 5
    tests = {t["test_type"]: t for t in records.list_records("lab_tests")}
    assert tests["atterberg"]["results"]["ll"] == 64.0 and len(records.list_records("lab_tests")) == 5


def test_lab_groups_can_be_left_out(client, admin_headers):
    plan = _post(client, admin_headers, LAB_FILE, include_lab=False).json()
    assert plan["boreholes"][0]["lab"] == 0
    assert {g["group"]: g["use"] for g in plan["groups"]}["LLPL"] == "Not imported"


def test_ags3_file():
    text = "\r\n".join([
        '"**PROJ"', '"*PROJ_ID","*PROJ_NAME"', '"<UNITS>","",""', '"P3","Jalan Tol Uji"', "",
        '"**HOLE"', '"*HOLE_ID","*HOLE_TYPE","*HOLE_FDEP","*HOLE_STAR"', '"<UNITS>","","","m","dd/mm/yyyy"',
        '"BH3","CP","15.0","04/03/2026"', "",
        '"**GEOL"', '"*HOLE_ID","*GEOL_TOP","*GEOL_BASE","*GEOL_DESC"', '"<UNITS>","","m","m",""',
        '"BH3","0.0","15.0","Lempung"', '"<CONT>","",""," kaku"', "",
        '"**WSTK"', '"*HOLE_ID","*WSTK_DEP","*WSTK_NMIN","*WSTK_POST"', '"<UNITS>","","m","min","m"', '"BH3","4.5","20","3.9"',
    ])
    plan = ags_import.run(text)
    assert plan["format"] == "AGS3"
    bh = plan["boreholes"][0]
    assert bh["id"] == "BH3" and bh["action"] == "create", bh["messages"]
    assert bh["report"]["StartDate"] == "2026-03-04" and bh["report"]["GroundwaterDepth_m"] == "3.9"
    assert bh["depth"]["layers"][0]["description"] == "Lempung kaku"
