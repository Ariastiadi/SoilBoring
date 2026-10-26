"""Laboratory quality controls after ISO/IEC 17025:2017: sample receipt and chain of custody (7.4),
calibration of the equipment used on the test date (6.4), review and authorisation of results
(7.8.1.1), nonconforming work and corrective action (7.10, 8.7). Expected values worked out by hand."""
from datetime import date

from backend.app import erp_lab
from backend.app.main import app
from backend.app.routers import erp_ops as erp_ops_router

from .conftest import login_headers, make_user

if not any(getattr(r, "path", "") == "/api/erp/ops/overview" for r in app.routes):
    app.include_router(erp_ops_router.router)


def _h(client, email, role):
    return login_headers(client, *make_user(email, role=role))


def _post(client, entity, data, headers, status=201):
    res = client.post(f"/api/records/{entity}", json=data, headers=headers)
    assert res.status_code == status, res.text
    return res.json()


def _put(client, entity, record, changes, headers, status=200):
    body = {k: v for k, v in record.items() if k not in ("id", "created_at", "created_by", "updated_at", "updated_by")}
    res = client.put(f"/api/records/{entity}/{record['id']}", json={**body, **changes}, headers=headers)
    assert res.status_code == status, res.text
    return res.json()


RECEIPT = {"received_on": "2026-10-01", "borehole_id": "BH-1", "sample_ref": "UDS-1", "depth_top": 2.0, "depth_base": 2.5,
           "sample_type": "uds", "condition": "as_specified", "storage_location": "Rak B-3"}


# --------------------------------------------------------------------------- #
# Sample receipt and chain of custody (7.4)
# --------------------------------------------------------------------------- #

def test_sample_receipt_deviation_custody_retention(client, admin_headers):
    lab = _h(client, "lab1@example.com", "lab")
    # A deviation must be described.
    assert client.post("/api/records/sample_receipts", json={**RECEIPT, "condition": "deviation"}, headers=lab).status_code == 422
    r = _post(client, "sample_receipts", {**RECEIPT, "condition": "deviation", "deviations": ["disturbed", "moisture_loss"],
                                          "custody": [{"date": "2026-10-03", "from_person": "Penerima", "to_person": "Teknisi A",
                                                       "purpose": "testing", "location": "Ruang uji"},
                                                      {"date": "2026-10-02", "from_person": "Sopir", "to_person": "Penerima",
                                                       "purpose": "storage", "location": "Rak B-3"}]}, lab)
    assert r["number"].startswith("SR-") and r["receipt_status"] == "on_hold"
    # Customer not consulted and no decision yet (7.4.3).
    assert [w["text"] for w in r["warnings"]] == ["Consult the customer before testing and record the outcome (ISO/IEC 17025 7.4.3)",
                                                  "Record the decision: test, test with a disclaimer in the report, do not test, or return"]
    # Custody rows sorted by date; the last row says who holds it now and where.
    assert [c["date"] for c in r["custody"]] == ["2026-10-02", "2026-10-03"]
    assert r["current_holder"] == "Teknisi A" and r["current_location"] == "Ruang uji"
    # The same sample cannot be received twice; custody before receipt and disposal without a method are refused.
    assert client.post("/api/records/sample_receipts", json={**RECEIPT, "sample_ref": "uds-1"}, headers=lab).status_code == 409
    other = {**RECEIPT, "sample_ref": "UDS-2"}
    assert client.post("/api/records/sample_receipts", json={**other, "custody": [{"date": "2026-09-30", "from_person": "A", "to_person": "B"}]},
                       headers=lab).status_code == 422
    assert client.post("/api/records/sample_receipts", json={**other, "disposed_on": "2026-10-20"}, headers=lab).status_code == 422
    assert client.post("/api/records/sample_receipts", json={**other, "decision": "test_with_disclaimer"}, headers=lab).status_code == 422
    # Retention ended (kept until 5 Oct 2026, today is later) and not disposed: flagged; once returned, the status says so.
    kept = _post(client, "sample_receipts", {**other, "retain_until": "2026-10-05"}, lab)
    assert any(w["text"].startswith("The retention period ended") for w in kept["warnings"])
    gone = _put(client, "sample_receipts", kept, {"disposed_on": "2026-10-10", "disposal_method": "returned"}, lab)
    assert gone["receipt_status"] == "returned" and gone["days_in_store"] == 9 and gone["warning_count"] == 0

    # The customer asks for testing with a disclaimer: the lab test is linked and carries the disclaimer.
    r = _put(client, "sample_receipts", r, {"customer_consulted_on": "2026-10-02", "decision": "test_with_disclaimer",
                                            "customer_instruction": "Tetap diuji"}, lab)
    assert r["receipt_status"] == "in_store" and r["warning_count"] == 0
    t = _post(client, "lab_tests", {"borehole_id": "bh-1", "sample_ref": "UDS-1", "depth_top": 2, "test_type": "moisture",
                                    "status": "requested"}, lab)
    assert t["receipt_id"] == r["id"] and t["received"] == "2026-10-01"
    assert "Sample disturbed" in t["report_disclaimer"] and "Moisture loss" in t["report_disclaimer"]
    # A sample the customer said not to test is flagged once testing starts.
    r = _put(client, "sample_receipts", r, {"decision": "do_not_test"}, lab)
    t = _put(client, "lab_tests", t, {"status": "testing"}, lab)
    assert "The sample receipt says this sample must not be tested" in [w["text"] for w in t["warnings"]]


# --------------------------------------------------------------------------- #
# Calibration of the equipment used (6.4, 6.5)
# --------------------------------------------------------------------------- #

def test_calibration_on_a_date():
    eq = {"id": "e1", "code": "LB-01", "name": "Timbangan", "calibration_months": 12, "last_calibration": "2025-06-01"}
    fail = {"equipment_id": "e1", "type": "calibration", "status": "completed", "completed_date": "2026-07-01", "calibration_result": "fail"}
    good = {"equipment_id": "e1", "type": "calibration", "status": "completed", "completed_date": "2026-07-10", "calibration_result": "adjusted"}
    # Calibrated 1 Jun 2025 + 12 months = due 1 Jun 2026.
    assert erp_lab.calibration_on(eq, [], date(2026, 6, 1))["status"] == "ok"
    late = erp_lab.calibration_on(eq, [], date(2026, 6, 2))
    assert late["status"] == "overdue" and late["due"] == "2026-06-01"
    assert erp_lab.calibration_on(eq, [fail], date(2026, 7, 5))["status"] == "failed"
    ok = erp_lab.calibration_on(eq, [fail, good], date(2026, 7, 15))
    assert ok["status"] == "ok" and ok["last"] == "2026-07-10" and ok["due"] == "2027-07-10"
    # Before the first calibration on record, and equipment that needs none.
    assert erp_lab.calibration_on(eq, [], date(2025, 5, 1))["status"] == "not_calibrated"
    assert erp_lab.calibration_on({**eq, "calibration_months": None}, [], date(2026, 6, 2))["status"] == "not_required"


def test_lab_test_equipment_check_and_failed_calibration(client, admin_headers):
    lab = _h(client, "lab2@example.com", "lab")
    eq = _post(client, "equipment", {"code": "LB-01", "name": "Timbangan digital", "category": "lab", "status": "available",
                                     "calibration_months": 12, "last_calibration": "2025-06-01"}, admin_headers)
    base = {"borehole_id": "BH-2", "depth_top": 3, "test_type": "moisture", "status": "testing", "equipment_used": [{"equipment_id": eq["id"]}]}
    # Tested 15 Jul 2026: the calibration ran out on 1 Jun 2026.
    t1 = _post(client, "lab_tests", {**base, "sample_ref": "D-1", "tested": "2026-07-15"}, lab)
    assert t1["calibration_check"][0]["status"] == "overdue" and t1["warnings"][0]["vars"]["due"] == "2026-06-01"
    _post(client, "lab_tests", {**base, "sample_ref": "D-2", "tested": "2026-03-01"}, lab)
    _post(client, "lab_tests", {**base, "sample_ref": "D-3", "tested": "2025-05-20"}, lab)  # before 1 Jun 2025: not counted
    # A failed calibration on 1 Jul 2026 lists the tests between the last good calibration (1 Jun 2025) and the failure:
    # D-2 (1 Mar 2026) only; D-3 is before 1 Jun 2025 and D-1 (15 Jul) after the failure.
    wo = _post(client, "work_orders", {"equipment_id": eq["id"], "type": "calibration", "status": "completed", "date": "2026-07-01",
                                       "completed_date": "2026-07-01", "calibration_result": "fail", "certificate_no": "K-9",
                                       "description": "Kalibrasi tahunan"}, admin_headers)
    hit = next(w for w in wo["warnings"] if "laboratory tests used this equipment" in w["text"])
    assert hit["vars"] == {"n": 1, "since": "2025-06-01"}
    # The test on 15 Jul is now on equipment whose last calibration failed.
    t1 = _put(client, "lab_tests", t1, {}, lab)
    assert t1["calibration_check"][0]["status"] == "failed"
    assert any("must not be used" in w["text"] for w in t1["warnings"])
    res = client.get("/api/erp/ops/lab/calibration?on=2026-07-15", headers=lab).json()
    assert [(r["code"], r["status"]) for r in res] == [("LB-01", "failed")]


# --------------------------------------------------------------------------- #
# Review and authorisation of results (7.8.1.1, 7.5)
# --------------------------------------------------------------------------- #

def test_results_authorisation_rules(client, admin_headers):
    tech = _h(client, "tech@example.com", "lab")
    head = _h(client, "head@example.com", "manager")
    staff = _h(client, "staff3@example.com", "general")
    body = {"borehole_id": "BH-3", "sample_ref": "UDS-3", "depth_top": 4, "test_type": "atterberg", "status": "done",
            "tested": "2026-10-20", "results": {"ll": 40, "pl": 20}}
    t = _post(client, "lab_tests", body, tech)
    assert t["result_status"] == "awaiting" and t["results_entered_by"] == "tech@example.com"
    assert [w["text"] for w in t["warnings"]] == ["Results are not yet reviewed and authorised (ISO/IEC 17025 7.8.1.1)"]
    # The person who entered the results cannot authorise them; someone else in the lab or a manager can.
    assert client.put(f"/api/records/lab_tests/{t['id']}", json={**body, "authorised": True}, headers=tech).status_code == 422
    t = _put(client, "lab_tests", t, {"authorised": True}, head)
    assert t["result_status"] == "authorised" and t["authorised_by"] == "head@example.com" and t["warning_count"] == 0
    assert t["authorised_at"] == date.today().isoformat()
    # Saved again unchanged: the authorisation stays.
    t = _put(client, "lab_tests", t, {}, tech)
    assert t["authorised"] and t["authorised_by"] == "head@example.com"
    # Results changed afterwards: authorisation cleared, to be authorised again.
    t = _put(client, "lab_tests", t, {"results": {"ll": 42, "pl": 20}}, tech)
    assert not t["authorised"] and t["authorised_by"] == "" and t["result_status"] == "awaiting"
    assert t["warnings"][0]["text"].startswith("The results changed after they were authorised")
    # Only done tests can be authorised; field staff cannot authorise.
    assert client.put(f"/api/records/lab_tests/{t['id']}", json={**body, "status": "testing", "authorised": True}, headers=head).status_code == 422
    own = _post(client, "lab_tests", {**body, "sample_ref": "UDS-4"}, staff)
    assert client.put(f"/api/records/lab_tests/{own['id']}", json={**body, "sample_ref": "UDS-4", "authorised": True},
                      headers=staff).status_code == 422
    # With "refuse" in the operations settings a test cannot be marked done without authorisation.
    _post(client, "ops_settings", {"lab_authorisation": "require"}, admin_headers)
    res = client.post("/api/records/lab_tests", json={**body, "sample_ref": "UDS-5"}, headers=tech)
    assert res.status_code == 422 and "7.8.1.1" in res.json()["detail"]
    assert client.post("/api/records/lab_tests", json={**body, "sample_ref": "UDS-5", "status": "testing"}, headers=tech).status_code == 201


# --------------------------------------------------------------------------- #
# Nonconforming work and corrective action (7.10, 8.7)
# --------------------------------------------------------------------------- #

def test_nonconformity_register_steps_and_closure(client, admin_headers):
    lab = _h(client, "lab4@example.com", "lab")
    head = _h(client, "head4@example.com", "manager")
    nc = _post(client, "nonconformities", {"date": "2026-10-10", "source": "equipment", "description": "Timbangan gagal kalibrasi",
                                           "work_halted": True}, lab)
    assert nc["number"] == "NC-2026-001" and nc["stage"] == "open"
    # Impact, decision, customer, halted work without resumption, corrective action decision: five open points.
    assert nc["warning_count"] == 5
    full = {"impact": "Dua uji kadar air diulang", "decision": "repeat", "customer_action": "notified", "correction": "Timbangan dikarantina",
            "resumption_authorised_by": "head4@example.com", "resumed_on": "2026-10-12", "corrective_action_needed": "yes",
            "root_cause": "Interval kalibrasi terlalu panjang", "corrective_action": "Interval 6 bulan dan cek antara bulanan",
            "action_due": "2026-10-20", "action_done_on": "2026-10-18"}
    nc = _put(client, "nonconformities", nc, full, lab)
    assert nc["stage"] == "verification" and [w["text"] for w in nc["warnings"]] == [
        "Review whether the corrective action was effective (8.7.1 d)"]
    # Closing before the effectiveness review is refused; then only a manager or administrator may close.
    res = client.put(f"/api/records/nonconformities/{nc['id']}", json={**full, "date": "2026-10-10", "source": "equipment",
                                                                         "description": "x", "closed_on": "2026-10-25"}, headers=head)
    assert res.status_code == 422 and res.json()["detail"].startswith("Before closing")
    done = {**full, "effective": "yes", "effectiveness_on": "2026-10-24", "closed_on": "2026-10-25"}
    assert client.put(f"/api/records/nonconformities/{nc['id']}", json={**done, "date": "2026-10-10", "source": "equipment", "description": "x"},
                      headers=lab).status_code == 422
    nc = _put(client, "nonconformities", nc, done, head)
    assert nc["stage"] == "closed" and nc["closed_by"] == "head4@example.com" and nc["warning_count"] == 0
    # Dates before the date found are refused.
    assert client.post("/api/records/nonconformities", json={"date": "2026-10-10", "source": "other", "description": "y",
                                                             "action_done_on": "2026-10-01"}, headers=lab).status_code == 422


def test_laboratory_overview(client, admin_headers):
    _post(client, "lab_tests", {"borehole_id": "BH-9", "sample_ref": "U-9", "depth_top": 1, "test_type": "moisture", "status": "done",
                                "tested": "2026-10-01", "results": {"w": 30}}, admin_headers)
    _post(client, "nonconformities", {"date": "2026-10-01", "source": "report", "description": "Salah ketik",
                                      "corrective_action_needed": "yes", "action_due": "2026-10-05"}, admin_headers)
    lab = client.get("/api/erp/ops/overview", headers=admin_headers).json()["laboratory"]
    assert lab["awaiting_authorisation"] == 1 and lab["nonconformities_open"] == 1 and lab["corrective_actions_overdue"] == 1
