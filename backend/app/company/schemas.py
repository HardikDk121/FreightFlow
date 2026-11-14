import uuid

from pydantic import BaseModel, ConfigDict

from app.validators import Gstin, Name, PatchModel


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str | None
    gstin: str | None


class CompanyUpdate(PatchModel):
    not_nullable = frozenset({"name"})

    name: Name | None = None
    address: str | None = None
    gstin: Gstin | None = None
