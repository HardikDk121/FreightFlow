import datetime as dt
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.eway.rules import Category, Leg
from app.eway.schemas import DistanceKm, StateCode
from app.validators import BusinessName, City, EnrolmentId, EwayBillNo, Gstin, HsnCode, Pan, PatchModel

Amount = Annotated[Decimal, Field(ge=0, le=Decimal("99999999.99"), decimal_places=2)]
PositiveWeight = Annotated[Decimal, Field(gt=0, le=Decimal("999999.99"), decimal_places=2)]


def _prefix(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,8}", value):
        raise ValueError("Prefix must be 1 to 8 letters or digits.")
    return value


Prefix = Annotated[str, AfterValidator(_prefix)]
# Names on the LR fit a 60-character box.
PartyName = Annotated[BusinessName, StringConstraints(max_length=60)]


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
    from_city: City
    to_city: City
    freight_by: FreightBy
    consignor_name: PartyName
    consignor_gstin: Gstin | None = None
    consignee_name: PartyName
    consignee_gstin: Gstin | None = None
    goods_description: _text(50)
    packages: int = Field(gt=0, le=99999)
    # Total weight. The form works it out as packages x weight per package; it can be overridden.
    weight: PositiveWeight
    weight_per_package: PositiveWeight | None = None
    charged_weight: PositiveWeight | None = None
    rate_rule_id: uuid.UUID | None = None
    # How the freight is worked out: rate x chargeable weight, rate x articles (packages),
    # or the rate matrix (rate_rule_id), which the server re-prices.
    charge_basis: Literal["per_kg", "per_article", "matrix"]
    rate: Amount = Decimal("0")
    freight: Amount = Decimal("0")
    hamali: Amount = Decimal("0")
    other_charges: Amount = Decimal("0")
    st_charges: Amount = Decimal("0")
    # Goods value, when given, must be more than zero (it decides the e-way bill).
    value: Annotated[Decimal, Field(gt=0, le=Decimal("99999999.99"), decimal_places=2)] | None = None
    eway_bill_no: EwayBillNo | None = None
    item_type_id: uuid.UUID | None = None
    # E-way bill inputs. A party is "registered" when its GST number is given.
    from_state: StateCode
    to_state: StateCode
    goods_category: Category = Category.REGULAR
    trip_leg: Leg = Leg.DIRECT
    distance_km: DistanceKm | None = None
    hsn_code: HsnCode | None = None
    consignor_pan: Pan | None = None
    consignee_pan: Pan | None = None
    enrolment_id: EnrolmentId | None = None

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
        if self.charge_basis == "matrix":
            if self.rate_rule_id is None:
                raise ValueError("Freight from the rate matrix needs the rate it came from.")
        else:
            quantity = (self.charged_weight or self.weight) if self.charge_basis == "per_kg" else Decimal(self.packages)
            unit = "kg" if self.charge_basis == "per_kg" else "article"
            expected = (self.rate * quantity).quantize(Decimal("0.01"), ROUND_HALF_UP)
            if self.freight != expected:
                raise ValueError(
                    f"Freight must be rate x {'chargeable weight' if unit == 'kg' else 'articles'}: "
                    f"Rs {self.rate} per {unit} x {quantity} = Rs {expected}."
                )
        return self


class LrCreate(LrFields):
    # The owner may book for a customer who is over their credit or overdue, saying why.
    credit_override_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)] | None = None


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
    # per_kg, per_article or matrix; null on LRs saved before the basis was recorded.
    charge_basis: str | None = None
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
    credit_override_reason: str | None
    branch_id: uuid.UUID
    delivery_branch_id: uuid.UUID | None
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
    # Credit and collection settings.
    credit_from: str
    overdue_hold_days: int
    credit_controls_from: dt.date | None
    collector_cash_limit: Decimal
    # Paper series the app continues: receipts and gate passes.
    receipt_prefix: str
    next_receipt_number: int
    gate_pass_prefix: str
    next_gate_pass_number: int


class LrSettingsUpdate(PatchModel):
    not_nullable = frozenset(
        {
            "prefix", "next_number", "default_st_charges", "credit_from", "overdue_hold_days", "collector_cash_limit",
            "receipt_prefix", "next_receipt_number", "gate_pass_prefix", "next_gate_pass_number",
        }
    )

    prefix: Prefix | None = None
    next_number: Annotated[int, Field(gt=0, le=2_000_000_000)] | None = None
    from_city: City | None = None
    default_st_charges: Amount | None = None
    # When a credit period starts counting: at delivery, or at booking.
    credit_from: Literal["delivery", "booking"] | None = None
    overdue_hold_days: Annotated[int, Field(ge=0, le=365)] | None = None
    # From this date, customers who are over their limit or overdue cannot be booked without the owner.
    credit_controls_from: dt.date | None = None
    collector_cash_limit: Annotated[Decimal, Field(gt=0, le=Decimal("199999"), decimal_places=2)] | None = None
    # Empty to print the bare number, as the paper pads do.
    receipt_prefix: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, max_length=6, pattern=r"^[A-Z]*$")] | None = None
    next_receipt_number: Annotated[int, Field(gt=0, le=2_000_000_000)] | None = None
    gate_pass_prefix: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, max_length=6, pattern=r"^[A-Z]*$")] | None = None
    next_gate_pass_number: Annotated[int, Field(gt=0, le=2_000_000_000)] | None = None


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
