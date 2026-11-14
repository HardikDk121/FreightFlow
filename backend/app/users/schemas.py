import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models import Role
from app.validators import Name, Password, PatchModel, Phone

Language = Literal["en", "hi", "gu"]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    email: str
    phone: str | None
    role: Role
    language: str
    is_active: bool


class ProfileUpdate(PatchModel):
    not_nullable = frozenset({"name", "language"})

    name: Name | None = None
    phone: Phone | None = None
    language: Language | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: Password


class InviteRequest(BaseModel):
    email: EmailStr
    role: Role


class InviteCreated(BaseModel):
    """The token is returned once. The admin shares it with the new staff member."""

    token: str
    email: str
    role: Role
    expires_at: datetime


class UserAdminUpdate(PatchModel):
    not_nullable = frozenset({"role", "is_active"})

    role: Role | None = None
    is_active: bool | None = None


class AdminPasswordReset(BaseModel):
    new_password: Password
