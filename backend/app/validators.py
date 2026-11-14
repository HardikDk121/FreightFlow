import re
from typing import Annotated, ClassVar

from pydantic import AfterValidator, BaseModel, StringConstraints, model_validator

_GSTIN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_PHONE = re.compile(r"^\+?[0-9]{10,13}$")


def _gstin(value: str) -> str:
    value = value.strip().upper()
    if not _GSTIN.fullmatch(value):
        raise ValueError("GSTIN must be 15 characters in the standard format.")
    return value


def _phone(value: str) -> str:
    value = re.sub(r"[\s-]", "", value)
    if not _PHONE.fullmatch(value):
        raise ValueError("Phone must be 10 to 13 digits, with an optional leading +.")
    return value


Gstin = Annotated[str, AfterValidator(_gstin)]
Phone = Annotated[str, AfterValidator(_phone)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]


class PatchModel(BaseModel):
    """Base for PATCH bodies. Fields in `not_nullable` may be omitted but not set to null."""

    not_nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_nulls(self) -> "PatchModel":
        nulled = sorted(f for f in self.model_fields_set & self.not_nullable if getattr(self, f) is None)
        if nulled:
            raise ValueError(f"These fields cannot be null: {', '.join(nulled)}.")
        return self
