"""Client reports: templates, versions in the approval flow, the integrity seal and the public
verify page, the read-only client role (no leaks), data checks and the dashboard distributions."""
import json
import re

import pytest

from backend.app import docstore, seals
from backend.app.main import app

from .conftest import login_headers, make_user, sample_report


def _h(client, email, role):
    return login_headers(client, *make_user(email, role=role))


def _post(client, entity, body, headers, status=201):
    res = client.post(f"/api/records/{entity}", json=body, headers=headers)
    assert res.status_code == status, res.text
    return res.json()


def _put(client, entity, record, changes, headers, status=200):
    body = {k: v for k, v in record.items() if not k.startswith("_") and k not in ("id", "created_at", "created_by", "updated_at", "updated_by")}
    res = client.put(f"/api/records/{entity}/{record['id']}", json={**body, **changes}, headers=headers)
    assert res.status_code == status, res.text
    return res.json()


def _step(client, report, action, headers, note="", status=200):
    res = client.post(f"/api/records/project_reports/{report['id']}/workflow", json={"action": action, "note": note}, headers=headers)
    assert res.status_code == status, res.text
    return res.json()


@pytest.fixture
def world(client, admin_headers):
    """Two clients with a project each, boreholes with depth data, a CPT and lab tests."""
    people = {
        "admin": admin_headers,
        "eng": _h(client, "eng@example.com", "manager"),
        "rev": _h(client, "rev@example.com", "manager"),
        "lab": _h(client, "tech@example.com", "lab"),
        "labhead": _h(client, "labhead@example.com", "lab"),
    }
    c1 = _post(client, "clients", {"name": "PT Contoh Pemilik", "type": "private"}, admin_headers)
    c2 = _post(client, "clients", {"name": "PT Lain Sekali", "type": "private"}, admin_headers)
    p1 = _post(client, "projects", {"code": "P-1", "name": "Gedung Contoh", "client_id": c1["id"], "status": "ongoing",
                                    "contract_value": 750000000, "location": "Bekasi"}, admin_headers)
    p2 = _post(client, "projects", {"code": "P-2", "name": "Gudang Lain", "client_id": c2["id"], "status": "ongoing",
                                    "contract_value": 990000000}, admin_headers)
    for bid, project in (("BH-01", p1), ("BH-02", p1), ("BX-09", p2)):
        res = client.post("/api/reports", json=sample_report(BoreholeID=bid, ProjectName=project["name"], FinalDepth_m="20"), headers=admin_headers)
        assert res.status_code == 201, res.text
    body = {"layers": [{"top": 0, "base": 6, "uscs": "CH", "description": "Lempung lunak"}, {"top": 6, "base": 20, "uscs": "SM"}],
            "spt": [{"depth": 2, "seat": 1, "inc1": 2, "inc2": 2}, {"depth": 8, "seat": 5, "inc1": 8, "inc2": 9},
                    {"depth": 14, "seat": 9, "inc1": 12, "inc2": 14}],
            "samples": [{"top": 2, "base": 2.5, "type": "U", "ref": "UDS-1"}], "core": []}
    for bid in ("BH-01", "BH-02", "BX-09"):
        assert client.put(f"/api/details/{bid}", json=body, headers=admin_headers).status_code == 200
    _post(client, "cpt", {"test_id": "S-01", "project_id": p1["id"], "date": "2026-10-01", "final_depth": 12,
                          "readings": [{"depth": 0.2, "qc": 5, "fs": 0.2}, {"depth": 0.4, "qc": 12, "fs": 0.5}]}, admin_headers)
    lab_body = {"borehole_id": "BH-01", "sample_ref": "UDS-1", "depth_top": 2, "test_type": "atterberg", "status": "done",
                "tested": "2026-10-20", "results": {"ll": 62, "pl": 27}, "project_id": p1["id"]}
    authorised = _post(client, "lab_tests", lab_body, people["lab"])
    authorised = _put(client, "lab_tests", authorised, {"authorised": True}, people["labhead"])
    pending = _post(client, "lab_tests", {**lab_body, "results": {"ll": 70, "pl": 30}, "depth_top": 2.2}, people["lab"])
    other = _post(client, "lab_tests", {**lab_body, "borehole_id": "BX-09", "project_id": p2["id"]}, people["lab"])
    other = _put(client, "lab_tests", other, {"authorised": True}, people["labhead"])
    return {"people": people, "c1": c1, "c2": c2, "p1": p1, "p2": p2, "authorised": authorised, "pending": pending, "other": other}


def _issue(client, world, project, **extra):
    p = world["people"]
    report = _post(client, "project_reports", {"project_id": project["id"], "title": "Laporan penyelidikan tanah",
                                               "date": "2026-10-25", "template": "building", **extra}, p["eng"])
    _step(client, report, "submit", p["eng"])
    _step(client, report, "review", p["rev"])
    return _step(client, report, "approve", p["admin"])


def test_template_outline_versions_and_seal(client, world):
    p = world["people"]
    t = client.get("/api/client-reports/templates", headers=p["eng"]).json()
    keys = {x["key"] for x in t["templates"]}
    assert {"building", "bridge", "road", "port", "dam", "railway", "industrial", "slope", "general"} <= keys
    building = next(x for x in t["templates"] if x["key"] == "building")
    titles = [s["title"] for s in building["sections"]]
    assert titles[:3] == ["Executive summary", "Project and site description", "Scope of work and standards"]
    assert titles.index("Bearing capacity") < titles.index("Settlement") < titles.index("Liquefaction potential") < titles.index("Pile design")
    assert titles[-1] == "Limitations"

    report = _post(client, "project_reports", {"project_id": world["p1"]["id"], "title": "Laporan", "date": "2026-10-25",
                                               "template": "building", "summary": "Ringkasan lama",
                                               "references": ["SNI 4153:2008", "SNI 8460:2017"]}, p["eng"])
    assert report["wf_status"] == "draft" and report["status"] == "draft" and report["version"] == 1
    assert [s["key"] for s in report["sections"]][0] == "summary" and report["sections"][0]["text"] == "Ringkasan lama"
    assert report["number"].startswith("RPT-2026-")
    # Unknown content sources are refused.
    bad = [{**report["sections"][0], "source": "drop table"}]
    _put(client, "project_reports", report, {"sections": bad}, p["eng"], status=422)

    content = client.get(f"/api/client-reports/{report['id']}/content", headers=p["eng"]).json()
    data = content["content"]["data"]
    assert [b["id"] for b in data["boreholes"]] == ["BH-01", "BH-02"]
    assert data["scope"]["boreholes"] == 2 and data["scope"]["metres"] == 40 and data["scope"]["spt"] == 6
    assert data["scope"]["undisturbed"] == 2 and data["scope"]["cpt"] == 1
    assert {(r["uscs"], r["count"], r["min"], r["max"]) for r in data["parameters"]["spt"]} == {("CH", 2, 4, 4), ("SM", 4, 17, 26)}
    assert [x["authorised"] for x in data["lab"]] == [True, False]
    assert any("not authorised yet" in w["text"] for w in content["warnings"])
    refs = content["content"]["document"]["references"]
    assert refs[0] == {"code": "SNI 4153:2008", "title": "Standard penetration test (SPT) method"}

    _step(client, report, "submit", p["eng"])
    _step(client, report, "review", p["rev"])
    v1 = _step(client, report, "approve", p["admin"])
    assert v1["status"] == "approved" and v1["prepared_by"] == "eng@example.com" and v1["reviewed_by"] == "rev@example.com"
    assert v1["approved_by"] == "admin@example.com" and re.fullmatch(r"[A-F0-9]{12}", v1["seal_code"])
    seal = seals.lookup(v1["seal_code"])
    assert seal["hash"] == v1["seal_hash"] and seals.digest(seal["sealed"]) == seal["hash"]
    # The hash is SHA-256 over the canonical JSON of what was issued.
    assert seal["hash"] == __import__("hashlib").sha256(json.dumps(seal["sealed"], sort_keys=True, separators=(",", ":"),
                                                                    ensure_ascii=False).encode()).hexdigest()

    # Public check: no sign-in, only the document facts.
    code = seals.format_code(v1["seal_code"])
    pub = client.get(f"/api/verify/{code}")
    assert pub.status_code == 200
    view = pub.json()
    assert view["status"] == "valid" and view["project"] == "Gedung Contoh" and view["number"] == f"{v1['number']} v1"
    assert view["document_type"] == "Soil investigation report"
    assert set(view) == {"document_type", "number", "title", "project", "issuer", "date", "status", "code", "hash", "revoked_on", "superseded_by"}
    assert "BH-01" not in json.dumps(view) and "ll" not in view
    assert client.get(f"/api/verify/{v1['seal_hash']}").json()["code"] == code
    assert client.get("/api/verify/ABCD-EF01-2345").status_code == 404
    assert client.get("/api/verify/not-a-code").status_code == 404

    # Issued content is frozen; later data changes show as "changed since issue".
    frozen = client.get(f"/api/client-reports/{v1['id']}/content", headers=p["eng"]).json()
    assert frozen["changed_since_issue"] is False and frozen["seal"]["intact"]
    client.post("/api/reports", json=sample_report(BoreholeID="BH-03", ProjectName="Gedung Contoh"), headers=p["admin"])
    frozen = client.get(f"/api/client-reports/{v1['id']}/content", headers=p["eng"]).json()
    assert frozen["changed_since_issue"] is True and len(frozen["content"]["data"]["boreholes"]) == 2

    # A new version keeps the number, needs a revision note, and supersedes v1 when approved.
    copy = {"project_id": v1["project_id"], "title": v1["title"], "date": "2026-10-28", "template": "building",
            "sections": v1["sections"], "number": v1["number"], "supersedes_id": v1["id"]}
    _post(client, "project_reports", copy, p["eng"], status=422)
    v2 = _post(client, "project_reports", {**copy, "revision_note": "BH-03 ditambahkan"}, p["eng"])
    assert v2["version"] == 2 and v2["number"] == v1["number"] and v2["family_id"] == v1["id"]
    # Only one open version at a time, and numbers stay unique across reports.
    _post(client, "project_reports", {**copy, "revision_note": "lagi"}, p["eng"], status=409)
    _post(client, "project_reports", {"project_id": v1["project_id"], "title": "Lain", "date": "2026-10-28", "number": v1["number"]},
          p["eng"], status=409)
    _step(client, v2, "submit", p["eng"])
    _step(client, v2, "review", p["rev"])
    v2 = _step(client, v2, "approve", p["admin"])
    old = client.get(f"/api/records/project_reports/{v1['id']}", headers=p["eng"]).json()
    assert old["status"] == "superseded" and old["superseded_by"] == v2["id"]
    view = client.get(f"/api/verify/{code}").json()
    assert view["status"] == "superseded" and view["superseded_by"] == seals.format_code(v2["seal_code"])
    # A superseded version cannot be reopened; the current one can, which withdraws its seal.
    _step(client, old, "reopen", p["admin"], note="salah", status=409)
    _step(client, v2, "reopen", p["admin"], note="Koreksi kedalaman")
    view2 = client.get(f"/api/verify/{v2['seal_code']}").json()
    assert view2["status"] == "revoked" and view2["revoked_on"]


def test_tampered_seal_is_reported_invalid(client, world):
    v1 = _issue(client, world, world["p1"])
    name = f"seal/{v1['seal_hash']}.json"
    seal = json.loads(docstore.read_text(name))
    seal["sealed"]["content"]["project"]["name"] = "Proyek lain"
    docstore.write_text(name, json.dumps(seal))
    assert client.get(f"/api/verify/{v1['seal_code']}").json()["status"] == "invalid"


def test_lab_result_sealed_when_authorised(client, world):
    p = world["people"]
    t = world["authorised"]
    assert re.fullmatch(r"[A-F0-9]{12}", t["seal_code"])
    view = client.get(f"/api/verify/{t['seal_code']}").json()
    assert view["document_type"] == "Laboratory test result" and view["status"] == "valid"
    assert view["number"] == "BH-01 / UDS-1" and view["title"] == "Atterberg limits" and view["project"] == "Gedung Contoh"
    # Saved again unchanged: same seal. Results changed: authorisation and seal withdrawn.
    same = _put(client, "lab_tests", t, {}, p["lab"])
    assert same["seal_code"] == t["seal_code"]
    changed = _put(client, "lab_tests", same, {"results": {"ll": 64, "pl": 27}}, p["lab"])
    assert not changed["authorised"]
    assert client.get(f"/api/verify/{t['seal_code']}").json()["status"] == "revoked"
    again = _put(client, "lab_tests", changed, {"authorised": True}, p["labhead"])
    assert again["seal_code"] != t["seal_code"]
    assert client.get(f"/api/verify/{t['seal_code']}").json()["status"] == "superseded"
    assert client.get(f"/api/verify/{again['seal_code']}").json()["status"] == "valid"


def test_old_reports_stay_valid(client, world):
    """A report saved before templates and the flow: legacy fields print as sections."""
    p = world["people"]
    from backend.app import records

    legacy = {"id": "a1b2c3d4e5f60718", "number": "RPT-2025-007", "project_id": world["p1"]["id"], "title": "Lama",
              "date": "2025-05-01", "status": "approved", "summary": "Ringkas", "recommendations": "Pondasi tiang"}
    docstore.write_text(records._doc("project_reports", legacy["id"]), json.dumps(legacy))
    got = client.get(f"/api/records/project_reports/{legacy['id']}", headers=p["eng"]).json()
    assert got["number"] == "RPT-2025-007"
    content = client.get(f"/api/client-reports/{legacy['id']}/content", headers=p["eng"]).json()["content"]
    keys = [s["key"] for s in content["document"]["sections"]]
    assert keys[0] == "summary" and keys[-1] == "recommendations"
    saved = _put(client, "project_reports", got, {}, p["eng"])
    assert saved["wf_status"] == "draft" and saved["version"] == 1 and saved["status"] == "draft"


# --------------------------------------------------------------------------- #
# Client role
# --------------------------------------------------------------------------- #

def _client_user(client, admin_headers, world, email="klien@example.com", links=None):
    res = client.post("/api/users", json={"email": email, "password": "correct-horse-1", "role": "client",
                                          "client_ids": links if links is not None else [world["c1"]["id"]]}, headers=admin_headers)
    assert res.status_code == 201, res.text
    return login_headers(client, email, "correct-horse-1")


PUBLIC = {"/api/auth/login", "/api/auth/setup", "/api/auth/signup", "/api/auth/reset-with-code", "/api/auth/forgot",
          "/api/auth/reset", "/api/config", "/api/health", "/api/verify/{token}"}
CLIENT_OK = {"/api/auth/me", "/api/auth/change-password", "/api/auth/2fa/setup", "/api/auth/2fa/enable", "/api/auth/2fa/disable",
             "/api/auth/recovery-codes", "/api/client/overview", "/api/client/reports/{report_id}",
             "/api/client/boreholes/{borehole_id}", "/api/client/projects/{project_id}/lab"}


def test_client_role_is_denied_everywhere_else(client, admin_headers, world):
    """Every signed-in endpoint outside the client portal answers 403 to a client account,
    including endpoints added later (default deny in get_current_user)."""
    ch = _client_user(client, admin_headers, world)
    checked = 0
    for route_path, operations in app.openapi()["paths"].items():
        if not route_path.startswith("/api") or route_path in PUBLIC or route_path in CLIENT_OK:
            continue
        path = re.sub(r"\{[^}]+\}", "a1b2c3d4e5f60718", route_path)
        for method in operations:
            res = client.request(method.upper(), path, headers=ch, json={})
            assert res.status_code == 403, f"{method} {route_path}: {res.status_code}"
            checked += 1
    assert checked > 60
    # Typical data paths, spelled out.
    for path in ("/api/records/projects", "/api/records/project_reports", "/api/records/invoices", "/api/reports",
                 "/api/depth-overview", "/api/details/BH-01", "/api/dashboard", "/api/summaries?period=weekly",
                 "/api/schemas", "/api/approvals", "/api/samples", "/api/users/directory", "/api/export/ags?project=x",
                 "/api/files/a1b2c3d4e5f60718a1b2c3d4", "/api/data-checks", f"/api/client-reports/{world['p1']['id']}/content",
                 "/api/erp/commercial/overview", "/api/audit"):
        assert client.get(path, headers=ch).status_code == 403, path
    assert client.post("/api/ai/prompt", json={"question": "x", "max_chars": 1000}, headers=ch).status_code == 403
    assert client.get("/api/auth/me", headers=ch).json()["role"] == "client"


def test_client_sees_only_own_approved_reports_and_logs(client, admin_headers, world):
    mine = _issue(client, world, world["p1"])
    theirs = _issue(client, world, world["p2"])
    draft = _post(client, "project_reports", {"project_id": world["p1"]["id"], "title": "Draf", "date": "2026-10-26"}, world["people"]["eng"])
    ch = _client_user(client, admin_headers, world)
    ov = client.get("/api/client/overview", headers=ch)
    assert ov.status_code == 200
    ov = ov.json()
    assert [c["name"] for c in ov["clients"]] == ["PT Contoh Pemilik"]
    assert [p["code"] for p in ov["projects"]] == ["P-1"]
    proj = ov["projects"][0]
    assert [r["id"] for r in proj["reports"]] == [mine["id"]]
    assert [b["id"] for b in proj["boreholes"]] == ["BH-01", "BH-02"] and proj["lab_results"] == 1
    text = json.dumps(ov)
    for secret in ("contract_value", "750000000", "Gudang Lain", "BX-09", "price", "invoice", "eng@example.com"):
        assert secret not in text, secret

    rep = client.get(f"/api/client/reports/{mine['id']}", headers=ch)
    assert rep.status_code == 200 and rep.json()["seal"]["status"] == "valid"
    assert "contract_value" not in json.dumps(rep.json())
    assert client.get(f"/api/client/reports/{theirs['id']}", headers=ch).status_code == 404
    assert client.get(f"/api/client/reports/{draft['id']}", headers=ch).status_code == 404
    assert client.get("/api/client/reports/zz", headers=ch).status_code == 404

    log = client.get("/api/client/boreholes/BH-01", headers=ch)
    assert log.status_code == 200 and log.json()["details"]["layers"][0]["uscs"] == "CH"
    assert "SubmittedBy" not in log.json()["report"] and log.json()["details"]["photos"] == []
    assert client.get("/api/client/boreholes/BX-09", headers=ch).status_code == 404
    assert client.get("/api/client/boreholes/NOPE", headers=ch).status_code == 404

    lab = client.get(f"/api/client/projects/{world['p1']['id']}/lab", headers=ch).json()
    assert [x["id"] for x in lab] == [world["authorised"]["id"]]  # the unauthorised result is not shown
    assert client.get(f"/api/client/projects/{world['p2']['id']}/lab", headers=ch).status_code == 404

    # Staff cannot use the portal endpoints; a client with no links sees nothing.
    assert client.get("/api/client/overview", headers=admin_headers).status_code == 403
    nobody = _client_user(client, admin_headers, world, email="kosong@example.com", links=[])
    assert client.get("/api/client/overview", headers=nobody).json()["projects"] == []
    assert client.get(f"/api/client/reports/{mine['id']}", headers=nobody).status_code == 404


def test_client_accounts_admin(client, admin_headers, world):
    ch = _client_user(client, admin_headers, world, links=[])
    users = {u["email"]: u for u in client.get("/api/users", headers=admin_headers).json()}
    assert users["klien@example.com"]["role"] == "client" and users["klien@example.com"]["client_ids"] == []
    res = client.put("/api/users/klien@example.com/clients", json={"client_ids": [world["c2"]["id"]]}, headers=admin_headers)
    assert res.status_code == 200 and res.json()["client_ids"] == [world["c2"]["id"]]
    assert [p["code"] for p in client.get("/api/client/overview", headers=ch).json()["projects"]] == ["P-2"]
    assert client.put("/api/users/klien@example.com/clients", json={"client_ids": ["0000000000000000"]}, headers=admin_headers).status_code == 422
    assert client.put("/api/users/eng@example.com/clients", json={"client_ids": []}, headers=admin_headers).status_code == 400
    assert client.put("/api/users/klien@example.com/clients", json={"client_ids": []}, headers=world["people"]["eng"]).status_code == 403
    # Client accounts are not offered as staff (engineer, reviewer ...).
    assert "klien@example.com" not in [u["email"] for u in client.get("/api/users/directory", headers=admin_headers).json()]
    # An account request can be approved as a client account.
    assert client.post("/api/auth/signup", json={"email": "owner@example.com", "name": "Pemilik", "department": "other",
                                                 "password": "correct-horse-1"}).status_code == 202
    ok = client.post("/api/users/requests/owner@example.com/approve", json={"role": "client", "client_ids": [world["c1"]["id"]]}, headers=admin_headers)
    assert ok.status_code == 201, ok.text
    oh = login_headers(client, "owner@example.com", "correct-horse-1")
    assert [p["code"] for p in client.get("/api/client/overview", headers=oh).json()["projects"]] == ["P-1"]


# --------------------------------------------------------------------------- #
# Data checks and dashboard
# --------------------------------------------------------------------------- #

def test_data_checks(client, admin_headers, world):
    p = world["people"]
    client.post("/api/reports", json=sample_report(BoreholeID="BH 1", ProjectName="Gedung Contoh", Latitude="", Longitude="",
                                                   FinalDepth_m="10"), headers=admin_headers)
    body = {"layers": [{"top": 0.5, "base": 3, "uscs": "CL"}, {"top": 4, "base": 12, "uscs": "SM"}],
            "spt": [{"depth": 5, "seat": 10, "inc1": 3, "inc2": 4}, {"depth": 6.5, "seat": 20, "inc1": 30, "inc2": 40},
                    {"depth": 8, "seat": 40, "inc1": 60, "inc2": 55}],
            "samples": [], "core": []}
    assert client.put("/api/details/BH 1", json=body, headers=admin_headers).status_code == 200
    _post(client, "lab_tests", {"borehole_id": "BH-77", "sample_ref": "UDS-9", "depth_top": 1, "test_type": "atterberg",
                                "status": "received"}, p["lab"])
    _post(client, "cpt", {"test_id": "S-EMPTY", "date": "2026-10-01"}, admin_headers)
    assert client.get("/api/data-checks", headers=p["lab"]).status_code == 403
    res = client.get("/api/data-checks?days=-1", headers=p["eng"])
    assert res.status_code == 422
    out = {c["key"]: c for c in client.get("/api/data-checks?days=0", headers=p["eng"]).json()["checks"]}
    texts = {k: [(i["text"], i["vars"]) for i in c["items"]] for k, c in out.items()}
    assert ("{ids} may be the same borehole", {"ids": "BH 1, BH-01"}) in texts["duplicate_ids"]
    strata = [t for t, v in texts["strata"] if v.get("id") == "BH 1"]
    assert strata == ["{id}: no stratum from 0 to {top} m", "{id}: gap between {a} m and {b} m"]
    assert ("{id}: {what} reach {depth} m, the final depth is {final} m",
            {"id": "BH 1", "what": "Strata", "depth": "12", "final": "10"}) in texts["too_deep"]
    spt = [(t, v) for t, v in texts["spt"] if v.get("id") == "BH 1"]
    assert ("{id} at {depth} m: N = {n} without a recorded refusal", {"id": "BH 1", "depth": "8", "n": 115}) in spt
    assert any(t.startswith("{id}: N jumps") and v["a"] == 7 and v["b"] == 70 for t, v in spt)
    assert ("{id}: no coordinates", {"id": "BH 1"}) in texts["location"]
    assert ("{id}: no ground elevation", {"id": "BH-01"}) in texts["location"]
    assert any(v.get("id") == "BH-77" for _, v in texts["orphans"])
    # The pending test of the fixture is done and not authorised (0 days allowed).
    assert [i["target"]["id"] for i in out["unauthorised"]["items"]] == [world["pending"]["id"]]
    assert [i["target"]["label"] for i in out["cpt_readings"]["items"]] == ["S-EMPTY"]
    assert out["unauthorised"]["items"][0]["target"]["kind"] == "lab_test"


def test_dashboard_distributions(client, admin_headers, world):
    client.post("/api/reports", json=sample_report(BoreholeID="BH-50", FinalDepth_m="55", GroundwaterEncountered=False,
                                                   GroundwaterDepth_m=""), headers=admin_headers)
    d = client.get("/api/dashboard", headers=admin_headers).json()
    assert d["depth_breakdown"] == [["0–10 m", 0], ["10–20 m", 0], ["20–30 m", 3], ["30–50 m", 0], ["≥ 50 m", 1]]
    assert d["groundwater_breakdown"] == {"encountered": 3, "not_encountered": 1, "not_recorded": 0}
    assert d["groundwater_rate_pct"] == 75.0
    assert d["strata_uscs_m"] == {"SM": 42.0, "CH": 18.0}
    assert d["method_breakdown"] and d["uscs_breakdown"]
