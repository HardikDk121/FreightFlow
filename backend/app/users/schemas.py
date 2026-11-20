import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, model_validator

from app.models import Role, User
from app.permissions import P, effective
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
    # None: works across all branches.
    branch_id: uuid.UUID | None
    permissions_granted: list[str]
    permissions_revoked: list[str]
    # What this person may actually do: the role's defaults with the owner's changes applied.
    permissions: list[str]

    @model_validator(mode="before")
    @classmethod
    def _with_permissions(cls, value):
        if isinstance(value, User):
            return {
                **{field: getattr(value, field) for field in cls.model_fields if field != "permissions"},
                "permissions": sorted(effective(value)),
            }
        return value


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
    # Leave out for someone who works across all branches.
    branch_id: uuid.UUID | None = None


class InviteCreated(BaseModel):
    """The token is returned once. The admin shares it with the new staff member."""

    token: str
    email: str
    role: Role
    expires_at: datetime


class UserAdminUpdate(PatchModel):
    not_nullable = frozenset({"role", "is_active", "permissions_granted", "permissions_revoked"})

    role: Role | None = None
    is_active: bool | None = None
    # None means all branches.
    branch_id: uuid.UUID | None = None
    permissions_granted: list[P] | None = None
    permissions_revoked: list[P] | None = None


class AdminPasswordReset(BaseModel):
    new_password: Password
