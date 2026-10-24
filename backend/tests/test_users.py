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
