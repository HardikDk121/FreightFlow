import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.clock import today
from app.errors import conflict, not_found
from app.models import DispatchLine, Lr, Payment, User
from app.payments.schemas import LrAccount, PartyOutstanding, PaymentCreate, PaymentRead, Receivables

# Days a to-be-billed LR has before it counts as overdue.
BILLING_CREDIT_DAYS = 30


def _due_on(lr: Lr, delivered_on: dt.date | None) -> dt.date | None:
    """Paid is due at booking, to-pay at delivery, to-be-billed after the credit period."""
    if lr.freight_by == "Paid":
        return lr.lr_date
    if lr.freight_by == "ToPay":
        return delivered_on
    return lr.lr_date + dt.timedelta(days=BILLING_CREDIT_DAYS)


def _account(lr: Lr, paid: Decimal, delivered_on: dt.date | None, payments: list[Payment]) -> LrAccount:
    balance = lr.total - paid
    due_on = _due_on(lr, delivered_on)
    return LrAccount(
        lr_id=lr.id,
        lr_number=lr.lr_number,
        lr_date=lr.lr_date,
        freight_by=lr.freight_by,
        payer=lr.consignee_name if lr.freight_by == "ToPay" else lr.consignor_name,
        total=lr.total,
        paid=paid,
        balance=balance,
        due_on=due_on,
        overdue=balance > 0 and due_on is not None and due_on < today(),
        payments=[PaymentRead.model_validate(p) for p in payments],
    )


def _delivered_on(session: Session, lr: Lr) -> dt.date | None:
    """The day the last package was delivered, or None while any package is still pending or on the road."""
    sent, delivered, last = session.execute(
        select(
            func.coalesce(func.sum(DispatchLine.packages), 0),
            func.coalesce(func.sum(DispatchLine.packages).filter(DispatchLine.delivered_at.is_not(None)), 0),
            func.max(DispatchLine.delivered_at),
        ).where(DispatchLine.lr_id == lr.id)
    ).one()
    return last.date() if sent == lr.packages and delivered == lr.packages else None


def lr_account(session: Session, lr_id: uuid.UUID, *, for_update: bool = False) -> LrAccount:
    lr = session.get(Lr, lr_id, with_for_update=for_update)
    if lr is None:
        raise not_found("LR")
    payments = list(session.scalars(select(Payment).where(Payment.lr_id == lr.id).order_by(Payment.created_at)))
    return _account(lr, sum((p.amount for p in payments), Decimal(0)), _delivered_on(session, lr), payments)


def record(session: Session, actor: User, lr_id: uuid.UUID, data: PaymentCreate) -> LrAccount:
    """Take a payment against an LR. The LR row is locked so two payments cannot overshoot the balance."""
    account = lr_account(session, lr_id, for_update=True)
    lr = session.get_one(Lr, lr_id)
    if lr.status != "confirmed":
        raise conflict("This LR is cancelled.")
    if data.amount > account.balance:
        raise conflict(f"Only Rs {account.balance:,.2f} is outstanding on LR {lr.lr_number}.")
    payment = Payment(
        company_id=actor.company_id,
        lr_id=lr.id,
        amount=data.amount.quantize(Decimal("0.01")),
        mode=data.mode,
        reference=data.reference,
        note=data.note,
        received_on=data.received_on or today(),
        received_by=actor.id,
    )
    session.add(payment)
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="payment.record",
        entity="payment",
        entity_id=payment.id,
        detail={"lr_number": lr.lr_number, "amount": str(data.amount), "mode": data.mode},
    )
    return lr_account(session, lr_id)


def open_accounts(session: Session, party: str | None = None) -> list[LrAccount]:
    """Every confirmed LR with money still owed, oldest first; optionally for one payer."""
    paid = select(Payment.lr_id, func.sum(Payment.amount).label("paid")).group_by(Payment.lr_id).subquery()
    rows = session.execute(
        select(Lr, func.coalesce(paid.c.paid, 0))
        .outerjoin(paid, paid.c.lr_id == Lr.id)
        .where(Lr.status == "confirmed", Lr.total > func.coalesce(paid.c.paid, 0))
        .order_by(Lr.lr_date, Lr.series_no)
    ).all()
    accounts = [_account(lr, Decimal(paid_amount), _delivered_on(session, lr), []) for lr, paid_amount in rows]
    return [a for a in accounts if party is None or a.payer.lower() == party.strip().lower()]


def receivables(session: Session) -> Receivables:
    """Outstanding money by payer, the largest first."""
    parties: dict[str, PartyOutstanding] = {}
    for account in open_accounts(session):
        key = account.payer.lower()
        entry = parties.get(key)
        if entry is None:
            entry = parties[key] = PartyOutstanding(
                party=account.payer, lr_count=0, outstanding=Decimal(0), overdue=Decimal(0), oldest_lr_date=account.lr_date
            )
        entry.lr_count += 1
        entry.outstanding += account.balance
        if account.overdue:
            entry.overdue += account.balance
    ordered = sorted(parties.values(), key=lambda p: p.outstanding, reverse=True)
    return Receivables(
        outstanding=sum((p.outstanding for p in ordered), Decimal(0)),
        overdue=sum((p.overdue for p in ordered), Decimal(0)),
        parties=ordered,
    )
