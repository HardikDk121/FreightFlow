"""Requests for quotes: asking several truck owners and brokers what they want to carry a load,
collecting their prices (revised as often as they like, every revision kept), and awarding one.
The awarded price becomes the trip's hire."""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, branches
from app.errors import conflict, not_found
from app.lr.service import _settings
from app.models import Company, Rfq, RfqInvite, RfqQuote, User, Vendor
from app.notify import Outbox
from app.security import utcnow

City = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=2, max_length=30)]
Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
# A vendor is reminded at most this often.
REMIND_EVERY = dt.timedelta(hours=2)


class RfqIn(BaseModel):
    origin: City
    destination: City
    weight_kg: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
    truck_type: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    needed_on: dt.date
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    vendor_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class QuoteIn(BaseModel):
    vendor_id: uuid.UUID
    amount: Money
    vehicle_number: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, max_length=15)] | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class QuoteRead(BaseModel):
    id: uuid.UUID
    vendor_id: uuid.UUID
    vendor_name: str
    amount: Decimal
    vehicle_number: str | None
    note: str | None
    received_at: dt.datetime
    # Earlier quotes from the same vendor on this request, oldest first.
    revisions: list[Decimal]
    rank: int


class RfqRead(BaseModel):
    id: uuid.UUID
    rfq_number: int
    origin: str
    destination: str
    weight_kg: Decimal
    truck_type: str | None
    needed_on: dt.date
    note: str | None
    status: str
    invited: list[str]
    not_responded: list[str]
    quotes: list[QuoteRead]
    awarded_quote_id: uuid.UUID | None
    created_at: dt.datetime


def _read(session: Session, rfq: Rfq) -> RfqRead:
    invites = session.scalars(select(RfqInvite).where(RfqInvite.rfq_id == rfq.id)).all()
    vendors = dict(session.execute(select(Vendor.id, Vendor.name)).all())
    quotes = session.scalars(select(RfqQuote).where(RfqQuote.rfq_id == rfq.id).order_by(RfqQuote.received_at)).all()
    history: dict[uuid.UUID, list[RfqQuote]] = {}
    for q in quotes:
        history.setdefault(q.vendor_id, []).append(q)
    latest = sorted((qs[-1] for qs in history.values()), key=lambda q: q.amount)
    return RfqRead(
        id=rfq.id, rfq_number=rfq.rfq_number, origin=rfq.origin, destination=rfq.destination, weight_kg=rfq.weight_kg,
        truck_type=rfq.truck_type, needed_on=rfq.needed_on, note=rfq.note, status=rfq.status,
        invited=[vendors[i.vendor_id] for i in invites],
        not_responded=[vendors[i.vendor_id] for i in invites if i.vendor_id not in history],
        quotes=[
            QuoteRead(id=q.id, vendor_id=q.vendor_id, vendor_name=vendors[q.vendor_id], amount=q.amount, vehicle_number=q.vehicle_number,
                      note=q.note, received_at=q.received_at, revisions=[r.amount for r in history[q.vendor_id][:-1]], rank=i + 1)
            for i, q in enumerate(latest)
        ],
        awarded_quote_id=rfq.awarded_quote_id,
        created_at=rfq.created_at,
    )


def _message(company: str, rfq: Rfq) -> str:
    return (f"{company}: need a truck {rfq.origin} to {rfq.destination}, {rfq.weight_kg:,.0f} kg"
            f"{f', {rfq.truck_type}' if rfq.truck_type else ''}, on {rfq.needed_on:%d-%m-%Y}. Please send your rate. Ref RFQ-{rfq.rfq_number}.")


def _notify(session: Session, outbox: Outbox, rfq: Rfq, vendor_ids: list[uuid.UUID]) -> None:
    company = session.get_one(Company, rfq.company_id).name
    for vendor in session.scalars(select(Vendor).where(Vendor.id.in_(vendor_ids))):
        if vendor.phone:
            outbox.whatsapp(vendor.phone, _message(company, rfq)) or outbox.sms(vendor.phone, _message(company, rfq))


def create(session: Session, actor: User, outbox: Outbox, data: RfqIn) -> RfqRead:
    vendors = session.scalars(select(Vendor).where(Vendor.id.in_(data.vendor_ids), Vendor.is_active)).all()
    if len(vendors) != len(set(data.vendor_ids)):
        raise not_found("Truck owner")
    settings = _settings(session, actor.company_id, for_update=True)
    rfq = Rfq(company_id=actor.company_id, branch_id=branches.home_branch(session, actor), rfq_number=settings.next_rfq_number,
              origin=data.origin, destination=data.destination, weight_kg=data.weight_kg, truck_type=data.truck_type,
              needed_on=data.needed_on, note=data.note, created_by=actor.id)
    settings.next_rfq_number += 1
    session.add(rfq)
    session.flush()
    session.add_all(RfqInvite(company_id=actor.company_id, rfq_id=rfq.id, vendor_id=v.id) for v in vendors)
    session.flush()
    _notify(session, outbox, rfq, [v.id for v in vendors])
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="rfq.create", entity="rfq", entity_id=rfq.id,
                 detail={"number": rfq.rfq_number, "vendors": [v.name for v in vendors]})
    return _read(session, rfq)


def _open(session: Session, rfq_id: uuid.UUID) -> Rfq:
    rfq = session.get(Rfq, rfq_id, with_for_update=True)
    if rfq is None:
        raise not_found("Request for quotes")
    if rfq.status != "open":
        raise conflict(f"RFQ-{rfq.rfq_number} is {rfq.status}.")
    return rfq


def get(session: Session, rfq_id: uuid.UUID) -> RfqRead:
    rfq = session.get(Rfq, rfq_id)
    if rfq is None:
        raise not_found("Request for quotes")
    return _read(session, rfq)


def list_rfqs(session: Session, status: str | None) -> list[RfqRead]:
    query = select(Rfq).order_by(Rfq.created_at.desc()).limit(100)
    if status:
        query = query.where(Rfq.status == status)
    return [_read(session, r) for r in session.scalars(query)]


def add_quote(session: Session, actor: User, rfq_id: uuid.UUID, data: QuoteIn) -> RfqRead:
    """Record a price a vendor gave (by phone or message). A vendor may revise; all revisions are kept."""
    rfq = _open(session, rfq_id)
    if session.scalar(select(RfqInvite.id).where(RfqInvite.rfq_id == rfq.id, RfqInvite.vendor_id == data.vendor_id)) is None:
        # Someone not invited can still quote; they are added to the invited list.
        if session.get(Vendor, data.vendor_id) is None:
            raise not_found("Truck owner")
        session.add(RfqInvite(company_id=actor.company_id, rfq_id=rfq.id, vendor_id=data.vendor_id))
    session.add(RfqQuote(company_id=actor.company_id, rfq_id=rfq.id, recorded_by=actor.id, **data.model_dump()))
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="rfq.quote", entity="rfq", entity_id=rfq.id,
                 detail={"vendor": str(data.vendor_id), "amount": str(data.amount)})
    return _read(session, rfq)


def remind(session: Session, actor: User, outbox: Outbox, rfq_id: uuid.UUID) -> RfqRead:
    """Remind invited vendors who have not quoted (not more than once every two hours each)."""
    rfq = _open(session, rfq_id)
    quoted = set(session.scalars(select(RfqQuote.vendor_id).where(RfqQuote.rfq_id == rfq.id)))
    now = utcnow()
    due = [i for i in session.scalars(select(RfqInvite).where(RfqInvite.rfq_id == rfq.id))
           if i.vendor_id not in quoted and (i.last_reminded_at is None or now - i.last_reminded_at >= REMIND_EVERY)]
    for invite in due:
        invite.last_reminded_at = now
    session.flush()
    _notify(session, outbox, rfq, [i.vendor_id for i in due])
    return _read(session, rfq)


def award(session: Session, actor: User, rfq_id: uuid.UUID, quote_id: uuid.UUID) -> RfqRead:
    rfq = _open(session, rfq_id)
    quote = session.get(RfqQuote, quote_id)
    if quote is None or quote.rfq_id != rfq.id:
        raise not_found("Quote")
    latest = session.scalar(select(RfqQuote).where(RfqQuote.rfq_id == rfq.id, RfqQuote.vendor_id == quote.vendor_id).order_by(RfqQuote.received_at.desc()).limit(1))
    if latest.id != quote.id:
        raise conflict("That vendor has revised their quote since; award the latest one.")
    rfq.status, rfq.awarded_quote_id, rfq.closed_at = "awarded", quote.id, utcnow()
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="rfq.award", entity="rfq", entity_id=rfq.id,
                 detail={"vendor": str(quote.vendor_id), "amount": str(quote.amount)})
    return _read(session, rfq)


def cancel(session: Session, actor: User, rfq_id: uuid.UUID) -> RfqRead:
    rfq = _open(session, rfq_id)
    rfq.status, rfq.closed_at = "cancelled", utcnow()
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="rfq.cancel", entity="rfq", entity_id=rfq.id, detail={})
    return _read(session, rfq)


def check_award(session: Session, rfq_id: uuid.UUID, vendor_id: uuid.UUID, amount: Decimal) -> None:
    """A trip hired through an RFQ must use its awarded vendor and price."""
    rfq = session.get(Rfq, rfq_id)
    if rfq is None or rfq.awarded_quote_id is None:
        raise conflict("That request for quotes has not been awarded.")
    quote = session.get_one(RfqQuote, rfq.awarded_quote_id)
    if quote.vendor_id != vendor_id or quote.amount != amount:
        raise conflict(f"RFQ-{rfq.rfq_number} was awarded at Rs {quote.amount:,.2f} to another vendor or price.")


Status = Literal["open", "awarded", "cancelled"]
