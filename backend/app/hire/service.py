"""Hired trucks: what was agreed with the truck owner for each trip, what has been paid, what was
deducted, what the office spent, and what the trip earned. Money records are insert-only."""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app import audit
from app.collections import balances
from app.errors import conflict, forbidden, not_found
from app.models import (
    DispatchLine,
    Lr,
    Trip,
    TripDeduction,
    TripExpense,
    TripHire,
    Truck,
    User,
    Vendor,
    VendorPayment,
)
from app.permissions import P, has
from app.validators import Phone

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
ZERO = Decimal(0)


class VendorIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
    kind: Literal["truck_owner", "broker"] = "truck_owner"
    phone: Phone | None = None
    pan: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")] | None = None
    bank_details: Annotated[str, StringConstraints(strip_whitespace=True, max_length=240)] | None = None
    is_active: bool = True


class VendorRead(VendorIn):
    id: uuid.UUID


class HireIn(BaseModel):
    vendor_id: uuid.UUID
    hire_amount: Money
    rfq_id: uuid.UUID | None = None
    note: Text | None = None


class VendorPaymentIn(BaseModel):
    kind: Literal["advance", "balance", "reversal"]
    amount: Money
    method: Literal["cash", "upi", "cheque", "bank_transfer"]
    reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] | None = None
    note: Text | None = None

    @model_validator(mode="after")
    def _check(self) -> "VendorPaymentIn":
        if self.kind == "reversal" and self.note is None:
            raise ValueError("Say why the payment is being reversed.")
        if self.method != "cash" and self.reference is None:
            raise ValueError("Give the UTR, cheque number or transfer reference.")
        return self


class DeductionIn(BaseModel):
    amount: Money
    reason: Literal["shortage", "damage", "late", "other"]
    note: Text


class ExpenseIn(BaseModel):
    kind: Literal["loading_labour", "unloading_labour", "broker_commission", "other"]
    amount: Money
    note: Text | None = None


class Line(BaseModel):
    kind: str
    amount: Decimal
    note: str | None
    by: str
    at: dt.datetime
    method: str | None = None
    reference: str | None = None


class TripMoney(BaseModel):
    """One trip's earnings and costs. Revenue counts each LR's share by the packages on this trip."""

    trip_id: uuid.UUID
    trip_no: int
    vehicle_number: str
    destination: str
    status: str
    dispatched_at: dt.datetime
    revenue: Decimal
    vendor_id: uuid.UUID | None
    vendor_name: str | None
    hire: Decimal | None
    deductions: Decimal
    expenses: Decimal
    paid_to_owner: Decimal
    owed_to_owner: Decimal | None
    margin: Decimal | None
    margin_pct: float | None
    payments: list[Line]
    deduction_lines: list[Line]
    expense_lines: list[Line]


def trip_revenue(session: Session, trip_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """Each trip's share of its LRs' revenue (total plus charges at delivery), by packages carried."""
    if not trip_ids:
        return {}
    rows = session.execute(select(DispatchLine, Lr).join(Lr, Lr.id == DispatchLine.lr_id).where(DispatchLine.trip_id.in_(trip_ids))).all()
    charges = balances.charges_by_lr(session, list({lr.id for _, lr in rows}))
    out: dict[uuid.UUID, Decimal] = {t: ZERO for t in trip_ids}
    for line, lr in rows:
        if lr.status != "confirmed" or not lr.packages:
            continue
        out[line.trip_id] += ((lr.total + charges.get(lr.id, ZERO)) * line.packages / lr.packages).quantize(Decimal("0.01"))
    return out


def _sums(session: Session, trip_ids: list[uuid.UUID]):
    paid = dict(
        session.execute(
            select(VendorPayment.trip_id, func.sum(case((VendorPayment.kind == "reversal", -VendorPayment.amount), else_=VendorPayment.amount)))
            .where(VendorPayment.trip_id.in_(trip_ids))
            .group_by(VendorPayment.trip_id)
        ).all()
    ) if trip_ids else {}
    deducted = dict(session.execute(select(TripDeduction.trip_id, func.sum(TripDeduction.amount)).where(TripDeduction.trip_id.in_(trip_ids)).group_by(TripDeduction.trip_id)).all()) if trip_ids else {}
    spent = dict(session.execute(select(TripExpense.trip_id, func.sum(TripExpense.amount)).where(TripExpense.trip_id.in_(trip_ids)).group_by(TripExpense.trip_id)).all()) if trip_ids else {}
    return paid, deducted, spent


def trip_money(session: Session, trip_id: uuid.UUID) -> TripMoney:
    trip = session.get(Trip, trip_id)
    if trip is None:
        raise not_found("Trip")
    return trip_money_many(session, [trip], detail=True)[0]


def trip_money_many(session: Session, trips: list[Trip], detail: bool = False) -> list[TripMoney]:
    ids = [t.id for t in trips]
    revenue = trip_revenue(session, ids)
    paid, deducted, spent = _sums(session, ids)
    hires = {h.trip_id: h for h in session.scalars(select(TripHire).where(TripHire.trip_id.in_(ids)))} if ids else {}
    vendors = {v.id: v for v in session.scalars(select(Vendor).where(Vendor.id.in_({h.vendor_id for h in hires.values()})))} if hires else {}
    trucks = {t.id: t for t in session.scalars(select(Truck).where(Truck.id.in_({t.truck_id for t in trips})))} if trips else {}
    names = dict(session.execute(select(User.id, User.name)).all()) if detail else {}
    out = []
    for trip in trips:
        hire = hires.get(trip.id)
        deductions, expenses, paid_total = deducted.get(trip.id, ZERO), spent.get(trip.id, ZERO), paid.get(trip.id, ZERO)
        cost = hire.hire_amount - deductions + expenses if hire else None
        margin = revenue[trip.id] - cost if cost is not None else None
        out.append(
            TripMoney(
                trip_id=trip.id,
                trip_no=trip.trip_no,
                vehicle_number=trucks[trip.truck_id].vehicle_number,
                destination=trip.destination,
                status=trip.status,
                dispatched_at=trip.dispatched_at,
                revenue=revenue[trip.id],
                vendor_id=hire.vendor_id if hire else None,
                vendor_name=vendors[hire.vendor_id].name if hire else None,
                hire=hire.hire_amount if hire else None,
                deductions=deductions,
                expenses=expenses,
                paid_to_owner=paid_total,
                owed_to_owner=hire.hire_amount - deductions - paid_total if hire else None,
                margin=margin,
                margin_pct=round(float(margin) * 100 / float(revenue[trip.id]), 1) if margin is not None and revenue[trip.id] else None,
                payments=[
                    Line(kind=p.kind, amount=p.amount, note=p.note, by=names.get(p.paid_by, ""), at=p.paid_at, method=p.method, reference=p.reference)
                    for p in session.scalars(select(VendorPayment).where(VendorPayment.trip_id == trip.id).order_by(VendorPayment.paid_at))
                ] if detail else [],
                deduction_lines=[
                    Line(kind=d.reason, amount=d.amount, note=d.note, by=names.get(d.recorded_by, ""), at=d.recorded_at)
                    for d in session.scalars(select(TripDeduction).where(TripDeduction.trip_id == trip.id).order_by(TripDeduction.recorded_at))
                ] if detail else [],
                expense_lines=[
                    Line(kind=e.kind, amount=e.amount, note=e.note, by=names.get(e.recorded_by, ""), at=e.recorded_at)
                    for e in session.scalars(select(TripExpense).where(TripExpense.trip_id == trip.id).order_by(TripExpense.recorded_at))
                ] if detail else [],
            )
        )
    return out


def _locked(session: Session, trip_id: uuid.UUID) -> Trip:
    trip = session.get(Trip, trip_id, with_for_update=True)
    if trip is None:
        raise not_found("Trip")
    return trip


def set_hire(session: Session, actor: User, trip_id: uuid.UUID, data: HireIn) -> TripMoney:
    """Record what was agreed with the truck owner. Can be changed only until the first payment."""
    from app.hire import rfq as rfqs

    trip = _locked(session, trip_id)
    vendor = session.get(Vendor, data.vendor_id)
    if vendor is None or not vendor.is_active:
        raise not_found("Truck owner")
    if data.rfq_id is not None:
        rfqs.check_award(session, data.rfq_id, data.vendor_id, data.hire_amount)
    hire = session.get(TripHire, trip.id)
    if hire is not None:
        if session.scalar(select(func.count()).select_from(VendorPayment).where(VendorPayment.trip_id == trip.id)):
            raise conflict("The truck owner has already been paid for this trip; the hire can no longer change.")
        was = {"vendor": str(hire.vendor_id), "hire": str(hire.hire_amount)}
        hire.vendor_id, hire.hire_amount, hire.note = data.vendor_id, data.hire_amount, data.note
    else:
        was = None
        session.add(TripHire(trip_id=trip.id, company_id=actor.company_id, vendor_id=data.vendor_id, hire_amount=data.hire_amount,
                             rfq_id=data.rfq_id, note=data.note, agreed_by=actor.id))
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="trip.hire", entity="trip", entity_id=trip.id,
                 detail={"vendor": vendor.name, "hire": str(data.hire_amount), "was": was})
    return trip_money(session, trip.id)


def pay_owner(session: Session, actor: User, trip_id: uuid.UUID, data: VendorPaymentIn) -> TripMoney:
    trip = _locked(session, trip_id)
    hire = session.get(TripHire, trip.id)
    if hire is None:
        raise conflict("Record the hire agreed with the truck owner first.")
    money = trip_money(session, trip.id)
    if data.kind == "reversal":
        if data.amount > money.paid_to_owner:
            raise conflict(f"Only Rs {money.paid_to_owner:,.2f} has been paid on this trip.")
    else:
        if data.amount > money.owed_to_owner:
            raise conflict(f"The truck owner is owed Rs {money.owed_to_owner:,.2f} on this trip, not Rs {data.amount:,.2f}.")
        # The balance is paid once the goods have arrived, so shortages and damage can be deducted first.
        if data.kind == "balance" and trip.status != "completed" and not has(actor, P.APPROVALS_DECIDE):
            raise forbidden()
    session.add(VendorPayment(company_id=actor.company_id, trip_id=trip.id, vendor_id=hire.vendor_id, kind=data.kind, amount=data.amount,
                              method=data.method, reference=data.reference, note=data.note, paid_by=actor.id))
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action=f"vendor.{data.kind}", entity="trip", entity_id=trip.id,
                 detail={"amount": str(data.amount), "method": data.method, "reference": data.reference, "note": data.note})
    return trip_money(session, trip.id)


def deduct(session: Session, actor: User, trip_id: uuid.UUID, data: DeductionIn) -> TripMoney:
    trip = _locked(session, trip_id)
    money = trip_money(session, trip.id)
    if money.owed_to_owner is None:
        raise conflict("Record the hire agreed with the truck owner first.")
    if data.amount > money.owed_to_owner:
        raise conflict(f"Only Rs {money.owed_to_owner:,.2f} is still owed to the truck owner; deduct at most that.")
    session.add(TripDeduction(company_id=actor.company_id, trip_id=trip.id, amount=data.amount, reason=data.reason, note=data.note, recorded_by=actor.id))
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="trip.deduction", entity="trip", entity_id=trip.id,
                 detail={"amount": str(data.amount), "reason": data.reason, "note": data.note})
    return trip_money(session, trip.id)


def add_expense(session: Session, actor: User, trip_id: uuid.UUID, data: ExpenseIn) -> TripMoney:
    trip = _locked(session, trip_id)
    session.add(TripExpense(company_id=actor.company_id, trip_id=trip.id, kind=data.kind, amount=data.amount, note=data.note, recorded_by=actor.id))
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="trip.expense", entity="trip", entity_id=trip.id,
                 detail={"amount": str(data.amount), "kind": data.kind})
    return trip_money(session, trip.id)


class VendorDue(BaseModel):
    vendor_id: uuid.UUID
    vendor_name: str
    phone: str | None
    trips: int
    hire: Decimal
    deductions: Decimal
    paid: Decimal
    owed: Decimal
    oldest_unpaid: dt.date | None


class Payables(BaseModel):
    total_owed: Decimal
    vendors: list[VendorDue]
    trips: list[TripMoney]


def payables(session: Session) -> Payables:
    """What is owed to truck owners, trip by trip."""
    trips = list(session.scalars(select(Trip).join(TripHire, TripHire.trip_id == Trip.id).order_by(Trip.dispatched_at)))
    money = [m for m in trip_money_many(session, trips) if m.owed_to_owner and m.owed_to_owner > 0]
    vendors: dict[uuid.UUID, VendorDue] = {}
    phones = dict(session.execute(select(Vendor.id, Vendor.phone)).all())
    for m in money:
        v = vendors.get(m.vendor_id)
        if v is None:
            v = vendors[m.vendor_id] = VendorDue(vendor_id=m.vendor_id, vendor_name=m.vendor_name, phone=phones.get(m.vendor_id), trips=0,
                                                 hire=ZERO, deductions=ZERO, paid=ZERO, owed=ZERO, oldest_unpaid=m.dispatched_at.date())
        v.trips += 1
        v.hire += m.hire
        v.deductions += m.deductions
        v.paid += m.paid_to_owner
        v.owed += m.owed_to_owner
    rows = sorted(vendors.values(), key=lambda v: v.owed, reverse=True)
    return Payables(total_owed=sum((v.owed for v in rows), ZERO), vendors=rows, trips=money)
