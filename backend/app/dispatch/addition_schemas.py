import datetime as dt
import uuid
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.dispatch.schemas import City, DispatchLineIn

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]


class AdditionRequest(BaseModel):
    """Ask to load more cargo onto a truck that is already on the road."""

    # Where the goods will be loaded.
    loaded_at: City
    # If that place is not yet a stop on the trip: the stop it comes before.
    insert_before: City | None = None
    lines: list[DispatchLineIn] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _check(self) -> "AdditionRequest":
        if len({line.lr_id for line in self.lines}) != len(self.lines):
            raise ValueError("Each LR can appear once.")
        return self


class VoidRequest(BaseModel):
    reason: Reason


class DriverCount(BaseModel):
    lr_id: uuid.UUID
    # What the driver counted onto the truck. Fewer than requested is a shortage; 0 means not loaded.
    packages: int = Field(ge=0, le=99999)


class DriverSignOff(BaseModel):
    driver_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
    # The signature as drawn: strokes, each a list of [x, y] points.
    signature: list[list[tuple[float, float]]] = Field(min_length=1, max_length=200)
    # Leave out an LR to accept the requested count for it.
    counts: list[DriverCount] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _check(self) -> "DriverSignOff":
        points = sum(len(stroke) for stroke in self.signature)
        if points < 8:
            raise ValueError("The signature is too short. Ask the driver to sign again.")
        if points > 5000:
            raise ValueError("The signature is too long to store.")
        return self


class ChallanLine(BaseModel):
    lr_id: uuid.UUID
    lr_number: str
    consignee_name: str
    to_city: str
    requested: int
    # What the driver counted; null until the driver has signed.
    loaded: int | None


class ChallanRead(BaseModel):
    id: uuid.UUID
    trip_id: uuid.UUID
    vehicle_number: str
    challan_number: str
    # 0 is the primary challan from the origin.
    seq: int
    status: str
    loaded_at: str
    requested_by: str
    approved_by: str | None
    created_at: dt.datetime
    issued_at: dt.datetime | None
    driver_name: str | None
    shortage_note: str | None
    void_reason: str | None
    lines: list[ChallanLine]
    # Things to know before approving, such as goods that will block others at unloading.
    warnings: list[str]
    # True when an issued challan still matches its seal; false if its lines were altered; null if unsealed.
    sealed: bool | None
    # What the person asking may do with this challan.
    can_approve: bool
    can_sign: bool
    can_void: bool
