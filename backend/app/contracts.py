"""Customer rate contracts: a customer's agreed rate per destination for a period, and the usual
transit time the office quotes for each destination."""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import audit
from app.clock import today
from app.db import get_session
from app.deps import current_user
from app.errors import conflict, not_found
from app.models import Contract, ContractRate, TransitTime, User
from app.permissions import P, require
from app.validators import BusinessName, City



class RateIn(BaseModel):
    destination: City
    basis: Literal["per_kg", "per_article"]
    rate: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]


class ContractIn(BaseModel):
    party_name: Annotated[BusinessName, StringConstraints(max_length=80)]
    starts_on: dt.date
    ends_on: dt.date
    terms: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    rates: list[RateIn] = Field(min_length=1, max_length=100)
    is_active: bool = True

    @model_validator(mode="after")
    def _check(self) -> "ContractIn":
        if self.ends_on < self.starts_on:
            raise ValueError("The contract ends before it starts.")
        if len({r.destination for r in self.rates}) != len(self.rates):
            raise ValueError("A destination is listed twice.")
        return self


class ContractRead(ContractIn):
    id: uuid.UUID
    status: Literal["upcoming", "active", "expiring", "expired", "stopped"]
    days_left: int


class ContractQuote(BaseModel):
    contract_id: uuid.UUID
    party_name: str
    ends_on: dt.date
    basis: str
    rate: Decimal


# A contract is "expiring" in its last month, time to talk about renewing it.
EXPIRING_DAYS = 30


def _status(c: Contract, day: dt.date) -> str:
    if not c.is_active:
        return "stopped"
    if day < c.starts_on:
        return "upcoming"
    if day > c.ends_on:
        return "expired"
    return "expiring" if (c.ends_on - day).days <= EXPIRING_DAYS else "active"


def read(session: Session, c: Contract, day: dt.date) -> ContractRead:
    rates = session.scalars(select(ContractRate).where(ContractRate.contract_id == c.id).order_by(ContractRate.destination)).all()
    return ContractRead(
        id=c.id, party_name=c.party_name, starts_on=c.starts_on, ends_on=c.ends_on, terms=c.terms, is_active=c.is_active,
        rates=[RateIn(destination=r.destination, basis=r.basis, rate=r.rate) for r in rates],
        status=_status(c, day), days_left=(c.ends_on - day).days,
    )


def applicable(session: Session, party: str, destination: str, on: dt.date) -> ContractQuote | None:
    """The contract rate for this customer and destination on this date, if any."""
    row = session.execute(
        select(Contract, ContractRate)
        .join(ContractRate, ContractRate.contract_id == Contract.id)
        .where(
            Contract.is_active,
            func.lower(Contract.party_name) == party.strip().lower(),
            ContractRate.destination == destination.strip().upper(),
            Contract.starts_on <= on,
            Contract.ends_on >= on,
        )
        .order_by(Contract.starts_on.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    contract, rate = row
    return ContractQuote(contract_id=contract.id, party_name=contract.party_name, ends_on=contract.ends_on, basis=rate.basis, rate=rate.rate)


def _overlaps(session: Session, data: ContractIn, keep: uuid.UUID | None) -> None:
    """Two active contracts for one customer cannot both price the same destination on the same day."""
    others = session.scalars(
        select(Contract).where(
            Contract.is_active, func.lower(Contract.party_name) == data.party_name.lower(),
            Contract.starts_on <= data.ends_on, Contract.ends_on >= data.starts_on,
        )
    ).all()
    destinations = {r.destination for r in data.rates}
    for other in others:
        if other.id == keep:
            continue
        clash = destinations & set(session.scalars(select(ContractRate.destination).where(ContractRate.contract_id == other.id)))
        if clash:
            raise conflict(f"Another contract for {data.party_name} already covers {', '.join(sorted(clash))} in these dates "
                           f"({other.starts_on:%d-%m-%Y} to {other.ends_on:%d-%m-%Y}).")


router = APIRouter(tags=["contracts"])
_manager = require(P.CONTRACTS)


@router.get("/contracts", response_model=list[ContractRead])
def list_contracts(_: User = Depends(require(P.ANALYTICS)), session: Session = Depends(get_session)) -> list[ContractRead]:
    day = today()
    return [read(session, c, day) for c in session.scalars(select(Contract).order_by(Contract.ends_on))]


@router.get("/contracts/rate", response_model=ContractQuote | None)
def contract_rate(
    party: Annotated[str, Query(min_length=1, max_length=80)],
    destination: Annotated[str, Query(min_length=1, max_length=30)],
    on: dt.date | None = None,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ContractQuote | None:
    """The agreed rate for an LR being booked, or null when there is no contract."""
    return applicable(session, party, destination, on or today())


def _save(session: Session, actor: User, contract: Contract, data: ContractIn) -> None:
    session.execute(delete(ContractRate).where(ContractRate.contract_id == contract.id))
    session.add_all(ContractRate(company_id=actor.company_id, contract_id=contract.id, **r.model_dump()) for r in data.rates)
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="contract.save", entity="contract", entity_id=contract.id,
                 detail=data.model_dump(mode="json"))


@router.post("/contracts", response_model=ContractRead, status_code=status.HTTP_201_CREATED)
def create_contract(body: ContractIn, actor: User = Depends(_manager), session: Session = Depends(get_session)) -> ContractRead:
    _overlaps(session, body, None)
    contract = Contract(company_id=actor.company_id, party_name=body.party_name, starts_on=body.starts_on, ends_on=body.ends_on,
                        terms=body.terms, is_active=body.is_active, created_by=actor.id)
    session.add(contract)
    session.flush()
    _save(session, actor, contract, body)
    return read(session, contract, today())


@router.put("/contracts/{contract_id}", response_model=ContractRead)
def update_contract(contract_id: uuid.UUID, body: ContractIn, actor: User = Depends(_manager), session: Session = Depends(get_session)) -> ContractRead:
    contract = session.get(Contract, contract_id)
    if contract is None:
        raise not_found("Contract")
    if body.is_active:
        _overlaps(session, body, contract.id)
    contract.party_name, contract.starts_on, contract.ends_on = body.party_name, body.starts_on, body.ends_on
    contract.terms, contract.is_active = body.terms, body.is_active
    _save(session, actor, contract, body)
    return read(session, contract, today())


class TransitIn(BaseModel):
    destination: City
    days_min: int = Field(ge=1, le=60)
    days_max: int = Field(ge=1, le=60)

    @model_validator(mode="after")
    def _range(self) -> "TransitIn":
        if self.days_max < self.days_min:
            raise ValueError("The longest time is shorter than the shortest.")
        return self


@router.get("/transit-times", response_model=list[TransitIn])
def list_transit(_: User = Depends(current_user), session: Session = Depends(get_session)) -> list[TransitIn]:
    return [TransitIn(destination=t.destination, days_min=t.days_min, days_max=t.days_max)
            for t in session.scalars(select(TransitTime).order_by(TransitTime.destination))]


@router.put("/transit-times", response_model=list[TransitIn])
def set_transit(body: list[TransitIn], actor: User = Depends(require(P.MASTERDATA_EDIT)), session: Session = Depends(get_session)) -> list[TransitIn]:
    """Replace the list of usual transit times ("Raipur: 4 to 5 days")."""
    if len({t.destination for t in body}) != len(body):
        raise conflict("A destination is listed twice.")
    session.execute(delete(TransitTime))
    session.add_all(TransitTime(company_id=actor.company_id, **t.model_dump()) for t in body)
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="transit.set", entity="transit_time", entity_id=None,
                 detail={"times": [t.model_dump() for t in body]})
    return sorted(body, key=lambda t: t.destination)
