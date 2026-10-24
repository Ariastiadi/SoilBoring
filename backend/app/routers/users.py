from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import MIN_PASSWORD_LENGTH, create_user, delete_user, list_users, require_admin, set_password
from ..models import Email


router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreate(BaseModel):
    email: Email
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    role: Literal["admin", "general"]


@router.get("")
def get_users(admin=Depends(require_admin)):
    return list_users()


@router.post("", status_code=201)
def add_user(payload: UserCreate, admin=Depends(require_admin)):
    return create_user(payload.email, payload.password, payload.role)


class PasswordReset(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)


# Declared before the catch-all "{email:path}" route so ".../password" is matched here.
@router.put("/{email:path}/password")
def reset_password(email: str, payload: PasswordReset, admin=Depends(require_admin)):
    set_password(email, payload.password)
    return {"status": "updated"}


@router.delete("/{email:path}")
def remove_user(email: str, admin=Depends(require_admin)):
    delete_user(email, acting_email=admin["email"])
    return {"status": "deleted"}
