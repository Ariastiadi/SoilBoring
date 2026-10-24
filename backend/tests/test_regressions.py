"""Regression tests for bugs found in the second review."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app import analytics, auth, ollama_client, storage
from backend.app.main import app

from .conftest import login_headers, make_user, sample_report


@pytest.fixture
def lenient_client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_unknown_or_missing_role_is_not_admin(client):
    auth.docstore.write_text(auth.USERS_DOC, json.dumps([
        {"email": "v@example.com", "password": "viewerpass1", "role": "Viewer"},
        {"email": "n@example.com", "password": "nopass-role1"},
        {"email": "g@example.com", "password": "generalpass1", "role": "General"},
    ]))
    for email, pw in (("v@example.com", "viewerpass1"), ("n@example.com", "nopass-role1")):
        h = login_headers(client, email, pw)
        assert client.get("/api/auth/me", headers=h).json()["role"] == "general"
        assert client.get("/api/users", headers=h).status_code == 403
    # Upper-case spelling of a valid role is accepted as that role.
    h = login_headers(client, "g@example.com", "generalpass1")
    assert client.get("/api/auth/me", headers=h).json()["role"] == "general"


def test_parallel_wrong_passwords_cannot_bypass_lockout(client):
    make_user("victim@example.com")

    def attempt(i):
        return client.post(
            "/api/auth/login", json={"email": "victim@example.com", "password": f"wrong-{i}xx"}
        ).status_code

    with ThreadPoolExecutor(20) as pool:
        codes = list(pool.map(attempt, range(20)))
    assert codes.count(401) <= auth.MAX_FAILED_LOGINS
    assert codes.count(429) >= 20 - auth.MAX_FAILED_LOGINS


def test_parallel_correct_logins_are_not_locked_out(client):
    email, password = make_user("crew@example.com")

    def attempt(_):
        return client.post("/api/auth/login", json={"email": email, "password": password}).status_code

    with ThreadPoolExecutor(8) as pool:
        assert list(pool.map(attempt, range(8))) == [200] * 8


def test_throttle_table_is_bounded(monkeypatch):
    monkeypatch.setattr(auth, "_MAX_TRACKED_KEYS", 50)
    for i in range(200):
        auth._record_failure(f"user{i}@example.com")
    assert auth._tracked_count() <= 50


def test_legacy_dict_users_file_strips_emails(client):
    auth.docstore.write_text(auth.USERS_DOC, json.dumps({" Boss@Example.com ": "legacy-password"}))
    login_headers(client, "boss@example.com", "legacy-password")


def test_extra_csv_column_is_409_everywhere(lenient_client, admin_headers):
    storage.docstore.write_text(storage.DOC, ",".join(storage.HEADERS) + ",Extra\n")
    calls = [
        ("get", "/api/reports", {}),
        ("get", "/api/dashboard", {}),
        ("get", "/api/summaries?period=weekly", {}),
        ("post", "/api/ai/analyze", {"json": {"question": "hi"}}),
        ("delete", "/api/reports/BH-1", {}),
        ("put", "/api/reports/BH-1", {"json": {}}),
        ("post", "/api/reports", {"json": sample_report()}),
    ]
    for method, path, kwargs in calls:
        res = getattr(lenient_client, method)(path, headers=admin_headers, **kwargs)
        assert res.status_code == 409, (method, path, res.status_code)


def test_csv_with_bom_is_read(client, admin_headers):
    row = ",".join(str(sample_report().get(h, "")) for h in storage.HEADERS)
    storage.docstore.write_text(storage.DOC, "﻿" + ",".join(storage.HEADERS) + "\n" + row + "\n")
    res = client.get("/api/reports", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()[0]["BoreholeID"] == "BH-001"


def test_put_null_cannot_blank_required_fields(client, admin_headers):
    client.post("/api/reports", json=sample_report(), headers=admin_headers)
    res = client.put(
        "/api/reports/BH-001",
        json={"StartDate": None, "ProjectName": None, "FinalDepth_m": None},
        headers=admin_headers,
    )
    assert res.status_code == 422
    assert storage.get_report("BH-001")["ProjectName"] == "Proyek Jalan Layang"
    # Optional fields can still be cleared.
    res = client.put("/api/reports/BH-001", json={"Remarks": None}, headers=admin_headers)
    assert res.status_code == 200


def test_put_end_before_stored_start_is_rejected(client, admin_headers):
    client.post("/api/reports", json=sample_report(), headers=admin_headers)
    start = storage.get_report("BH-001")["StartDate"]
    res = client.put("/api/reports/BH-001", json={"EndDate": "2000-01-01"}, headers=admin_headers)
    assert res.status_code == 422
    assert storage.get_report("BH-001")["StartDate"] == start


def test_non_ascii_bearer_token_is_401(lenient_client):
    res = lenient_client.get("/api/reports", headers={"Authorization": "Bearer abc.\xe9".encode("latin-1")})
    assert res.status_code == 401


def test_short_admin_password_does_not_crash_startup(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "a@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "short")
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
    assert auth.list_users() == []


@pytest.mark.parametrize("email", ["admin@company.local", "ops@intranet"])
def test_intranet_emails_can_log_in(client, email):
    auth.create_user(email, "longpassword1", "admin")
    res = client.post("/api/auth/login", json={"email": email, "password": "longpassword1"})
    assert res.status_code == 200


def test_invalid_email_is_rejected_by_cli_path():
    with pytest.raises(HTTPException):
        auth.create_user("not-an-email", "longpassword1", "admin")


@pytest.mark.parametrize("bad_id", ["BH/01", "BH%01", "BH?1", ".", ".."])
def test_unsafe_new_ids_are_rejected(client, admin_headers, bad_id):
    res = client.post("/api/reports", json=sample_report(BoreholeID=bad_id), headers=admin_headers)
    assert res.status_code == 422


def test_legacy_id_with_slash_can_be_deleted(client, admin_headers):
    storage._write_reports([dict(sample_report(BoreholeID="BH/01"), SubmittedBy="admin@example.com")])
    assert client.delete("/api/reports/BH%2F01", headers=admin_headers).status_code == 200
    assert storage.load_reports() == []


def test_delete_only_removes_the_checked_row(client, admin_headers):
    make_user("g@example.com")
    gh = login_headers(client, "g@example.com", "correct-horse-1")
    storage._write_reports([
        dict(sample_report(BoreholeID="bh-9"), SubmittedBy="g@example.com"),
        dict(sample_report(BoreholeID="BH-9"), SubmittedBy="admin@example.com"),
    ])
    assert client.delete("/api/reports/bh-9", headers=gh).status_code == 200
    remaining = storage.load_reports()
    assert [r["BoreholeID"] for r in remaining] == ["BH-9"]
    # The admin-owned row cannot be reached by the general user.
    assert client.delete("/api/reports/BH-9", headers=gh).status_code == 403


def test_ambiguous_case_only_match_is_409(client, admin_headers):
    storage._write_reports([
        dict(sample_report(BoreholeID="bh-9"), SubmittedBy="admin@example.com"),
        dict(sample_report(BoreholeID="BH-9"), SubmittedBy="admin@example.com"),
    ])
    assert client.delete("/api/reports/Bh-9", headers=admin_headers).status_code == 409
    assert len(storage.load_reports()) == 2


def test_old_token_rejected_after_account_recreated(client, admin_headers):
    make_user("w@example.com")
    h = login_headers(client, "w@example.com", "correct-horse-1")
    client.delete("/api/users/w@example.com", headers=admin_headers)
    auth.create_user("w@example.com", "other-password-9", "general")
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_summary_cache_survives_clock_minute(monkeypatch):
    calls = []
    monkeypatch.setattr(analytics, "ai_server_configured", lambda: True)
    monkeypatch.setattr(analytics, "ask_strict", lambda *a, **k: calls.append(1) or "narrative")
    rows = [sample_report()]
    monkeypatch.setattr(analytics, "_now", lambda: datetime(2026, 3, 12, 10, 0))
    analytics.build_summary_report(rows, "monthly", month=3, year=2026)
    monkeypatch.setattr(analytics, "_now", lambda: datetime(2026, 3, 12, 10, 1))
    analytics.build_summary_report(rows, "monthly", month=3, year=2026)
    assert len(calls) == 1


def test_summary_blank_depth_and_requested_label(client, admin_headers):
    storage._write_reports([dict(sample_report(FinalDepth_m=""))])
    start = sample_report()["StartDate"][:8] + "01"
    end = sample_report()["StartDate"][:8] + "28"
    res = client.get(
        f"/api/summaries?period=weekly&start_date={start}&end_date={end}", headers=admin_headers
    ).json()
    assert "None" not in res["text"]
    assert res["period_label"] == f"{start} to {end}"


def test_malformed_ollama_reply_is_not_500(lenient_client, admin_headers, monkeypatch):
    monkeypatch.setattr(ollama_client, "OLLAMA_URL", "http://ollama.invalid")

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": "oops"}

    monkeypatch.setattr(ollama_client.requests, "post", lambda *a, **k: Reply())
    res = lenient_client.post("/api/ai/analyze", json={"question": "q"}, headers=admin_headers)
    assert res.status_code == 200
    assert "unexpected" in res.json()["answer"]


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() != 0, reason="needs root")
def test_root_written_file_keeps_data_folder_owner(tmp_path):
    os.chown(tmp_path, 65534, 65534)
    target = tmp_path / "users.json"
    storage.atomic_write_text(target, "[]", mode=0o600)
    assert (target.stat().st_uid, target.stat().st_gid) == (65534, 65534)


def test_control_characters_are_stripped_and_lists_rejected(client, admin_headers):
    client.post("/api/reports", json=sample_report(), headers=admin_headers)
    res = client.put("/api/reports/BH-001", json={"Remarks": "a\x00b\x1bc\r\nd"}, headers=admin_headers)
    assert res.status_code == 200
    assert storage.get_report("BH-001")["Remarks"] == "abc\nd"
    assert "\x00" not in storage.docstore.read_text(storage.DOC)
    res = client.put("/api/reports/BH-001", json={"Remarks": ["x"]}, headers=admin_headers)
    assert res.status_code == 422


def test_negative_spt_is_rejected(client, admin_headers):
    res = client.post("/api/reports", json=sample_report(Avg_SPT_N60="-3"), headers=admin_headers)
    assert res.status_code == 422
