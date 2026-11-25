from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from app.eway.rules import Category, Leg, Party
from app.eway.states import STATES


def _state_code(value: str) -> str:
    if value not in STATES:
        raise ValueError("Choose a state from the list.")
    return value


StateCode = Annotated[str, AfterValidator(_state_code)]
DistanceKm = Annotated[int, Field(ge=1, le=4000)]


class StateRead(BaseModel):
    code: str
    name: str
    intra_state_threshold: Decimal
    note: str | None


class EvaluateRequest(BaseModel):
    # Left out (rather than 0 or negative) while the goods value is not known: the answer is then "value needed".
    value: Annotated[Decimal, Field(gt=0)] | None = None
    from_state: StateCode
    to_state: StateCode
    category: Category = Category.REGULAR
    consignor_registered: bool
    consignee_registered: bool
    distance_km: DistanceKm | None = None
    leg: Leg = Leg.DIRECT


class RequirementRead(BaseModel):
    required: bool | None
    rule: str
    reason: str
    responsible: Party | None
    part_b_required: bool
    validity_days: int | None
    notes: list[str]
