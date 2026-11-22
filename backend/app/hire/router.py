import uuid
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_session
from app.deps import current_user
from app.errors import conflict, not_found
from app.hire import rfq, service
from app.idempotency import IdempotencyHeader, run_once
from app.models import User, Vendor
from app.notify import Outbox, get_outbox
from app.permissions import P, require

router = APIRouter(tags=["hire"])
_manage = require(P.VENDORS_MANAGE)
_pay = require(P.VENDORS_PAY)


@router.get("/vendors", response_model=list[service.VendorRead])
def list_vendors(_: User = Depends(current_user), session: Session = Depends(get_session)) -> list[service.VendorRead]:
    return [service.VendorRead.model_validate(v, from_attributes=True) for v in session.scalars(select(Vendor).order_by(Vendor.name))]


@router.post("/vendors", response_model=service.VendorRead, status_code=status.HTTP_201_CREATED)
def create_vendor(body: service.VendorIn, actor: User = Depends(_manage), session: Session = Depends(get_session)) -> service.VendorRead:
    if session.scalar(select(Vendor.id).where(func.lower(Vendor.name) == body.name.lower())) is not None:
        raise conflict(f"{body.name} is already a truck owner here.")
    vendor = Vendor(company_id=actor.company_id, **body.model_dump())
    session.add(vendor)
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="vendor.create", entity="vendor", entity_id=vendor.id, detail=body.model_dump())
    return service.VendorRead.model_validate(vendor, from_attributes=True)


@router.put("/vendors/{vendor_id}", response_model=service.VendorRead)
def update_vendor(vendor_id: uuid.UUID, body: service.VendorIn, actor: User = Depends(_manage), session: Session = Depends(get_session)) -> service.VendorRead:
    vendor = session.get(Vendor, vendor_id)
    if vendor is None:
        raise not_found("Truck owner")
    for key, value in body.model_dump().items():
        setattr(vendor, key, value)
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="vendor.update", entity="vendor", entity_id=vendor.id, detail=body.model_dump())
    return service.VendorRead.model_validate(vendor, from_attributes=True)


@router.get("/trips/{trip_id}/money", response_model=service.TripMoney)
def trip_money(trip_id: uuid.UUID, _: User = Depends(require(P.VENDORS_MANAGE)), session: Session = Depends(get_session)) -> service.TripMoney:
    """What the trip earned and cost: revenue carried, hire, deductions, expenses, paid and owed to the owner."""
    return service.trip_money(session, trip_id)


@router.put("/trips/{trip_id}/hire", response_model=service.TripMoney)
def set_hire(trip_id: uuid.UUID, body: service.HireIn, actor: User = Depends(_manage), session: Session = Depends(get_session)) -> service.TripMoney:
    return service.set_hire(session, actor, trip_id, body)


@router.post("/trips/{trip_id}/owner-payments", response_model=service.TripMoney, status_code=status.HTTP_201_CREATED)
def pay_owner(
    trip_id: uuid.UUID,
    body: service.VendorPaymentIn,
    idempotency_key: IdempotencyHeader = None,
    actor: User = Depends(_pay),
    session: Session = Depends(get_session),
):
    """An advance at loading, the balance after delivery (earlier only with the owner's permission), or a reversal."""
    return run_once(session, actor, idempotency_key, f"POST /trips/{trip_id}/owner-payments", 201, lambda: service.pay_owner(session, actor, trip_id, body))


@router.post("/trips/{trip_id}/deductions", response_model=service.TripMoney, status_code=status.HTTP_201_CREATED)
def deduct(trip_id: uuid.UUID, body: service.DeductionIn, actor: User = Depends(_manage), session: Session = Depends(get_session)) -> service.TripMoney:
    return service.deduct(session, actor, trip_id, body)


@router.post("/trips/{trip_id}/expenses", response_model=service.TripMoney, status_code=status.HTTP_201_CREATED)
def add_expense(trip_id: uuid.UUID, body: service.ExpenseIn, actor: User = Depends(_manage), session: Session = Depends(get_session)) -> service.TripMoney:
    return service.add_expense(session, actor, trip_id, body)


@router.get("/payables", response_model=service.Payables)
def payables(_: User = Depends(_pay), session: Session = Depends(get_session)) -> service.Payables:
    """What is owed to truck owners, by owner and by trip."""
    return service.payables(session)


@router.get("/rfqs", response_model=list[rfq.RfqRead])
def list_rfqs(rfq_status: rfq.Status | None = None, _: User = Depends(_manage), session: Session = Depends(get_session)) -> list[rfq.RfqRead]:
    return rfq.list_rfqs(session, rfq_status)


@router.post("/rfqs", response_model=rfq.RfqRead, status_code=status.HTTP_201_CREATED)
def create_rfq(body: rfq.RfqIn, actor: User = Depends(_manage), session: Session = Depends(get_session), outbox: Outbox = Depends(get_outbox)) -> rfq.RfqRead:
    """Ask truck owners for a price. Each invited owner with a phone gets the details by WhatsApp or SMS."""
    return rfq.create(session, actor, outbox, body)


@router.get("/rfqs/{rfq_id}", response_model=rfq.RfqRead)
def get_rfq(rfq_id: uuid.UUID, _: User = Depends(_manage), session: Session = Depends(get_session)) -> rfq.RfqRead:
    return rfq.get(session, rfq_id)


@router.post("/rfqs/{rfq_id}/quotes", response_model=rfq.RfqRead, status_code=status.HTTP_201_CREATED)
def add_quote(rfq_id: uuid.UUID, body: rfq.QuoteIn, actor: User = Depends(_manage), session: Session = Depends(get_session)) -> rfq.RfqRead:
    return rfq.add_quote(session, actor, rfq_id, body)


@router.post("/rfqs/{rfq_id}/remind", response_model=rfq.RfqRead)
def remind(rfq_id: uuid.UUID, actor: User = Depends(_manage), session: Session = Depends(get_session), outbox: Outbox = Depends(get_outbox)) -> rfq.RfqRead:
    return rfq.remind(session, actor, outbox, rfq_id)


class AwardIn(BaseModel):
    quote_id: uuid.UUID


@router.post("/rfqs/{rfq_id}/award", response_model=rfq.RfqRead)
def award(rfq_id: uuid.UUID, body: AwardIn, actor: User = Depends(_manage), session: Session = Depends(get_session)) -> rfq.RfqRead:
    return rfq.award(session, actor, rfq_id, body.quote_id)


@router.post("/rfqs/{rfq_id}/cancel", response_model=rfq.RfqRead)
def cancel(rfq_id: uuid.UUID, actor: User = Depends(_manage), session: Session = Depends(get_session)) -> rfq.RfqRead:
    return rfq.cancel(session, actor, rfq_id)

