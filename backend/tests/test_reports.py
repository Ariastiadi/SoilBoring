import pytest
import threading

from backend.app import storage

from .conftest import sample_report


def test_all_data_endpoints_require_auth(client):
    for method, url in [
        ("get", "/api/reports"),
        ("get", "/api/dashboard"),
        ("get", "/api/summaries?period=weekly"),
        ("post", "/api/ai/analyze"),
    ]:
        assert getattr(client, method)(url).status_code == 401, url


def test_create_list_and_submitted_by(client, admin_headers):
    res = client.post("/api/reports", json=sample_report(SubmittedBy="spoofed@evil.com"), headers=admin_headers)
    assert res.status_code == 201
    rows = client.get("/api/reports", headers=admin_headers).json()
    assert len(rows) == 1
    assert rows[0]["SubmittedBy"] == "admin@example.com"
    assert rows[0]["GroundwaterEncountered"] == "True"


def test_duplicate_borehole_id_is_rejected_case_insensitively(client, admin_headers):
    assert client.post("/api/reports", json=sample_report(), headers=admin_headers).status_code == 201
    dup = client.post("/api/reports", json=sample_report(BoreholeID="bh-001"), headers=admin_headers)
    assert dup.status_code == 409


def test_invalid_payloads_are_rejected(client, admin_headers):
    cases = [
        {"Latitude": "95"},
        {"Longitude": "abc"},
        {"FinalDepth_m": "-3"},
        {"StartDate": "10/03/2026"},
        {"StartDate": "2026-04-01", "EndDate": "2026-03-01"},
        {"BoreholeID": "   "},
        {"GroundwaterEncountered": "maybe"},
    ]
    for override in cases:
        res = client.post("/api/reports", json=sample_report(**override), headers=admin_headers)
        assert res.status_code == 422, override
    assert client.get("/api/reports", headers=admin_headers).json() == []


def test_edit_whitelists_fields(client, admin_headers):
    client.post("/api/reports", json=sample_report(), headers=admin_headers)
    res = client.put("/api/reports/BH-001", headers=admin_headers,
                     json={"Remarks": "updated", "BoreholeID": "HACK", "SubmittedBy": "x@y.z", "Unknown": "1"})
    assert res.status_code == 200
    row = client.get("/api/reports", headers=admin_headers).json()[0]
    assert row["Remarks"] == "updated"
    assert row["BoreholeID"] == "BH-001"
    assert row["SubmittedBy"] == "admin@example.com"


def test_edit_rejects_date_inversion_against_stored_value(client, admin_headers):
    client.post("/api/reports", json=sample_report(), headers=admin_headers)
    res = client.put("/api/reports/BH-001", headers=admin_headers, json={"EndDate": "2026-03-01"})
    assert res.status_code == 422


def test_general_user_can_only_touch_own_logs(client, admin_headers, general_headers):
    client.post("/api/reports", json=sample_report(BoreholeID="ADMIN-1"), headers=admin_headers)
    client.post("/api/reports", json=sample_report(BoreholeID="MINE-1"), headers=general_headers)

    assert client.put("/api/reports/ADMIN-1", json={"Remarks": "x"}, headers=general_headers).status_code == 403
    assert client.delete("/api/reports/ADMIN-1", headers=general_headers).status_code == 403
    assert client.put("/api/reports/MINE-1", json={"Remarks": "ok"}, headers=general_headers).status_code == 200
    assert client.delete("/api/reports/MINE-1", headers=general_headers).status_code == 200
    assert client.delete("/api/reports/ADMIN-1", headers=admin_headers).status_code == 200


def test_missing_report_returns_404(client, admin_headers):
    assert client.delete("/api/reports/NOPE", headers=admin_headers).status_code == 404
    assert client.put("/api/reports/NOPE", json={"Remarks": "x"}, headers=admin_headers).status_code == 404


def test_concurrent_saves_do_not_lose_rows(client):
    def worker(i):
        storage.save_report(sample_report(BoreholeID=f"BH-{i:03d}"), submitted_by="t@example.com")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(storage.load_reports()) == 25


def test_unknown_csv_columns_return_conflict_instead_of_crashing(client, admin_headers):
    storage.docstore.write_text(storage.DOC, "Foo,Bar\n1,2\n")
    assert client.get("/api/reports", headers=admin_headers).status_code == 409


def test_older_csv_with_fewer_columns_is_migrated_on_write(client, admin_headers):
    storage.docstore.write_text(storage.DOC, "BoreholeID,ProjectName\nBH-OLD,Legacy\n")
    assert client.post("/api/reports", json=sample_report(), headers=admin_headers).status_code == 201
    ids = [r["BoreholeID"] for r in client.get("/api/reports", headers=admin_headers).json()]
    assert ids == ["BH-OLD", "BH-001"]


@pytest.mark.skipif(storage.docstore.USE_DATABASE, reason="file mode only")
def test_file_permissions_data_readable_secrets_private(client, admin_headers):
    import os
    import stat

    from backend.app import auth

    client.post("/api/reports", json=sample_report(), headers=admin_headers)
    assert stat.S_IMODE(os.stat(storage.FILE).st_mode) & 0o044, "reports.csv should stay readable for host backups"
    assert stat.S_IMODE(os.stat(auth.USER_FILE).st_mode) == 0o600
