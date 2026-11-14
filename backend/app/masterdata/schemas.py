import re
import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.validators import Gstin, Name, PatchModel, Phone

Positive = Annotated[float, Field(gt=0, le=99_999_999)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]


def _vehicle_number(value: str) -> str:
    value = re.sub(r"[\s-]", "", value).upper()
    if not re.fullmatch(r"[A-Z0-9]{4,12}", value):
        raise ValueError("Vehicle number must be 4 to 12 letters and digits.")
    return value


VehicleNumber = Annotated[str, AfterValidator(_vehicle_number)]


class _Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool


class PartyCreate(BaseModel):
    name: Name
    address: str | None = None
    gstin: Gstin | None = None
    phone: Phone | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None

    @model_validator(mode="after")
    def _coordinates_together(self) -> "PartyCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Give both latitude and longitude, or neither.")
        return self


class PartyUpdate(PatchModel):
    not_nullable = frozenset({"name", "is_active"})

    name: Name | None = None
    address: str | None = None
    gstin: Gstin | None = None
    phone: Phone | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    is_active: bool | None = None


class PartyRead(_Read):
    name: str
    address: str | None
    gstin: str | None
    phone: str | None
    latitude: float | None
    longitude: float | None


class ItemTypeCreate(BaseModel):
    name: Name
    length_cm: Positive
    width_cm: Positive
    height_cm: Positive
    unit_weight_kg: Positive
    stackable: bool = True


class ItemTypeUpdate(PatchModel):
    not_nullable = frozenset(
        {"name", "length_cm", "width_cm", "height_cm", "unit_weight_kg", "stackable", "is_active"}
    )

    name: Name | None = None
    length_cm: Positive | None = None
    width_cm: Positive | None = None
    height_cm: Positive | None = None
    unit_weight_kg: Positive | None = None
    stackable: bool | None = None
    is_active: bool | None = None


class ItemTypeRead(_Read):
    name: str
    length_cm: float
    width_cm: float
    height_cm: float
    unit_weight_kg: float
    stackable: bool


class TruckCreate(BaseModel):
    vehicle_number: VehicleNumber
    label: str | None = None
    inner_length_cm: Positive
    inner_width_cm: Positive
    inner_height_cm: Positive
    payload_kg: Positive


class TruckUpdate(PatchModel):
    not_nullable = frozenset(
        {"vehicle_number", "inner_length_cm", "inner_width_cm", "inner_height_cm", "payload_kg", "is_active"}
    )

    vehicle_number: VehicleNumber | None = None
    label: str | None = None
    inner_length_cm: Positive | None = None
    inner_width_cm: Positive | None = None
    inner_height_cm: Positive | None = None
    payload_kg: Positive | None = None
    is_active: bool | None = None


class TruckRead(_Read):
    vehicle_number: str
    label: str | None
    inner_length_cm: float
    inner_width_cm: float
    inner_height_cm: float
    payload_kg: float
