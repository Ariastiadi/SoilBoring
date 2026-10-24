from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from .. import audit, mailer
from ..auth import (
    TOKEN_TTL,
    allow_reset_email,
    authenticate_user,
    change_own_password,
    confirm_password,
    confirm_totp_setup,
    create_first_admin,
    disable_totp,
    first_run_setup_enabled,
    generate_token,
    get_current_user,
    make_reset_token,
    recovery_codes_left,
    regenerate_recovery_codes,
    reset_with_recovery_code,
    reset_with_token,
    setup_needed,
    start_totp_setup,
    verify_current_totp,
)
from ..config import producer_name
from ..models import Email


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=256)
    # Authenticator code or recovery code, for accounts with two-step verification.
    otp: Optional[str] = Field(default=None, max_length=32)


def _session(user: dict) -> dict:
    token = generate_token(user["email"])
    return {"token": token, "email": user["email"], "role": user.get("role", "general"), "expires_in": TOKEN_TTL}


@router.post("/login")
def login(payload: LoginRequest):
    user = authenticate_user(payload.email, payload.password, payload.otp)
    return _session(user)


@router.get("/setup")
def setup_status():
    """Whether the sign-in page should offer to create the first admin account."""
    return {"needed": first_run_setup_enabled() and setup_needed()}


class SetupRequest(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=256)


@router.post("/setup", status_code=201)
def first_run_setup(payload: SetupRequest):
    user = create_first_admin(payload.email, payload.password)
    audit.record(user["email"], "account.first_admin", user["email"])
    return _session(user)


@router.get("/me")
def current_user(user=Depends(get_current_user)):
    return {
        "email": user["email"],
        "role": user.get("role", "general"),
        "totp_enabled": bool(user.get("totp_enabled")),
        "recovery_codes_left": recovery_codes_left(user["email"]),
    }


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


@router.post("/change-password")
def change_password(payload: PasswordChange, user=Depends(get_current_user)):
    change_own_password(user["email"], payload.current_password, payload.new_password)
    audit.record(user["email"], "account.password_changed", user["email"])
    # Old tokens (this browser and any other device) are now invalid; hand out a fresh one.
    return _session(user)


# --- Two-step verification ---------------------------------------------------

@router.post("/2fa/setup")
def totp_setup(user=Depends(get_current_user)):
    return start_totp_setup(user["email"], producer_name())


class CodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


@router.post("/2fa/enable")
def totp_enable(payload: CodeRequest, user=Depends(get_current_user)):
    codes = confirm_totp_setup(user["email"], payload.code)
    audit.record(user["email"], "account.2fa_enabled", user["email"])
    return {"recovery_codes": codes}


class PasswordConfirm(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class DisableRequest(PasswordConfirm):
    code: str = Field(min_length=6, max_length=16)


@router.post("/2fa/disable")
def totp_disable(payload: DisableRequest, user=Depends(get_current_user)):
    """Needs the password and a current authenticator code (a stolen session is not enough)."""
    confirm_password(user["email"], payload.password)
    verify_current_totp(user["email"], payload.code)
    disable_totp(user["email"])
    audit.record(user["email"], "account.2fa_disabled", user["email"])
    return {"status": "disabled"}


@router.post("/recovery-codes")
def new_recovery_codes(payload: PasswordConfirm, user=Depends(get_current_user)):
    confirm_password(user["email"], payload.password)
    codes = regenerate_recovery_codes(user["email"])
    audit.record(user["email"], "account.recovery_codes_created", user["email"])
    return {"recovery_codes": codes}


# --- Forgotten password -------------------------------------------------------

class RecoveryReset(BaseModel):
    email: Email
    recovery_code: str = Field(min_length=4, max_length=32)
    new_password: str = Field(min_length=1, max_length=256)
    # Needed when the account has two-step verification on.
    otp: Optional[str] = Field(default=None, max_length=16)


@router.post("/reset-with-code")
def reset_by_code(payload: RecoveryReset):
    reset_with_recovery_code(payload.email, payload.recovery_code, payload.new_password, payload.otp)
    audit.record(payload.email, "account.password_reset_with_code", payload.email)
    return {"status": "updated"}


class ForgotRequest(BaseModel):
    email: Email


def _send_reset_mail(email: str) -> None:
    token = make_reset_token(email)
    if not token:
        return
    link = f"{mailer.base_url()}/#reset={token}"
    sent = mailer.send(
        email,
        f"{producer_name()}: reset your password",
        "Someone asked to reset the password of your account.\n\n"
        f"Open this link within 30 minutes to choose a new password:\n{link}\n\n"
        "If this was not you, ignore this email; your password stays the same.\n",
    )
    audit.record(email, "account.reset_email_sent" if sent else "account.reset_email_failed", email, public=True)


@router.post("/forgot")
def forgot(payload: ForgotRequest, background: BackgroundTasks):
    """Emails a reset link when email is configured.

    The answer is the same, and equally fast, whether or not the account exists: the mail
    is sent after the response. At most a few mails per address per hour.
    """
    if mailer.email_enabled() and allow_reset_email(payload.email):
        background.add_task(_send_reset_mail, payload.email)
    return {"status": "ok", "email_enabled": mailer.email_enabled()}


class TokenReset(BaseModel):
    token: str = Field(min_length=10, max_length=2000)
    new_password: str = Field(min_length=1, max_length=256)


@router.post("/reset")
def reset_by_token(payload: TokenReset):
    email = reset_with_token(payload.token, payload.new_password)
    audit.record(email, "account.password_reset_by_email", email)
    return {"status": "updated"}
