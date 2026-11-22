"""One row per LR with everything analytics needs, worked out from the records the business already
keeps: the LR, its trips, its gate pass, and the money collected against it.

Every analytics figure is computed from these rows, so each can be traced to the LRs behind it.
Row-level security applies as usual: a branch manager's facts are their branch's LRs.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.collections import balances
from app.models import Collection, CollectionAllocation, DispatchLine, GatePass, GatePassLine, Lr, Trip

Stage = Literal["awaiting_dispatch", "in_transit", "awaiting_delivery", "delivered"]
CustomerRole = Literal["payer", "consignor", "consignee"]

# Longest period one request may cover, so a query cannot scan years of data by accident.
MAX_DAYS = 3 * 366


class Filters(BaseModel):
    """What to analyse. Dates are booking dates (the LR date), both inclusive."""

    date_from: dt.date
    date_to: dt.date
    branch_id: uuid.UUID | None = None
    customer: str | None = Field(default=None, max_length=60)
    customer_role: CustomerRole = "payer"
    origin: str | None = Field(default=None, max_length=30)
    destination: str | None = Field(default=None, max_length=30)
    freight_by: Literal["Paid", "ToPay", "TBB"] | None = None
    stage: Stage | None = None

    @model_validator(mode="after")
    def _range(self) -> "Filters":
        if self.date_to < self.date_from:
            raise ValueError("The end date is before the start date.")
        if (self.date_to - self.date_from).days > MAX_DAYS:
            raise ValueError("Choose a period of up to three years.")
        return self

    def previous(self) -> "Filters":
        """The period of the same length just before this one, for comparisons."""
        length = (self.date_to - self.date_from).days + 1
        return self.model_copy(
            update={"date_from": self.date_from - dt.timedelta(days=length), "date_to": self.date_from - dt.timedelta(days=1)}
        )

    def describe(self) -> str:
        parts = [f"LRs booked {self.date_from:%d-%m-%Y} to {self.date_to:%d-%m-%Y}, cancelled LRs excluded"]
        if self.customer:
            parts.append(f"{self.customer_role} {self.customer}")
        if self.origin:
            parts.append(f"from {self.origin.upper()}")
        if self.destination:
            parts.append(f"to {self.destination.upper()}")
        if self.freight_by:
            parts.append(f"freight by {self.freight_by}")
        if self.stage:
            parts.append(f"stage {self.stage.replace('_', ' ')}")
        if self.branch_id:
            parts.append("one branch")
        return "; ".join(parts)


@dataclass(frozen=True)
class Fact:
    lr_id: uuid.UUID
    lr_number: str
    lr_date: dt.date
    branch_id: uuid.UUID
    delivery_branch_id: uuid.UUID | None
    origin: str
    destination: str
    consignor: str
    consignee: str
    payer: str
    freight_by: str
    charge_basis: str | None
    packages: int
    weight: Decimal | None
    chargeable_weight: Decimal | None
    rate: Decimal
    freight: Decimal
    revenue: Decimal  # LR total plus charges added at delivery
    paid: Decimal
    first_dispatch: dt.datetime | None
    unloaded: dt.datetime | None  # last package unloaded at the destination
    fully_dispatched: bool
    fully_unloaded: bool
    pod: dt.datetime | None  # consignee signed the gate pass
    settled: dt.datetime | None  # the payment that cleared the balance
    distance_km: int | None

    @property
    def balance(self) -> Decimal:
        return self.revenue - self.paid

    @property
    def stage(self) -> Stage:
        if self.pod is not None:
            return "delivered"
        if not self.fully_dispatched:
            return "awaiting_dispatch"
        if not self.fully_unloaded:
            return "in_transit"
        return "awaiting_delivery"

    @property
    def rate_per_kg(self) -> Decimal | None:
        """Freight per chargeable kg, whatever the basis it was charged on."""
        if self.chargeable_weight and self.chargeable_weight > 0 and self.freight > 0:
            return (self.freight / self.chargeable_weight).quantize(Decimal("0.01"))
        return None

    @property
    def rate_per_article(self) -> Decimal | None:
        return (self.freight / self.packages).quantize(Decimal("0.01")) if self.freight > 0 and self.packages else None


def days_between(a: dt.datetime | dt.date | None, b: dt.datetime | dt.date | None) -> float | None:
    """Days from a to b, to two decimals for timestamps; None if either is missing."""
    if a is None or b is None:
        return None
    if isinstance(a, dt.datetime) and isinstance(b, dt.datetime):
        return round((b - a).total_seconds() / 86400, 2)
    a = a.date() if isinstance(a, dt.datetime) else a
    b = b.date() if isinstance(b, dt.datetime) else b
    return float((b - a).days)



def load(session: Session, f: Filters) -> list[Fact]:
    """The LRs matching the filters, with their execution and money facts."""
    sent = (
        select(
            DispatchLine.lr_id,
            func.sum(DispatchLine.packages).label("sent"),
            func.sum(DispatchLine.packages).filter(DispatchLine.delivered_at.is_not(None)).label("unloaded_pkgs"),
            func.min(Trip.dispatched_at).label("first_dispatch"),
            func.max(DispatchLine.delivered_at).label("unloaded_at"),
        )
        .join(Trip, Trip.id == DispatchLine.trip_id)
        .group_by(DispatchLine.lr_id)
        .subquery()
    )
    pod = (
        select(GatePassLine.lr_id, func.max(GatePass.delivered_at).label("pod_at"))
        .join(GatePass, GatePass.id == GatePassLine.gate_pass_id)
        .where(GatePass.status == "delivered")
        .group_by(GatePassLine.lr_id)
        .subquery()
    )
    paid = (
        select(
            CollectionAllocation.lr_id,
            func.sum(CollectionAllocation.amount).label("paid"),
            func.max(Collection.collected_at).label("last_paid_at"),
        )
        .join(Collection, Collection.id == CollectionAllocation.collection_id)
        .where(Collection.status != "failed")
        .group_by(CollectionAllocation.lr_id)
        .subquery()
    )
    charges = balances.charges_subquery()
    payer = case((Lr.freight_by == "ToPay", Lr.consignee_name), else_=Lr.consignor_name)
    query = (
        select(
            Lr,
            payer.label("payer"),
            func.coalesce(charges.c.charges, 0).label("charges"),
            func.coalesce(paid.c.paid, 0).label("paid"),
            paid.c.last_paid_at,
            func.coalesce(sent.c.sent, 0).label("sent"),
            func.coalesce(sent.c.unloaded_pkgs, 0).label("unloaded_pkgs"),
            sent.c.first_dispatch,
            sent.c.unloaded_at,
            pod.c.pod_at,
        )
        .outerjoin(sent, sent.c.lr_id == Lr.id)
        .outerjoin(pod, pod.c.lr_id == Lr.id)
        .outerjoin(paid, paid.c.lr_id == Lr.id)
        .outerjoin(charges, charges.c.lr_id == Lr.id)
        .where(Lr.status == "confirmed", Lr.lr_date >= f.date_from, Lr.lr_date <= f.date_to)
        .order_by(Lr.lr_date, Lr.series_no)
    )
    if f.branch_id:
        query = query.where(or_(Lr.branch_id == f.branch_id, Lr.delivery_branch_id == f.branch_id))
    if f.origin:
        query = query.where(func.upper(Lr.from_city) == f.origin.strip().upper())
    if f.destination:
        query = query.where(func.upper(Lr.to_city) == f.destination.strip().upper())
    if f.freight_by:
        query = query.where(Lr.freight_by == f.freight_by)
    if f.customer:
        column = {"payer": payer, "consignor": Lr.consignor_name, "consignee": Lr.consignee_name}[f.customer_role]
        query = query.where(func.lower(func.trim(column)) == f.customer.strip().lower())
    facts = []
    for lr, payer_name, extra, paid_amount, last_paid, sent_pkgs, unloaded_pkgs, first_dispatch, unloaded_at, pod_at in session.execute(query):
        revenue = lr.total + Decimal(extra)
        paid_total = Decimal(paid_amount)
        facts.append(
            Fact(
                lr_id=lr.id,
                lr_number=lr.lr_number,
                lr_date=lr.lr_date,
                branch_id=lr.branch_id,
                delivery_branch_id=lr.delivery_branch_id,
                origin=lr.from_city.strip().upper(),
                destination=lr.to_city.strip().upper(),
                consignor=lr.consignor_name.strip(),
                consignee=lr.consignee_name.strip(),
                payer=payer_name.strip(),
                freight_by=lr.freight_by,
                charge_basis=lr.charge_basis,
                packages=lr.packages,
                weight=lr.weight,
                chargeable_weight=lr.charged_weight or lr.weight,
                rate=lr.rate,
                freight=lr.freight,
                revenue=revenue,
                paid=paid_total,
                first_dispatch=first_dispatch,
                unloaded=unloaded_at,
                fully_dispatched=sent_pkgs >= lr.packages,
                fully_unloaded=sent_pkgs >= lr.packages and unloaded_pkgs >= lr.packages,
                pod=pod_at,
                settled=last_paid if revenue > 0 and paid_total >= revenue else None,
                distance_km=lr.distance_km,
            )
        )
    if f.stage:
        facts = [x for x in facts if x.stage == f.stage]
    return facts

