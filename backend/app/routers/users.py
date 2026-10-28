from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import audit, signup
from ..auth import MIN_PASSWORD_LENGTH, create_user, delete_user, disable_totp, get_current_user, list_users, require_admin, set_password
from ..models import Email


router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreate(BaseModel):
    email: Email
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    role: Literal["admin", "manager", "general", "lab", "finance"]


@router.get("")
def get_users(admin=Depends(require_admin)):
    return list_users()


@router.get("/directory")
def directory(user=Depends(get_current_user)):
    """Names to choose from (project leader, engineer, ...): emails and roles only."""
    return [{"email": u["email"], "role": u["role"]} for u in list_users()]


@router.post("", status_code=201)
def add_user(payload: UserCreate, admin=Depends(require_admin)):
    created = create_user(payload.email, payload.password, payload.role)
    audit.record(admin["email"], "user.created", created["email"], {"role": [None, created["role"]]})
    return created


class RequestApproval(BaseModel):
    role: Literal["admin", "manager", "general", "lab", "finance"]


@router.get("/requests")
def account_requests(admin=Depends(require_admin)):
    """Open requests from the sign-in page, oldest first."""
    return signup.pending()


@router.post("/requests/{email:path}/approve", status_code=201)
def approve_request(email: str, payload: RequestApproval, admin=Depends(require_admin)):
    created = signup.approve(email, payload.role)
    audit.record(admin["email"], "user.request_approved", created["email"], {"role": [None, created["role"]]})
    return created


@router.delete("/requests/{email:path}")
def reject_request(email: str, admin=Depends(require_admin)):
    signup.reject(email)
    audit.record(admin["email"], "user.request_rejected", email)
    return {"status": "rejected"}


class PasswordReset(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)


# Declared before the catch-all "{email:path}" route so ".../password" is matched here.
@router.put("/{email:path}/password")
def reset_password(email: str, payload: PasswordReset, admin=Depends(require_admin)):
    set_password(email, payload.password)
    audit.record(admin["email"], "user.password_reset", email)
    return {"status": "updated"}


@router.delete("/{email:path}/2fa")
def reset_two_factor(email: str, admin=Depends(require_admin)):
    """For a user who lost their phone and their recovery codes."""
    disable_totp(email)
    audit.record(admin["email"], "user.2fa_reset", email)
    return {"status": "disabled"}


@router.delete("/{email:path}")
def remove_user(email: str, admin=Depends(require_admin)):
    delete_user(email, acting_email=admin["email"])
    audit.record(admin["email"], "user.deleted", email)
    return {"status": "deleted"}
