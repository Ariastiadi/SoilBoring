from .conftest import make_user


def test_user_endpoints_require_admin(client, general_headers):
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/users", headers=general_headers).status_code == 403
    res = client.post("/api/users", headers=general_headers,
                      json={"email": "x@example.com", "password": "longenough1", "role": "general"})
    assert res.status_code == 403


def test_admin_can_create_list_and_delete(client, admin_headers):
    res = client.post("/api/users", headers=admin_headers,
                      json={"email": "new@example.com", "password": "longenough1", "role": "general"})
    assert res.status_code == 201
    emails = [u["email"] for u in client.get("/api/users", headers=admin_headers).json()]
    assert "new@example.com" in emails
    assert client.delete("/api/users/new@example.com", headers=admin_headers).status_code == 200


def test_short_password_rejected(client, admin_headers):
    res = client.post("/api/users", headers=admin_headers,
                      json={"email": "new@example.com", "password": "short", "role": "general"})
    assert res.status_code == 422


def test_admin_cannot_delete_self_or_last_admin(client, admin_headers):
    res = client.delete("/api/users/admin@example.com", headers=admin_headers)
    assert res.status_code == 400


def test_last_admin_is_protected_even_without_self_check(client, admin_headers):
    import pytest
    from fastapi import HTTPException

    from backend.app import auth

    make_user("worker@example.com")
    with pytest.raises(HTTPException) as exc:
        auth.delete_user("admin@example.com")  # no acting user: only the last-admin rule applies
    assert exc.value.status_code == 400
    assert "last admin" in exc.value.detail

    make_user("admin2@example.com", role="admin")
    auth.delete_user("admin@example.com")  # fine now: another admin remains
    assert [u["email"] for u in auth.list_users() if u["role"] == "admin"] == ["admin2@example.com"]


def test_change_own_password_rotates_sessions(client):
    from .conftest import login_headers, make_user

    email, password = make_user("me@example.com")
    old = login_headers(client, email, password)
    other_device = login_headers(client, email, password)
    res = client.post(
        "/api/auth/change-password",
        json={"current_password": password, "new_password": "brand-new-pass-1"},
        headers=old,
    )
    assert res.status_code == 200
    new = {"Authorization": f"Bearer {res.json()['token']}"}
    assert client.get("/api/auth/me", headers=new).status_code == 200
    assert client.get("/api/auth/me", headers=other_device).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 401
    login_headers(client, email, "brand-new-pass-1")


def test_change_password_needs_correct_current_and_valid_new(client):
    from .conftest import login_headers, make_user

    email, password = make_user("me2@example.com")
    h = login_headers(client, email, password)
    bad = client.post("/api/auth/change-password", json={"current_password": "nope-nope", "new_password": "brand-new-pass-1"}, headers=h)
    assert bad.status_code == 400
    assert client.get("/api/auth/me", headers=h).status_code == 200
    short = client.post("/api/auth/change-password", json={"current_password": password, "new_password": "short"}, headers=h)
    assert short.status_code == 400


def test_admin_can_reset_password_general_cannot(client, admin_headers, general_headers):
    res = client.put("/api/users/worker@example.com/password", json={"password": "reset-by-admin-1"}, headers=admin_headers)
    assert res.status_code == 200
    assert client.get("/api/auth/me", headers=general_headers).status_code == 401
    from .conftest import login_headers

    gh = login_headers(client, "worker@example.com", "reset-by-admin-1")
    res = client.put("/api/users/admin@example.com/password", json={"password": "hijack-attempt-1"}, headers=gh)
    assert res.status_code == 403
    assert client.put("/api/users/ghost@example.com/password", json={"password": "whatever-123"}, headers=admin_headers).status_code == 404


def test_admin_reset_lifts_lockout(client, admin_headers):
    from backend.app import auth
    from .conftest import login_headers, make_user

    make_user("locked@example.com")
    for _ in range(auth.MAX_FAILED_LOGINS):
        client.post("/api/auth/login", json={"email": "locked@example.com", "password": "wrong-pass-x"})
    assert client.post("/api/auth/login", json={"email": "locked@example.com", "password": "wrong-pass-x"}).status_code == 429
    client.put("/api/users/locked@example.com/password", json={"password": "fresh-pass-123"}, headers=admin_headers)
    login_headers(client, "locked@example.com", "fresh-pass-123")
