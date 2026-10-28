from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit, records, signup
from ..auth import (MIN_PASSWORD_LENGTH, create_user, delete_user, disable_totp, get_current_user, list_users, require_admin,
                    set_client_links, set_password)
from ..models import Email

Role = Literal["admin", "manager", "general", "lab", "finance", "client"]
ClientIds = List[str]


def _check_clients(client_ids: ClientIds) -> List[str]:
    """Client records a client account is linked to; each must exist."""
    out = []
    for cid in client_ids:
        try:
            records.get_record("clients", cid)
        except records.NotFound:
            raise HTTPException(status_code=422, detail="The chosen client no longer exists")
        out.append(cid)
    return out


router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreate(BaseModel):
    email: Email
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    role: Role
    client_ids: ClientIds = Field(default_factory=list, max_length=50)


@router.get("")
def get_users(admin=Depends(require_admin)):
    return list_users()


@router.get("/directory")
def directory(user=Depends(get_current_user)):
    """Names to choose from (project leader, engineer, ...): emails and roles only."""
    # Client accounts are not staff: they are never chosen as engineer, reviewer and so on.
    return [{"email": u["email"], "role": u["role"]} for u in list_users() if u["role"] != "client"]


@router.post("", status_code=201)
def add_user(payload: UserCreate, admin=Depends(require_admin)):
    links = _check_clients(payload.client_ids) if payload.role == "client" else []
    created = create_user(payload.email, payload.password, payload.role)
    if links:
        set_client_links(created["email"], links)
    audit.record(admin["email"], "user.created", created["email"], {"role": [None, created["role"]]})
    return {**created, "client_ids": links}


class ClientLinks(BaseModel):
    client_ids: ClientIds = Field(max_length=50)


class RequestApproval(BaseModel):
    role: Role
    client_ids: ClientIds = Field(default_factory=list, max_length=50)


@router.get("/requests")
def account_requests(admin=Depends(require_admin)):
    """Open requests from the sign-in page, oldest first."""
    return signup.pending()


@router.post("/requests/{email:path}/approve", status_code=201)
def approve_request(email: str, payload: RequestApproval, admin=Depends(require_admin)):
    links = _check_clients(payload.client_ids) if payload.role == "client" else []
    created = signup.approve(email, payload.role)
    if links:
        set_client_links(created["email"], links)
    audit.record(admin["email"], "user.request_approved", created["email"], {"role": [None, created["role"]]})
    return created


# Declared before the catch-all "{email:path}" route.
@router.put("/{email:path}/clients")
def link_clients(email: str, payload: ClientLinks, admin=Depends(require_admin)):
    """Which client records a client account belongs to."""
    out = set_client_links(email, _check_clients(payload.client_ids))
    audit.record(admin["email"], "user.clients_linked", out["email"], {"client_ids": out["client_ids"]})
    return out


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
