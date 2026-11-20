import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from app.validators import Gstin, Name, PatchModel, Phone


def _address(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines or len(lines) > 3 or any(len(line) > 48 for line in lines):
        raise ValueError("Address must be 1 to 3 lines of up to 48 characters. It is printed on the LR.")
    return "\n".join(lines)


Address = Annotated[str, AfterValidator(_address)]


def _bank(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines or len(lines) > 4 or any(len(line) > 60 for line in lines):
        raise ValueError("Bank details must be 1 to 4 lines of up to 60 characters. They are printed on money receipts.")
    return "\n".join(lines)


BankDetails = Annotated[str, AfterValidator(_bank)]
Tagline = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    tagline: str | None
    address: str | None
    gstin: str | None
    phone: str | None
    bank_details: str | None


class CompanyUpdate(PatchModel):
    not_nullable = frozenset({"name"})

    name: Name | None = None
    tagline: Tagline | None = None
    address: Address | None = None
    gstin: Gstin | None = None
    phone: Phone | None = None
    bank_details: BankDetails | None = None
