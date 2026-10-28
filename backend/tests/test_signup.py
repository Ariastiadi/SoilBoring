"""Account requests from the sign-in page: nobody gets in before an admin approves."""
from backend.app import signup

from .conftest import login_headers, make_user

REQUEST = {"email": "new.staff@example.com", "password": "field-book-77", "name": "Budi  Santoso",
           "department": "lab", "note": "Lab staff, project A"}


def test_request_waits_for_approval_then_signs_in_with_own_password(client, admin_headers):
    assert client.get("/api/config").json()["signup"] is True
    res = client.post("/api/auth/signup", json=REQUEST)
    assert res.status_code == 202 and res.json() == {"status": "pending"}

    # Not an account yet
    assert client.post("/api/auth/login", json={"email": REQUEST["email"], "password": REQUEST["password"]}).status_code == 401

    pending = client.get("/api/users/requests", headers=admin_headers).json()
    assert len(pending) == 1
    item = pending[0]
    assert item["email"] == REQUEST["email"] and item["name"] == "Budi Santoso"
    assert item["department"] == "lab" and item["suggested_role"] == "lab" and item["note"] == "Lab staff, project A"
    assert "password" not in item

    res = client.post(f"/api/users/requests/{REQUEST['email']}/approve", json={"role": "lab"}, headers=admin_headers)
    assert res.status_code == 201, res.text
    assert client.get("/api/users/requests", headers=admin_headers).json() == []

    headers = login_headers(client, REQUEST["email"], REQUEST["password"])
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["role"] == "lab"
    users = {u["email"]: u for u in client.get("/api/users", headers=admin_headers).json()}
    assert users[REQUEST["email"]]["name"] == "Budi Santoso"


def test_reject_removes_the_request(client, admin_headers):
    client.post("/api/auth/signup", json=REQUEST)
    assert client.delete(f"/api/users/requests/{REQUEST['email']}", headers=admin_headers).status_code == 200
    assert client.get("/api/users/requests", headers=admin_headers).json() == []
    assert client.post(f"/api/users/requests/{REQUEST['email']}/approve", json={"role": "general"},
                       headers=admin_headers).status_code == 404


def test_only_admins_see_and_handle_requests(client, general_headers):
    client.post("/api/auth/signup", json=REQUEST)
    assert client.get("/api/users/requests", headers=general_headers).status_code == 403
    assert client.post(f"/api/users/requests/{REQUEST['email']}/approve", json={"role": "admin"},
                       headers=general_headers).status_code == 403
    assert client.get("/api/users/requests").status_code == 401


def test_existing_account_gets_the_same_answer_and_is_not_changed(client, admin_headers):
    email, password = make_user("worker@example.com")
    res = client.post("/api/auth/signup", json={**REQUEST, "email": email, "password": "another-pass-9"})
    assert res.status_code == 202 and res.json() == {"status": "pending"}
    assert client.get("/api/users/requests", headers=admin_headers).json() == []
    login_headers(client, email, password)  # old password still works


def test_a_second_request_cannot_overwrite_the_first(client, admin_headers):
    client.post("/api/auth/signup", json=REQUEST)
    client.post("/api/auth/signup", json={**REQUEST, "password": "someone-else-1", "name": "Someone Else"})
    pending = client.get("/api/users/requests", headers=admin_headers).json()
    assert [p["name"] for p in pending] == ["Budi Santoso"]
    client.post(f"/api/users/requests/{REQUEST['email']}/approve", json={"role": "general"}, headers=admin_headers)
    login_headers(client, REQUEST["email"], REQUEST["password"])


def test_validation_and_rate_limit(client):
    assert client.post("/api/auth/signup", json={**REQUEST, "password": "short"}).status_code == 400
    assert client.post("/api/auth/signup", json={**REQUEST, "name": " x "}).status_code == 400
    assert client.post("/api/auth/signup", json={**REQUEST, "email": "not-an-email"}).status_code == 422
    codes = [client.post("/api/auth/signup", json={**REQUEST, "email": f"p{i}@example.com"}).status_code
             for i in range(signup.SIGNUPS_PER_HOUR + 1)]
    assert codes[-1] == 429


def test_switched_off_in_company_settings(client, admin_headers):
    res = client.post("/api/records/settings", json={"company_name": "PT Contoh", "self_signup": False},
                      headers=admin_headers)
    assert res.status_code == 201, res.text
    assert client.get("/api/config").json()["signup"] is False
    assert client.post("/api/auth/signup", json=REQUEST).status_code == 403


def test_switched_off_by_environment(client, monkeypatch):
    monkeypatch.setenv("SELF_SIGNUP", "false")
    assert client.get("/api/config").json()["signup"] is False
    assert client.post("/api/auth/signup", json=REQUEST).status_code == 403
