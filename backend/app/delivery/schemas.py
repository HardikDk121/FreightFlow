import datetime as dt
import uuid
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.validators import Phone

Text40 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class GatePassCreate(BaseModel):
    """Release one consignee's goods: their LRs, and the local vehicle that takes them."""

    lr_ids: list[uuid.UUID] = Field(min_length=1, max_length=30)
    auto_no: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=4, max_length=15)] | None = None
    driver_name: Text40 | None = None

    @model_validator(mode="after")
    def _distinct(self) -> "GatePassCreate":
        if len(set(self.lr_ids)) != len(self.lr_ids):
            raise ValueError("An LR can appear once on a gate pass.")
        return self


class ProofOfDelivery(BaseModel):
    """The consignee received the goods. Sent with the photo of the signed gate pass, if taken.
    `delivered_at` is the phone's time when the consignee signed, so a proof saved offline and sent
    later still says when delivery happened."""

    delivered_at: dt.datetime
    receiver_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
    receiver_phone: Phone | None = None
    # The signature as drawn: strokes of [x, y] points.
    signature: list[list[tuple[float, float]]] = Field(min_length=1, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100000)

    @model_validator(mode="after")
    def _check(self) -> "ProofOfDelivery":
        points = sum(len(stroke) for stroke in self.signature)
        if not 8 <= points <= 5000:
            raise ValueError("The signature is too short or too long. Ask the consignee to sign again.")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("A location needs both latitude and longitude.")
        if self.delivered_at.tzinfo is None:
            raise ValueError("The delivery time needs its time zone.")
        return self


class GatePassLineRead(BaseModel):
    lr_id: uuid.UUID
    lr_number: str
    packages: int
    basis: str
    # What the paper's "Payments" column says: Paid, Credit, Approved, or how the LR was booked.
    payment: str


class GatePassRead(BaseModel):
    id: uuid.UUID
    gate_pass_number: str
    consignee_name: str
    auto_no: str | None
    driver_name: str | None
    status: str
    issued_by: str
    issued_at: dt.datetime
    lines: list[GatePassLineRead]
    delivered_at: dt.datetime | None
    receiver_name: str | None
    receiver_phone: str | None
    latitude: float | None
    longitude: float | None
    has_photo: bool
    pod_recorded_by: str | None
    void_reason: str | None


class VoidRequest(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=200)]
