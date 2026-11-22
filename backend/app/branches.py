"""Branches: where each record belongs, so branch staff see their own branch and the owner sees all."""

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import any_, func, select
from sqlalchemy.orm import Session

from app import audit
from app.errors import conflict, not_found
from app.models import Branch, Lr, User
from app.security import utcnow
from app.validators import Phone

City = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=30)]


class BranchUpsert(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40)]
    address: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    phone: Phone | None = None
    # Destination cities this branch delivers to.
    cities: list[City] = Field(default_factory=list, max_length=100)
    is_active: bool = True


class BranchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str | None
    phone: str | None
    cities: list[str]
    is_head_office: bool
    is_active: bool


def head_office(session: Session) -> Branch:
    return session.scalars(select(Branch).where(Branch.is_head_office)).one()


def home_branch(session: Session, user: User) -> uuid.UUID:
    """Where this person's work is recorded: their branch, or the head office for people without one."""
    return user.branch_id or head_office(session).id


def delivering_branch(session: Session, city: str) -> uuid.UUID | None:
    """The branch that delivers to this destination city, if any branch lists it."""
    return session.scalar(
        select(Branch.id).where(Branch.is_active, any_(Branch.cities) == city.strip().upper()).limit(1)
    )


def lr_branch(lr: Lr) -> uuid.UUID:
    """The branch that collects and delivers for an LR: its delivering branch, else where it was booked."""
    return lr.delivery_branch_id or lr.branch_id


def list_branches(session: Session) -> list[Branch]:
    return list(session.scalars(select(Branch).order_by(Branch.is_head_office.desc(), Branch.name)))


def _check_cities(session: Session, cities: list[str], keep: uuid.UUID | None) -> None:
    """A destination city belongs to one branch, so there is never doubt who delivers."""
    for branch in session.scalars(select(Branch).where(Branch.is_active)):
        if branch.id == keep:
            continue
        clash = set(cities) & set(branch.cities)
        if clash:
            raise conflict(f"{', '.join(sorted(clash))} is already delivered by {branch.name}.")


def _check_name(session: Session, name: str, keep: uuid.UUID | None) -> None:
    other = session.scalar(select(Branch.id).where(func.lower(Branch.name) == name.lower()))
    if other is not None and other != keep:
        raise conflict(f"There is already a branch called {name}.")


def create(session: Session, actor: User, data: BranchUpsert) -> Branch:
    _check_name(session, data.name, None)
    if len(set(data.cities)) != len(data.cities):
        raise conflict("A city is listed twice.")
    _check_cities(session, data.cities, None)
    branch = Branch(company_id=actor.company_id, **data.model_dump())
    session.add(branch)
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="branch.create", entity="branch", entity_id=branch.id, detail=data.model_dump())
    return branch


def update(session: Session, actor: User, branch_id: uuid.UUID, data: BranchUpsert) -> Branch:
    branch = session.get(Branch, branch_id)
    if branch is None:
        raise not_found("Branch")
    if branch.is_head_office and not data.is_active:
        raise conflict("The head office cannot be closed.")
    _check_name(session, data.name, branch.id)
    _check_cities(session, data.cities, branch.id)
    for key, value in data.model_dump().items():
        setattr(branch, key, value)
    branch.updated_at = utcnow()
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="branch.update", entity="branch", entity_id=branch.id, detail=data.model_dump())
    return branch
