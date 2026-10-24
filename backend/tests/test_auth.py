import hashlib
import json

import pytest

from backend.app import auth

from .conftest import login_headers, make_user


def test_login_success_and_me(client):
    email, password = make_user("a@example.com", role="admin")
    headers = login_headers(client, email, password)
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json() == {"email": "a@example.com", "role": "admin", "totp_enabled": False, "recovery_codes_left": 0}


def test_wrong_password_and_unknown_user_look_the_same(client):
    make_user("a@example.com")
    bad_pw = client.post("/api/auth/login", json={"email": "a@example.com", "password": "nope-nope-1"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-1"})
    assert bad_pw.status_code == unknown.status_code == 401
    assert bad_pw.json() == unknown.json()


def test_login_is_throttled_after_repeated_failures(client):
    make_user("a@example.com")
    for _ in range(auth.MAX_FAILED_LOGINS):
        assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "bad-bad-bad"}).status_code == 401
    blocked = client.post("/api/auth/login", json={"email": "a@example.com", "password": "correct-horse-1"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_successful_login_resets_failure_counter(client):
    make_user("a@example.com")
    for _ in range(auth.MAX_FAILED_LOGINS - 1):
        client.post("/api/auth/login", json={"email": "a@example.com", "password": "bad-bad-bad"})
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "correct-horse-1"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "bad-bad-bad"}).status_code == 401


def test_legacy_sha256_hash_still_works_and_is_upgraded(client):
    salt = "c18ef9cb596f199c"
    digest = hashlib.sha256((salt + "old-password-1").encode()).hexdigest()
    auth.docstore.write_text(auth.USERS_DOC, json.dumps([
        {"email": "legacy@example.com", "password": f"sha256${salt}${digest}", "role": "admin"}
    ]))
    login_headers(client, "legacy@example.com", "old-password-1")
    stored = json.loads(auth.docstore.read_text(auth.USERS_DOC))[0]["password"]
    assert stored.startswith("pbkdf2_sha256$")
    login_headers(client, "legacy@example.com", "old-password-1")


def test_plaintext_entry_is_upgraded_to_a_hash(client):
    auth.docstore.write_text(auth.USERS_DOC, json.dumps([{"email": "p@example.com", "password": "plain-secret-1", "role": "admin"}]))
    login_headers(client, "p@example.com", "plain-secret-1")
    assert json.loads(auth.docstore.read_text(auth.USERS_DOC))[0]["password"].startswith("pbkdf2_sha256$")


def test_tampered_and_expired_tokens_are_rejected(client):
    email, password = make_user("a@example.com")
    token = login_headers(client, email, password)["Authorization"].split()[1]
    encoded, signature = token.rsplit(".", 1)
    forged = auth._encode_payload({"email": "a@example.com", "exp": 9999999999}) + "." + signature
    for bad in (forged, token + "x", "garbage", ""):
        res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"})
        assert res.status_code == 401
    expired = auth._encode_payload({"email": "a@example.com", "exp": 1})
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}.{auth._sign(expired)}"})
    assert res.status_code == 401


def test_weak_or_default_secret_is_refused(monkeypatch):
    for weak in ("change-me-please", "short"):
        monkeypatch.setenv("AUTH_TOKEN_SECRET", weak)
        with pytest.raises(RuntimeError):
            auth._resolve_token_secret()


def test_secret_is_generated_and_persisted_when_missing(monkeypatch):
    monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)
    auth.docstore.delete(auth.SECRET_DOC)
    first = auth._resolve_token_secret()
    assert len(first) >= 32
    assert auth._resolve_token_secret() == first
    auth.docstore.delete(auth.SECRET_DOC)


def test_bootstrap_admin_only_when_no_users(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "bootstrap-pass-1")
    assert auth.bootstrap_admin_from_env() == "boss@example.com"
    assert auth.bootstrap_admin_from_env() is None
    assert [u["role"] for u in auth.list_users()] == ["admin"]


def test_first_run_setup_creates_one_admin_then_closes(client, monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    assert client.get("/api/auth/setup").json() == {"needed": True}
    short = client.post("/api/auth/setup", json={"email": "first@example.com", "password": "short"})
    assert short.status_code == 400
    r = client.post("/api/auth/setup", json={"email": "First@Example.com", "password": "first-admin-1"})
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "admin"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200 and me.json()["role"] == "admin"
    assert client.get("/api/auth/setup").json() == {"needed": False}
    again = client.post("/api/auth/setup", json={"email": "evil@example.com", "password": "evil-admin-1"})
    assert again.status_code == 409
    assert [u["email"] for u in auth.list_users()] == ["First@Example.com"]


def test_first_run_setup_respects_admin_email_and_switch(client, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "boss@example.com")
    wrong = client.post("/api/auth/setup", json={"email": "other@example.com", "password": "first-admin-1"})
    assert wrong.status_code == 403
    assert auth.list_users() == []
    monkeypatch.setenv("ALLOW_FIRST_RUN_SETUP", "false")
    assert client.get("/api/auth/setup").json() == {"needed": False}
    off = client.post("/api/auth/setup", json={"email": "boss@example.com", "password": "first-admin-1"})
    assert off.status_code == 403
    monkeypatch.delenv("ALLOW_FIRST_RUN_SETUP")
    ok = client.post("/api/auth/setup", json={"email": "BOSS@example.com", "password": "first-admin-1"})
    assert ok.status_code == 201
