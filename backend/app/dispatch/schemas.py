import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.validators import Phone

City = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]


class PendingDestination(BaseModel):
    to_city: str
    lr_count: int
    packages: int
    oldest_lr_date: dt.date
    days_waiting: int


class PendingLr(BaseModel):
    lr_id: uuid.UUID
    lr_number: str
    lr_date: dt.date
    days_waiting: int
    to_city: str
    consignor_name: str
    consignee_name: str
    goods_description: str
    packages: int
    pending: int
    sized: bool


class PlanRequest(BaseModel):
    truck_id: uuid.UUID
    destination: City


class PlanLine(BaseModel):
    lr_id: uuid.UUID
    lr_number: str
    consignee_name: str
    pending: int
    load: int
    volume_m3: Decimal
    weight_kg: Decimal


class PlanRead(BaseModel):
    """Advice only. `load` is what the planner suggests; the manager decides what is dispatched."""

    lines: list[PlanLine]
    unsized: list[PendingLr]
    too_big: list[PendingLr]
    usable_volume_m3: Decimal
    volume_used_m3: Decimal
    volume_used_pct: int
    payload_kg: Decimal
    weight_used_kg: Decimal
    payload_used_pct: int


class DispatchLineIn(BaseModel):
    lr_id: uuid.UUID
    packages: int = Field(gt=0, le=99999)


class DispatchRequest(BaseModel):
    truck_id: uuid.UUID
    destination: City
    driver_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None = None
    driver_phone: Phone | None = None
    lines: list[DispatchLineIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _one_line_per_lr(self) -> "DispatchRequest":
        if len({line.lr_id for line in self.lines}) != len(self.lines):
            raise ValueError("Each LR can appear once per trip.")
        return self


class TripLineRead(BaseModel):
    id: uuid.UUID
    lr_id: uuid.UUID
    lr_number: str
    consignee_name: str
    packages: int
    delivered_at: dt.datetime | None


class TripRead(BaseModel):
    id: uuid.UUID
    vehicle_number: str
    destination: str
    driver_name: str | None
    driver_phone: str | None
    status: str
    dispatched_at: dt.datetime
    completed_at: dt.datetime | None
    lines: list[TripLineRead]


class LoadSheetRow(BaseModel):
    lr_number: str
    consignor_name: str
    consignee_name: str
    goods_description: str
    packages: int
    # "Rs 35.00" when the consignee pays on delivery and this is the LR's first trip; otherwise "-".
    to_collect: str
