import time

from backend.app import auth

from .conftest import login_headers, make_user


def _code(secret, offset=0):
    return auth._totp_at(secret, int(time.time() // auth.TOTP_STEP) + offset)


def test_two_step_verification_flow(client):
    email, password = make_user("mfa@example.com", role="general")
    headers = login_headers(client, email, password)
    setup = client.post("/api/auth/2fa/setup", headers=headers).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    assert client.post("/api/auth/2fa/enable", json={"code": "000000"}, headers=headers).status_code == 400
    res = client.post("/api/auth/2fa/enable", json={"code": _code(setup["secret"])}, headers=headers)
    assert res.status_code == 200
    codes = res.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10

    no_code = client.post("/api/auth/login", json={"email": email, "password": password})
    assert no_code.status_code == 401 and no_code.json()["detail"] == "otp_required"
    wrong = client.post("/api/auth/login", json={"email": email, "password": password, "otp": "123456"})
    assert wrong.status_code == 401 and wrong.json()["detail"] == "Invalid authentication code"
    ok = client.post("/api/auth/login", json={"email": email, "password": password, "otp": _code(setup["secret"], 1)})
    assert ok.status_code == 200
    # A code cannot be used twice.
    again = client.post("/api/auth/login", json={"email": email, "password": password, "otp": _code(setup["secret"], 1)})
    assert again.status_code == 401
    # Recovery code works once.
    rec = client.post("/api/auth/login", json={"email": email, "password": password, "otp": codes[0].lower()})
    assert rec.status_code == 200
    assert client.post("/api/auth/login", json={"email": email, "password": password, "otp": codes[0]}).status_code == 401
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {rec.json()['token']}"}).json()
    assert me["totp_enabled"] is True and me["recovery_codes_left"] == 9


def test_admin_can_turn_off_2fa_and_users_list_shows_it(client, admin_headers):
    email, password = make_user("lost@example.com", role="general")
    headers = login_headers(client, email, password)
    secret = client.post("/api/auth/2fa/setup", headers=headers).json()["secret"]
    client.post("/api/auth/2fa/enable", json={"code": _code(secret)}, headers=headers)
    users = {u["email"]: u for u in client.get("/api/users", headers=admin_headers).json()}
    assert users["lost@example.com"]["totp_enabled"] is True
    assert client.delete("/api/users/lost@example.com/2fa", headers=admin_headers).status_code == 200
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200


def test_forgot_password_with_recovery_code(client):
    email, password = make_user("forget@example.com", role="general")
    headers = login_headers(client, email, password)
    codes = client.post("/api/auth/recovery-codes", json={"password": password}, headers=headers).json()["recovery_codes"]
    bad = client.post("/api/auth/reset-with-code", json={"email": email, "recovery_code": "AAAA-AAAA", "new_password": "brand-new-pass"})
    assert bad.status_code == 400
    res = client.post("/api/auth/reset-with-code", json={"email": email, "recovery_code": codes[3], "new_password": "brand-new-pass"})
    assert res.status_code == 200
    assert client.post("/api/auth/login", json={"email": email, "password": "brand-new-pass"}).status_code == 200
    # Old sessions die with the old password; the code is used up.
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    again = client.post("/api/auth/reset-with-code", json={"email": email, "recovery_code": codes[3], "new_password": "another-pass-1"})
    assert again.status_code == 400


def test_reset_link_token(client, monkeypatch):
    email, password = make_user("mail@example.com", role="general")
    token = auth.make_reset_token(email)
    # A reset token is never accepted as a session.
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.post("/api/auth/reset", json={"token": token, "new_password": "from-email-1"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": email, "password": "from-email-1"}).status_code == 200
    # Single use: the password changed, so the same link is dead.
    assert client.post("/api/auth/reset", json={"token": token, "new_password": "from-email-2"}).status_code == 400
    sent = []
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("APP_BASE_URL", "https://soil.example.com")
    from backend.app import mailer

    monkeypatch.setattr(mailer, "send", lambda to, subject, body: sent.append((to, body)) or True)
    assert client.post("/api/auth/forgot", json={"email": email}).json()["email_enabled"] is True
    assert client.post("/api/auth/forgot", json={"email": "nobody@example.com"}).status_code == 200
    assert len(sent) == 1 and "https://soil.example.com/#reset=" in sent[0][1]


def test_lockout_is_shared_through_storage(client):
    email, password = make_user("lock@example.com", role="general")
    for _ in range(auth.MAX_FAILED_LOGINS):
        client.post("/api/auth/login", json={"email": email, "password": "wrong-one"})
    # Another app instance reads the same document.
    assert "lock@example.com" in auth._load_throttle()
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 429


def _enable_2fa(client, email, password):
    headers = login_headers(client, email, password)
    secret = client.post("/api/auth/2fa/setup", headers=headers).json()["secret"]
    codes = client.post("/api/auth/2fa/enable", json={"code": _code(secret)}, headers=headers).json()["recovery_codes"]
    return headers, secret, codes


def test_recovery_codes_need_the_authenticator_when_2fa_is_on(client):
    email, password = make_user("both@example.com", role="general")
    _, secret, codes = _enable_2fa(client, email, password)
    assert len(codes[0].replace("-", "")) == 12
    alone = client.post("/api/auth/reset-with-code", json={"email": email, "recovery_code": codes[0], "new_password": "new-pass-123"})
    assert alone.status_code == 400
    both = client.post("/api/auth/reset-with-code", json={
        "email": email, "recovery_code": codes[0], "new_password": "new-pass-123", "otp": _code(secret, 1)})
    assert both.status_code == 200


def test_turning_2fa_off_needs_a_code_and_drops_recovery_codes(client, admin_headers):
    email, password = make_user("off@example.com", role="general")
    headers, secret, codes = _enable_2fa(client, email, password)
    login = client.post("/api/auth/login", json={"email": email, "password": password, "otp": _code(secret, 1)}).json()
    headers = {"Authorization": f"Bearer {login['token']}"}
    wrong_pw = client.post("/api/auth/2fa/disable", json={"password": "nope-nope", "code": _code(secret)}, headers=headers)
    assert wrong_pw.status_code == 400  # not 401: the session stays valid
    assert client.post("/api/auth/2fa/disable", json={"password": password, "code": "000000"}, headers=headers).status_code == 400
    assert client.post("/api/auth/recovery-codes", json={"password": "nope-nope"}, headers=headers).status_code == 400
    # Admin turns it off (lost phone): the old code sheet stops working too.
    assert client.delete(f"/api/users/{email}/2fa", headers=admin_headers).status_code == 200
    res = client.post("/api/auth/reset-with-code", json={"email": email, "recovery_code": codes[1], "new_password": "taken-over-1"})
    assert res.status_code == 400


def test_forgot_is_rate_limited_and_kept_out_of_the_main_log(client, admin_headers, monkeypatch):
    from backend.app import audit, mailer

    email, _ = make_user("flood@example.com", role="general")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("APP_BASE_URL", "https://soil.example.com")
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body: sent.append(to) or True)
    for _ in range(6):
        assert client.post("/api/auth/forgot", json={"email": email}).status_code == 200
    assert len(sent) == auth.RESET_MAILS_PER_HOUR
    assert not any(e["action"].startswith("account.reset") for e in audit._load(audit.DOC))
    assert any(e["action"] == "account.reset_email_sent" for e in audit.list_events())
