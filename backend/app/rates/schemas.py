import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.validators import PatchModel

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
StationName = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=30)]
Money = Annotated[float, Field(gt=0, le=1_000_000)]
Method = Literal["per_kg", "per_package_slab", "per_unit"]


class _Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool


class StationCreate(BaseModel):
    name: StationName
    zone: StationName
    surcharge_per_kg: Annotated[float, Field(ge=0, le=1000)] = 0


class StationUpdate(PatchModel):
    not_nullable = frozenset({"name", "zone", "surcharge_per_kg", "is_active"})

    name: StationName | None = None
    zone: StationName | None = None
    surcharge_per_kg: Annotated[float, Field(ge=0, le=1000)] | None = None
    is_active: bool | None = None


class StationRead(_Read):
    name: str
    zone: str
    surcharge_per_kg: float


def _distinct(stops: list[str]) -> list[str]:
    if len(set(stops)) != len(stops):
        raise ValueError("A station can appear once on a route.")
    return stops


Stops = Annotated[list[StationName], Field(min_length=1, max_length=12)]


class RouteCreate(BaseModel):
    name: Label
    stops: Stops

    @model_validator(mode="after")
    def _check(self) -> "RouteCreate":
        _distinct(self.stops)
        return self


class RouteUpdate(PatchModel):
    not_nullable = frozenset({"name", "stops", "is_active"})

    name: Label | None = None
    stops: Stops | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> "RouteUpdate":
        if self.stops is not None:
            _distinct(self.stops)
        return self


class RouteRead(_Read):
    name: str
    stops: list[str]


class Slab(BaseModel):
    up_to_kg: Money
    amount: Money


def _check_rule(method: str | None, rate: float | None, slabs: list[Slab] | None) -> None:
    if method == "per_package_slab":
        if not slabs or rate is not None:
            raise ValueError("A slab rate needs its slabs and no single rate.")
        if len({s.up_to_kg for s in slabs}) != len(slabs):
            raise ValueError("Two slabs have the same weight limit.")
    elif method is not None and (rate is None or slabs is not None):
        raise ValueError("This kind of rate needs one rate and no slabs.")


class RateRuleCreate(BaseModel):
    goods_class: Label
    zone: StationName
    method: Method
    rate: Money | None = None
    slabs: Annotated[list[Slab], Field(max_length=30)] | None = None

    @model_validator(mode="after")
    def _check(self) -> "RateRuleCreate":
        _check_rule(self.method, self.rate, self.slabs)
        return self


class RateRuleUpdate(PatchModel):
    """Method, rate and slabs change together, so an update sends all three."""

    not_nullable = frozenset({"goods_class", "zone", "method", "is_active"})

    goods_class: Label | None = None
    zone: StationName | None = None
    method: Method | None = None
    rate: Money | None = None
    slabs: Annotated[list[Slab], Field(max_length=30)] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> "RateRuleUpdate":
        _check_rule(self.method, self.rate, self.slabs)
        return self


class RateRuleRead(_Read):
    goods_class: str
    zone: str
    method: str
    rate: float | None
    slabs: list[Slab] | None


class QuoteRequest(BaseModel):
    goods_class: Label
    to_city: StationName
    packages: int = Field(gt=0, le=99999)
    weight_per_package: Annotated[Decimal, Field(gt=0, le=Decimal("99999"))] | None = None
    # Overrides packages x weight per package, for a weighed or volumetric total.
    total_weight: Annotated[Decimal, Field(gt=0, le=Decimal("999999"))] | None = None


class QuoteRead(BaseModel):
    rate_rule_id: uuid.UUID
    freight: Decimal
    chargeable_weight: Decimal | None
    rate_per_kg: Decimal | None
    explanation: list[str]
