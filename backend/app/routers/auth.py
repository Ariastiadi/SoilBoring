from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field

from ..auth import TOKEN_TTL, authenticate_user, generate_token, get_current_user


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
def login(payload: LoginRequest):
    user = authenticate_user(payload.email, payload.password)
    token = generate_token(user["email"])
    return {"token": token, "email": user["email"], "role": user.get("role", "admin"), "expires_in": TOKEN_TTL}


@router.get("/me")
def current_user(user=Depends(get_current_user)):
    return {"email": user["email"], "role": user.get("role", "admin")}
