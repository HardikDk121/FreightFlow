import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.validators import Phone

City = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=30)]
# The stations a truck visits, in order. One stop is a plain point-to-point trip.
Stops = Annotated[list[City], Field(min_length=1, max_length=12)]


def _distinct(stops: list[str]) -> None:
    if len(set(stops)) != len(stops):
        raise ValueError("A station can appear once on a trip.")


class PendingDestination(BaseModel):
    to_city: str
    lr_count: int
    packages: int
    # Weight of the packages still waiting, from each LR's weight spread over its packages.
    weight_kg: Decimal
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
    # Weight of the pending packages; 0 for an old LR saved without a weight.
    weight_kg: Decimal
    # pending means the LR cannot move until its e-way bill number is added.
    ewb_status: str
    freight_by: str
    sized: bool


class PlanRequest(BaseModel):
    truck_id: uuid.UUID
    stops: Stops

    @model_validator(mode="after")
    def _check(self) -> "PlanRequest":
        _distinct(self.stops)
        return self


class PlanLine(BaseModel):
    lr_id: uuid.UUID
    lr_number: str
    consignee_name: str
    to_city: str
    pending: int
    load: int
    volume_m3: Decimal
    weight_kg: Decimal


class PlanRead(BaseModel):
    """Advice only. `load` is what the planner suggests; the manager decides what is dispatched."""

    lines: list[PlanLine]
    # Planned by weight because the LR has no package type; their space is not counted.
    weight_only: list[PendingLr]
    unsized: list[PendingLr]
    too_big: list[PendingLr]
    usable_volume_m3: Decimal
    volume_used_m3: Decimal
    volume_used_pct: int
    payload_kg: Decimal
    weight_used_kg: Decimal
    payload_used_pct: int


class Suggestion(BaseModel):
    """One truck the planner would send, with what to put on it."""

    route_name: str | None
    stops: list[str]
    # Null when no free truck is left for this group of LRs.
    truck_id: uuid.UUID | None
    vehicle_number: str | None
    truck_location: str | None
    plan: PlanRead | None
    packages_pending: int
    packages_loaded: int
    oldest_days_waiting: int
    reason: str


class DispatchLineIn(BaseModel):
    lr_id: uuid.UUID
    packages: int = Field(gt=0, le=99999)


class DispatchRequest(BaseModel):
    truck_id: uuid.UUID
    stops: Stops
    driver_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None = None
    driver_phone: Phone | None = None
    lines: list[DispatchLineIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _check(self) -> "DispatchRequest":
        _distinct(self.stops)
        if len({line.lr_id for line in self.lines}) != len(self.lines):
            raise ValueError("Each LR can appear once per trip.")
        return self


class TripLineRead(BaseModel):
    id: uuid.UUID
    lr_id: uuid.UUID
    lr_number: str
    consignee_name: str
    to_city: str
    packages: int
    delivered_at: dt.datetime | None
    # The challan this loading is recorded on, and where it was loaded.
    challan_number: str
    loaded_at: str


class TripStop(BaseModel):
    city: str
    lr_count: int
    delivered_count: int


class TripRead(BaseModel):
    id: uuid.UUID
    trip_no: int
    vehicle_number: str
    # The final stop.
    destination: str
    stops: list[TripStop]
    driver_name: str | None
    driver_phone: str | None
    status: str
    # in_transit (nothing delivered), partially_delivered (some stops done), delivered
    progress: str
    # The first stop that still has an undelivered LR; null once everything is delivered.
    next_stop: str | None
    dispatched_at: dt.datetime
    completed_at: dt.datetime | None
    lines: list[TripLineRead]


class LoadSheetRow(BaseModel):
    lr_number: str
    consignor_name: str
    consignee_name: str
    goods_description: str
    to_city: str
    challan_number: str
    packages: int
    # "Rs 35.00" when the consignee pays on delivery and this is the LR's first trip; otherwise "-".
    to_collect: str
