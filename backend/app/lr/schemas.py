import datetime as dt
import re
import uuid
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.validators import Gstin, PatchModel

Amount = Annotated[Decimal, Field(ge=0, le=Decimal("99999999.99"), decimal_places=2)]
PositiveWeight = Annotated[Decimal, Field(gt=0, le=Decimal("999999.99"), decimal_places=2)]


def _prefix(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,8}", value):
        raise ValueError("Prefix must be 1 to 8 letters or digits.")
    return value


Prefix = Annotated[str, AfterValidator(_prefix)]


def _text(max_length: int) -> type[str]:
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)]


class FreightBy(StrEnum):
    TO_PAY = "ToPay"
    PAID = "Paid"
    TBB = "TBB"


class LrFields(BaseModel):
    """What the clerk enters for an LR. Max lengths keep each value inside its box on the printed form."""

    model_config = ConfigDict(from_attributes=True)

    lr_date: dt.date
    from_city: _text(30)
    to_city: _text(30)
    freight_by: FreightBy
    consignor_name: _text(60)
    consignor_gstin: Gstin | None = None
    consignee_name: _text(60)
    consignee_gstin: Gstin | None = None
    goods_description: _text(50)
    packages: int = Field(gt=0, le=99999)
    weight: PositiveWeight
    charged_weight: PositiveWeight | None = None
    rate: Amount = Decimal("0")
    freight: Amount = Decimal("0")
    hamali: Amount = Decimal("0")
    other_charges: Amount = Decimal("0")
    st_charges: Amount = Decimal("0")
    value: Amount | None = None
    eway_bill_no: Annotated[str, StringConstraints(pattern=r"^[0-9]{12}$")] | None = None
    item_type_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> "LrFields":
        if self.from_city.lower() == self.to_city.lower():
            raise ValueError("From and To cannot be the same city.")
        if self.charged_weight is not None and self.charged_weight < self.weight:
            raise ValueError("Charged weight cannot be less than the actual weight.")
        if self.consignor_gstin and self.consignor_gstin == self.consignee_gstin:
            raise ValueError("Consignor and consignee cannot have the same GST number.")
        return self


class LrPreview(LrFields):
    """An unsaved LR to draw as a PDF, with the number to show on it."""

    lr_number: _text(20)


class LrPrintData(BaseModel):
    """Everything printed on the LR. No input rules here: it also carries LRs saved before a rule existed."""

    model_config = ConfigDict(from_attributes=True)

    lr_number: str
    lr_date: dt.date
    from_city: str
    to_city: str
    freight_by: str
    consignor_name: str
    consignor_gstin: str | None
    consignee_name: str
    consignee_gstin: str | None
    goods_description: str
    packages: int
    weight: Decimal | None
    charged_weight: Decimal | None
    rate: Decimal
    freight: Decimal
    hamali: Decimal
    other_charges: Decimal
    st_charges: Decimal
    value: Decimal | None
    eway_bill_no: str | None


class LrRead(LrPrintData):
    id: uuid.UUID
    status: str
    total: Decimal
    item_type_id: uuid.UUID | None
    created_at: dt.datetime
    cancelled_at: dt.datetime | None
    cancel_reason: str | None


class LrCancel(BaseModel):
    reason: _text(200)


class LrSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prefix: str
    next_number: int
    from_city: str | None
    default_st_charges: Decimal


class LrSettingsUpdate(PatchModel):
    not_nullable = frozenset({"prefix", "next_number", "default_st_charges"})

    prefix: Prefix | None = None
    next_number: Annotated[int, Field(gt=0, le=2_000_000_000)] | None = None
    from_city: _text(30) | None = None
    default_st_charges: Amount | None = None


class LrDefaults(BaseModel):
    """What a new LR form starts with. The number is provisional: it is assigned for good when the LR is saved."""

    next_lr_number: str
    from_city: str | None
    st_charges: Decimal


class LrSuggestions(BaseModel):
    """Taken from this consignor's most recent LR. Every field is null when there is none."""

    freight_by: FreightBy | None = None
    packages: int | None = None
    goods_description: str | None = None
    consignor_gstin: str | None = None
    item_type_id: uuid.UUID | None = None
