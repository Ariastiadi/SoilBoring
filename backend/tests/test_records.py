"""Business records: clients, projects, quotations, contracts, field work, lab, invoices."""
import base64

from .conftest import login_headers, make_user


def _client(client, headers, name="PT Waskita Contoh", **extra):
    res = client.post("/api/records/clients", json={"name": name, "type": "bumn", **extra}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _project(client, headers, client_id, code="P-01", **extra):
    body = {"code": code, "name": "Tol Contoh", "client_id": client_id, "status": "tender", "contract_value": 500_000_000, **extra}
    res = client.post("/api/records/projects", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def test_schemas_and_permissions_per_role(client, admin_headers):
    make_user("lab@example.com", role="lab")
    make_user("money@example.com", role="finance")
    lab = login_headers(client, "lab@example.com", "correct-horse-1")
    schemas = client.get("/api/schemas", headers=lab).json()
    assert schemas["lab_tests"]["can_create"] and not schemas["invoices"]["can_read"]
    assert not schemas["clients"]["can_create"]
    assert client.post("/api/records/clients", json={"name": "X", "type": "other"}, headers=lab).status_code == 403
    assert client.get("/api/records/invoices", headers=lab).status_code == 403
    finance = login_headers(client, "money@example.com", "correct-horse-1")
    assert client.get("/api/records/invoices", headers=finance).status_code == 200
    assert client.get("/api/records/unknown", headers=admin_headers).status_code == 404


def test_client_project_crud_references_and_private_values(client, admin_headers, general_headers):
    c = _client(client, admin_headers)
    p = _project(client, admin_headers, c["id"])
    assert p["status"] == "tender" and p["created_by"] == "admin@example.com"
    # Field staff see the project but not its contract value, and cannot change it.
    seen = client.get(f"/api/records/projects/{p['id']}", headers=general_headers).json()
    assert "contract_value" not in seen and seen["_can_edit"] is False
    assert client.put(f"/api/records/projects/{p['id']}", json=seen, headers=general_headers).status_code == 403
    # Duplicate code, unknown client, bad option.
    assert client.post("/api/records/projects", json={"code": "p-01", "name": "B", "client_id": c["id"], "status": "tender"}, headers=admin_headers).status_code == 409
    assert client.post("/api/records/projects", json={"code": "P-02", "name": "B", "client_id": "0" * 16, "status": "tender"}, headers=admin_headers).status_code == 422
    assert client.post("/api/records/projects", json={"code": "P-03", "name": "B", "client_id": c["id"], "status": "zzz"}, headers=admin_headers).status_code == 422
    # A client with projects cannot be deleted.
    res = client.delete(f"/api/records/clients/{c['id']}", headers=admin_headers)
    assert res.status_code == 409 and "Project" in res.json()["detail"]
    # Edit conflict.
    stale = dict(p, expected_updated_at="2000-01-01T00:00:00+00:00", status="ongoing")
    assert client.put(f"/api/records/projects/{p['id']}", json=stale, headers=admin_headers).status_code == 409
    fresh = dict(p, expected_updated_at=p["updated_at"], status="ongoing")
    assert client.put(f"/api/records/projects/{p['id']}", json=fresh, headers=admin_headers).json()["status"] == "ongoing"
    assert client.delete(f"/api/records/projects/{p['id']}", headers=admin_headers).status_code == 200
    assert client.delete(f"/api/records/clients/{c['id']}", headers=admin_headers).status_code == 200
    events = client.get("/api/audit", headers=admin_headers).json()
    assert any(e["action"] == "projects.updated" for e in events)


def test_quote_and_invoice_totals_and_numbers(client, admin_headers):
    c = _client(client, admin_headers)
    p = _project(client, admin_headers, c["id"])
    items = [{"description": "Pengeboran", "unit": "m", "qty": 30, "unit_price": 450_000},
             {"description": "SPT", "unit": "titik", "qty": 15, "unit_price": 150_000}]
    q = client.post("/api/records/quotes", json={"project_id": p["id"], "date": "2026-10-01", "status": "draft",
                                                 "items": items, "discount_pct": 10, "tax_pct": 11}, headers=admin_headers).json()
    assert q["number"] == "QUO-2026-001"
    assert q["subtotal"] == round((30 * 450_000 + 15 * 150_000) * 0.9)
    assert q["tax"] == round(q["subtotal"] * 0.11) and q["total"] == q["subtotal"] + q["tax"]
    q2 = client.post("/api/records/quotes", json={"project_id": p["id"], "date": "2026-11-01", "status": "draft"}, headers=admin_headers).json()
    assert q2["number"] == "QUO-2026-002"
    inv = client.post("/api/records/invoices", json={
        "project_id": p["id"], "date": "2026-10-05", "due_date": "2026-10-20", "status": "sent",
        "items": [{"description": "Termin 1", "qty": 1, "unit_price": 10_000_000}], "tax_pct": 11, "pph_pct": 2,
        "payments": [{"date": "2026-10-10", "amount": 5_000_000}]}, headers=admin_headers).json()
    assert inv["number"] == "INV-2026-001"
    assert inv["total"] == 11_100_000 and inv["pph"] == 200_000
    assert inv["paid"] == 5_000_000 and inv["outstanding"] == 11_100_000 - 200_000 - 5_000_000
    assert inv["payment_status"] == "partial"
    inv["payments"].append({"date": "2026-10-15", "amount": 5_900_000})
    inv["expected_updated_at"] = inv["updated_at"]
    paid = client.put(f"/api/records/invoices/{inv['id']}", json=inv, headers=admin_headers).json()
    assert paid["outstanding"] == 0 and paid["payment_status"] == "paid"
    # Totals cannot be set from outside.
    forged = client.post("/api/records/invoices", json={"project_id": p["id"], "date": "2026-10-05", "status": "draft",
                                                         "total": 1, "outstanding": 0}, headers=admin_headers).json()
    assert forged["total"] == 0 and forged["payment_status"] == "unpaid"


def test_field_staff_own_records_and_lab_results(client, admin_headers, general_headers):
    make_user("other@example.com", role="general")
    other = login_headers(client, "other@example.com", "correct-horse-1")
    cpt = client.post("/api/records/cpt", json={"test_id": "S-01", "date": "2026-10-01",
                                                "readings": [{"depth": 0.2, "qc": 5, "fs": 0.2}, {"depth": "0,4", "qc": 7}]},
                      headers=general_headers)
    assert cpt.status_code == 201, cpt.text
    body = cpt.json()
    assert body["readings"][1]["depth"] == 0.4
    assert client.put(f"/api/records/cpt/{body['id']}", json=body, headers=general_headers).status_code == 200
    assert client.put(f"/api/records/cpt/{body['id']}", json=body, headers=other).status_code == 403
    # Method must belong to the discipline.
    bad = client.post("/api/records/field_activities", json={"code": "L1", "type": "geology", "method": "masw", "date": "2026-10-01"}, headers=general_headers)
    assert bad.status_code == 422
    ok = client.post("/api/records/field_activities", json={"code": "L1", "type": "geophysics", "method": "masw", "date": "2026-10-01"}, headers=general_headers)
    assert ok.status_code == 201
    lab = client.post("/api/records/lab_tests", json={"borehole_id": "BH-1", "sample_ref": "UDS-1", "depth_top": 2, "test_type": "atterberg",
                                                      "status": "done", "results": {"ll": 55, "pl": 25, "junk": 1}}, headers=admin_headers).json()
    assert lab["results"] == {"ll": 55.0, "pl": 25.0, "pi": 30.0}
    assert client.post("/api/records/lab_tests", json={"borehole_id": "BH-1", "sample_ref": "U", "depth_top": 2, "test_type": "grain_size",
                                                       "results": {"sand": 140}}, headers=admin_headers).status_code == 422


def test_files_attach_download_and_cleanup(client, admin_headers):
    pdf = b"%PDF-1.4 test document"
    res = client.post("/api/files", json={"name": "Kontrak ä.pdf", "content_type": "application/pdf",
                                          "data_base64": base64.b64encode(pdf).decode()}, headers=admin_headers)
    assert res.status_code == 201, res.text
    meta = res.json()
    assert client.post("/api/files", json={"name": "x.pdf", "content_type": "application/pdf",
                                           "data_base64": base64.b64encode(b"not a pdf").decode()}, headers=admin_headers).status_code == 422
    assert client.post("/api/files", json={"name": "x.exe", "content_type": "application/x-msdownload",
                                           "data_base64": base64.b64encode(b"MZ").decode()}, headers=admin_headers).status_code == 422
    c = _client(client, admin_headers)
    p = _project(client, admin_headers, c["id"])
    contract = client.post("/api/records/contracts", json={"number": "K-1", "project_id": p["id"], "date": "2026-10-01", "value": 100,
                                                           "status": "signed", "files": [{"id": meta["id"]}],
                                                           "terms": [{"name": "DP", "percent": 30}]}, headers=admin_headers).json()
    assert contract["files"][0]["name"] == "Kontrak ä.pdf"
    got = client.get(f"/api/files/{meta['id']}", headers=admin_headers)
    assert got.status_code == 200 and got.content == pdf and "attachment" in got.headers["content-disposition"]
    contract["files"] = []
    client.put(f"/api/records/contracts/{contract['id']}", json=contract, headers=admin_headers)
    assert client.get(f"/api/files/{meta['id']}", headers=admin_headers).status_code == 404


def test_settings_is_a_single_record(client, admin_headers, general_headers):
    first = client.post("/api/records/settings", json={"company_name": "PT Contoh"}, headers=admin_headers).json()
    second = client.post("/api/records/settings", json={"company_name": "PT Contoh Baru"}, headers=admin_headers).json()
    assert first["id"] == second["id"]
    assert len(client.get("/api/records/settings", headers=general_headers).json()) == 1
    assert client.post("/api/records/settings", json={"company_name": "X"}, headers=general_headers).status_code == 403


def test_new_roles_can_be_created(client, admin_headers):
    for role in ("manager", "lab", "finance"):
        res = client.post("/api/users", json={"email": f"{role}@example.com", "password": "correct-horse-1", "role": role}, headers=admin_headers)
        assert res.status_code == 201 and res.json()["role"] == role


def test_analyses_run_from_borehole_and_lab_data(client, admin_headers):
    from .conftest import sample_report
    client.post("/api/reports", json=sample_report(BoreholeID="BH-A", FinalDepth_m="12", GroundwaterDepth_m="1.0"), headers=admin_headers)
    client.put("/api/details/BH-A", json={
        "layers": [{"top": 0, "base": 4, "uscs": "CL"}, {"top": 4, "base": 12, "uscs": "SP"}],
        "spt": [{"depth": d, "seat": 2, "inc1": n // 2, "inc2": n - n // 2} for d, n in [(2, 4), (4, 6), (6, 8), (8, 10), (10, 25), (12, 40)]],
    }, headers=admin_headers)
    client.post("/api/records/lab_tests", json={"borehole_id": "BH-A", "sample_ref": "D-1", "depth_top": 6, "test_type": "grain_size",
                                                "status": "done", "results": {"sand": 95, "silt": 3, "clay": 2}}, headers=admin_headers)
    pile = client.post("/api/analyses/run", json={"type": "pile", "inputs": {"borehole_id": "BH-A", "diameter": 0.4, "length": 10, "pile_type": "bored"}}, headers=admin_headers)
    assert pile.status_code == 200, pile.text
    assert pile.json()["Qallow"] > 0 and pile.json()["profile"]
    liq = client.post("/api/analyses/run", json={"type": "liquefaction", "inputs": {"borehole_id": "BH-A", "amax_g": 0.35, "magnitude": 7.5}}, headers=admin_headers).json()
    assert liq["details"]["n_liquefiable"] >= 1 and "liquefiable" in liq["summary"]
    rows = {r["depth"]: r for r in liq["rows"]}
    assert rows[2.0]["status"] != "liquefiable"  # clay layer
    bearing = client.post("/api/analyses/run", json={"type": "bearing", "inputs": {"B": 2, "L": 2, "Df": 1, "c": 10, "phi_deg": 28, "gamma": 18}}, headers=admin_headers).json()
    assert bearing["q_allow"] > 0 and bearing["summary"].startswith("q_allow")
    assert client.post("/api/analyses/run", json={"type": "pile", "inputs": {"borehole_id": "NOPE", "diameter": 0.4, "length": 5}}, headers=admin_headers).status_code == 422
    saved = client.post("/api/records/analyses", json={"title": "Daya dukung", "type": "bearing",
                                                       "inputs": {"B": 2, "L": 2, "Df": 1, "c": 10, "phi_deg": 28, "gamma": 18}}, headers=admin_headers)
    assert saved.status_code == 201, saved.text
    assert saved.json()["results"]["q_allow"] == bearing["q_allow"] and saved.json()["summary"] == bearing["summary"]
