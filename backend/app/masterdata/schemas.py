import datetime as dt
import re
import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.clock import today
from app.validators import Gstin, Name, PatchModel, Phone

# One package: up to 15 m long and 5 tonnes.
PackageSize = Annotated[float, Field(ge=1, le=1500)]
PackageWeight = Annotated[float, Field(ge=0.01, le=5000)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]


# State series (GJ03CW0620, DL1LAB1234) or Bharat series (22BH1234AA).
_VEHICLE = re.compile(r"[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}|[0-9]{2}BH[0-9]{4}[A-Z]{1,2}")


def _vehicle_number(value: str) -> str:
    value = re.sub(r"[\s-]", "", value).upper()
    if not _VEHICLE.fullmatch(value):
        raise ValueError("Enter a registration number like GJ03CW0620.")
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
    length_cm: PackageSize
    width_cm: PackageSize
    height_cm: PackageSize
    unit_weight_kg: PackageWeight
    stackable: bool = True


class ItemTypeUpdate(PatchModel):
    not_nullable = frozenset(
        {"name", "length_cm", "width_cm", "height_cm", "unit_weight_kg", "stackable", "is_active"}
    )

    name: Name | None = None
    length_cm: PackageSize | None = None
    width_cm: PackageSize | None = None
    height_cm: PackageSize | None = None
    unit_weight_kg: PackageWeight | None = None
    stackable: bool | None = None
    is_active: bool | None = None


class ItemTypeRead(_Read):
    name: str
    length_cm: float
    width_cm: float
    height_cm: float
    unit_weight_kg: float
    stackable: bool


# Limits wide enough for any road-legal goods vehicle, tight enough to catch a slipped decimal
# or metres typed as centimetres.
TruckLength = Annotated[float, Field(ge=100, le=2000)]
TruckWidth = Annotated[float, Field(ge=100, le=300)]
TruckHeight = Annotated[float, Field(ge=100, le=450)]
Payload = Annotated[float, Field(ge=100, le=60000)]
TruckLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


def _model_year(value: int) -> int:
    if not 1990 <= value <= today().year + 1:
        raise ValueError(f"Model year must be between 1990 and {today().year + 1}.")
    return value


ModelYear = Annotated[int, AfterValidator(_model_year)]


class TruckCreate(BaseModel):
    vehicle_number: VehicleNumber
    label: TruckLabel | None = None
    inner_length_cm: TruckLength
    inner_width_cm: TruckWidth
    inner_height_cm: TruckHeight
    payload_kg: Payload
    model_year: ModelYear
    insurance_expiry: dt.date
    fitness_expiry: dt.date
    # The truck's owner, when known. The company hires every truck.
    vendor_id: uuid.UUID | None = None


class TruckUpdate(PatchModel):
    not_nullable = frozenset(
        {"vehicle_number", "inner_length_cm", "inner_width_cm", "inner_height_cm", "payload_kg", "is_active"}
    )

    vehicle_number: VehicleNumber | None = None
    label: TruckLabel | None = None
    inner_length_cm: TruckLength | None = None
    inner_width_cm: TruckWidth | None = None
    inner_height_cm: TruckHeight | None = None
    payload_kg: Payload | None = None
    model_year: ModelYear | None = None
    insurance_expiry: dt.date | None = None
    fitness_expiry: dt.date | None = None
    current_station: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=30)] | None = None
    vendor_id: uuid.UUID | None = None
    is_active: bool | None = None


class TruckRead(_Read):
    vehicle_number: str
    label: str | None
    inner_length_cm: float
    inner_width_cm: float
    inner_height_cm: float
    payload_kg: float
    # Null on trucks added before these were recorded.
    model_year: int | None
    insurance_expiry: dt.date | None
    fitness_expiry: dt.date | None
    current_station: str | None
    vendor_id: uuid.UUID | None
