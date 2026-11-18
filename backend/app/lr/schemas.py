import datetime as dt
import re
import uuid
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.eway.rules import Category, Leg
from app.eway.schemas import DistanceKm, StateCode
from app.validators import Gstin, PatchModel

Amount = Annotated[Decimal, Field(ge=0, le=Decimal("99999999.99"), decimal_places=2)]
PositiveWeight = Annotated[Decimal, Field(gt=0, le=Decimal("999999.99"), decimal_places=2)]


def _prefix(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,8}", value):
        raise ValueError("Prefix must be 1 to 8 letters or digits.")
    return value


Prefix = Annotated[str, AfterValidator(_prefix)]
EwayBillNo = Annotated[str, StringConstraints(pattern=r"^[0-9]{12}$")]


def _pan(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", value):
        raise ValueError("A PAN has 10 characters, like ABCDE1234F.")
    return value


Pan = Annotated[str, AfterValidator(_pan)]


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
    # Total weight. The form works it out as packages x weight per package; it can be overridden.
    weight: PositiveWeight
    weight_per_package: PositiveWeight | None = None
    charged_weight: PositiveWeight | None = None
    rate_rule_id: uuid.UUID | None = None
    rate: Amount = Decimal("0")
    freight: Amount = Decimal("0")
    hamali: Amount = Decimal("0")
    other_charges: Amount = Decimal("0")
    st_charges: Amount = Decimal("0")
    value: Amount | None = None
    eway_bill_no: EwayBillNo | None = None
    item_type_id: uuid.UUID | None = None
    # E-way bill inputs. A party is "registered" when its GST number is given.
    from_state: StateCode
    to_state: StateCode
    goods_category: Category = Category.REGULAR
    trip_leg: Leg = Leg.DIRECT
    distance_km: DistanceKm | None = None
    hsn_code: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}([0-9]{2}){0,2}$")] | None = None
    consignor_pan: Pan | None = None
    consignee_pan: Pan | None = None
    enrolment_id: Annotated[str, StringConstraints(to_upper=True, pattern=r"^[0-9A-Za-z]{15}$")] | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> "LrFields":
        for role in ("consignor", "consignee"):
            gstin, pan = getattr(self, f"{role}_gstin"), getattr(self, f"{role}_pan")
            # Characters 3 to 12 of a GST number are the holder's PAN.
            if gstin and pan and gstin[2:12] != pan:
                raise ValueError(f"The {role}'s PAN does not match its GST number.")
        if not self.consignor_gstin and not self.consignee_gstin and not (self.consignor_pan and self.consignee_pan):
            raise ValueError("Neither party has a GST number, so the PAN of both is needed.")
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
    weight_per_package: Decimal | None
    rate_rule_id: uuid.UUID | None
    from_state: str | None
    to_state: str | None
    goods_category: str
    distance_km: int | None
    hsn_code: str | None
    # not_assessed, not_required, exempt, pending (bill number still needed), awaiting_part_b, active
    ewb_status: str
    ewb_responsible: str | None
    ewb_reason: str | None
    ewb_vehicle_number: str | None
    ewb_valid_until: dt.datetime | None
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


class PartySuggestion(BaseModel):
    """A party the company has dealt with before. `city` is where its goods last went (consignees only)."""

    name: str
    gstin: str | None
    city: str | None


class EwayBillUpdate(BaseModel):
    eway_bill_no: EwayBillNo
