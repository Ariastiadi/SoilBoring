from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import (
    TOKEN_TTL,
    authenticate_user,
    change_own_password,
    create_first_admin,
    first_run_setup_enabled,
    generate_token,
    get_current_user,
    setup_needed,
)
from ..models import Email


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
def login(payload: LoginRequest):
    user = authenticate_user(payload.email, payload.password)
    token = generate_token(user["email"])
    return {"token": token, "email": user["email"], "role": user.get("role", "general"), "expires_in": TOKEN_TTL}


@router.get("/setup")
def setup_status():
    """Whether the sign-in page should offer to create the first admin account."""
    return {"needed": first_run_setup_enabled() and setup_needed()}


@router.post("/setup", status_code=201)
def first_run_setup(payload: LoginRequest):
    user = create_first_admin(payload.email, payload.password)
    token = generate_token(user["email"])
    return {"token": token, "email": user["email"], "role": user["role"], "expires_in": TOKEN_TTL}


@router.get("/me")
def current_user(user=Depends(get_current_user)):
    return {"email": user["email"], "role": user.get("role", "general")}


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


@router.post("/change-password")
def change_password(payload: PasswordChange, user=Depends(get_current_user)):
    change_own_password(user["email"], payload.current_password, payload.new_password)
    # Old tokens (this browser and any other device) are now invalid; hand out a fresh one.
    token = generate_token(user["email"])
    return {"token": token, "email": user["email"], "role": user.get("role", "general"), "expires_in": TOKEN_TTL}
