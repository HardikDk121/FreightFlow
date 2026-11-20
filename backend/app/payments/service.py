import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import today
from app.collections import balances, credit
from app.delivery import service as delivery_service
from app.errors import not_found
from app.models import Collection, CollectionAllocation, CreditTerms, DispatchLine, Lr, MoneyReceipt, User
from app.payments.schemas import (
    Ageing,
    AgeingRow,
    LatePayer,
    LimitUse,
    LrAccount,
    OverdueLr,
    PartyOutstanding,
    PaymentRead,
    Priorities,
    Receivables,
)

class _Terms:
    """Each payer's terms and the company's credit start, looked up once per request."""

    def __init__(self, session: Session):
        self._session = session
        self._cache: dict[str, CreditTerms | None] = {}
        self.credit_from: str | None = None

    def due_on(self, lr: Lr, delivered_on: dt.date | None) -> dt.date | None:
        if self.credit_from is None:
            self.credit_from = credit.settings_of(self._session, lr.company_id).credit_from
        payer = balances.payer_of(lr).strip().lower()
        if payer not in self._cache:
            self._cache[payer] = credit.terms_for(self._session, payer)
        return credit.due_on(lr, delivered_on, self._cache[payer], self.credit_from)


def _account(lr: Lr, paid: Decimal, due_on: dt.date | None, payments: list[PaymentRead], charges: Decimal = Decimal(0)) -> LrAccount:
    total = lr.total + charges
    balance = total - paid
    return LrAccount(
        lr_id=lr.id,
        lr_number=lr.lr_number,
        lr_date=lr.lr_date,
        freight_by=lr.freight_by,
        payer=balances.payer_of(lr),
        total=total,
        paid=paid,
        balance=balance,
        due_on=due_on,
        overdue=balance > 0 and due_on is not None and due_on < today(),
        payments=payments,
    )


def _delivered_on(session: Session, lr: Lr) -> dt.date | None:
    """When the consignee signed for the goods (proof of delivery). For LRs delivered before gate passes
    were recorded in the app: the day the last package was unloaded, or None while any is still pending."""
    signed = delivery_service.delivered_on(session, lr.id)
    if signed is not None:
        return signed
    sent, delivered, last = session.execute(
        select(
            func.coalesce(func.sum(DispatchLine.packages), 0),
            func.coalesce(func.sum(DispatchLine.packages).filter(DispatchLine.delivered_at.is_not(None)), 0),
            func.max(DispatchLine.delivered_at),
        ).where(DispatchLine.lr_id == lr.id)
    ).one()
    return last.date() if sent == lr.packages and delivered == lr.packages else None


def lr_account(session: Session, lr_id: uuid.UUID) -> LrAccount:
    lr = session.get(Lr, lr_id)
    if lr is None:
        raise not_found("LR")
    rows = session.execute(
        select(CollectionAllocation.amount, Collection, MoneyReceipt.receipt_number, User.name)
        .join(Collection, Collection.id == CollectionAllocation.collection_id)
        .join(User, User.id == Collection.collected_by)
        .outerjoin(MoneyReceipt, MoneyReceipt.id == Collection.receipt_id)
        .where(CollectionAllocation.lr_id == lr.id)
        .order_by(Collection.collected_at)
    ).all()
    payments = [
        PaymentRead(
            collection_id=c.id,
            amount=amount,
            method=c.method,
            status=c.status,
            reference=c.utr or (f"{c.cheque_bank} {c.cheque_number}" if c.cheque_number else None),
            receipt_number=receipt_number,
            collected_by=name,
            collected_on=c.collected_at.date(),
        )
        for amount, c, receipt_number, name in rows
    ]
    paid = sum((p.amount for p in payments if p.status != "failed"), Decimal(0))
    charges = balances.charges_by_lr(session, [lr.id]).get(lr.id, Decimal(0))
    return _account(lr, paid, _Terms(session).due_on(lr, _delivered_on(session, lr)), payments, charges)


def open_accounts(session: Session, party: str | None = None) -> list[LrAccount]:
    """Every confirmed LR with money still owed, oldest first; optionally for one payer."""
    paid, charges = balances.paid_subquery(), balances.charges_subquery()
    rows = session.execute(
        select(Lr, func.coalesce(paid.c.paid, 0), func.coalesce(charges.c.charges, 0))
        .outerjoin(paid, paid.c.lr_id == Lr.id)
        .outerjoin(charges, charges.c.lr_id == Lr.id)
        .where(Lr.status == "confirmed", Lr.total + func.coalesce(charges.c.charges, 0) > func.coalesce(paid.c.paid, 0))
        .order_by(Lr.lr_date, Lr.series_no)
    ).all()
    terms = _Terms(session)
    if party is not None:
        rows = [row for row in rows if balances.payer_of(row[0]).lower() == party.strip().lower()]
    return [
        _account(lr, Decimal(paid_amount), terms.due_on(lr, _delivered_on(session, lr)), [], Decimal(extra))
        for lr, paid_amount, extra in rows
    ]


def receivables(session: Session) -> Receivables:
    """Outstanding money by payer, the largest first."""
    parties: dict[str, PartyOutstanding] = {}
    for account in open_accounts(session):
        key = account.payer.lower()
        entry = parties.get(key)
        if entry is None:
            terms = credit.terms_for(session, account.payer)
            entry = parties[key] = PartyOutstanding(
                party=account.payer,
                lr_count=0,
                outstanding=Decimal(0),
                overdue=Decimal(0),
                oldest_lr_date=account.lr_date,
                payment_terms=terms.payment_terms if terms else "at_delivery",
                credit_days=terms.credit_days if terms else None,
                credit_limit=terms.credit_limit if terms else None,
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


_BUCKETS = (("days_0_7", 7), ("days_8_15", 15), ("days_16_30", 30), ("days_31_60", 60))


def ageing(session: Session) -> Ageing:
    """Money owed by how long past its due date, per customer."""
    rows: dict[str, AgeingRow] = {}
    day = today()
    for account in open_accounts(session):
        row = rows.get(account.payer.lower())
        if row is None:
            row = rows[account.payer.lower()] = AgeingRow(party=account.payer)
        if account.due_on is None or account.due_on >= day:
            row.not_due += account.balance
        else:
            late = (day - account.due_on).days
            bucket = next((name for name, upto in _BUCKETS if late <= upto), "days_60_plus")
            setattr(row, bucket, getattr(row, bucket) + account.balance)
        row.total += account.balance
    ordered = sorted(rows.values(), key=lambda r: r.total - r.not_due, reverse=True)
    totals = AgeingRow(party="All customers")
    for row in ordered:
        for field in AgeingRow.model_fields:
            if field != "party":
                setattr(totals, field, getattr(totals, field) + getattr(row, field))
    return Ageing(rows=ordered, totals=totals)


def priorities(session: Session) -> Priorities:
    """Where the money is stuck: the biggest debts, the oldest overdue LRs, customers at or over their
    credit limit, and customers who repeatedly pay late."""
    day = today()
    owed = receivables(session)
    accounts = open_accounts(session)
    overdue = sorted((a for a in accounts if a.overdue), key=lambda a: a.due_on)
    near_limit = []
    for p in owed.parties:
        if p.credit_limit:
            used = round(p.outstanding * 100 / p.credit_limit)
            if used >= 80:
                near_limit.append(LimitUse(party=p.party, outstanding=p.outstanding, credit_limit=p.credit_limit, used_pct=used))
    # Late payers: LRs fully paid in the last 180 days, and how many days after their due date.
    paid_lrs = session.execute(
        select(Lr, func.max(Collection.collected_at))
        .join(CollectionAllocation, CollectionAllocation.lr_id == Lr.id)
        .join(Collection, Collection.id == CollectionAllocation.collection_id)
        .where(Lr.status == "confirmed", Collection.status != "failed", Collection.collected_at >= day - dt.timedelta(days=180))
        .group_by(Lr.id)
    ).all()
    paid_by = balances.paid_by_lr(session, [lr.id for lr, _ in paid_lrs])
    terms = _Terms(session)
    delays: dict[str, list[int]] = {}
    for lr, last_paid in paid_lrs:
        if paid_by.get(lr.id, Decimal(0)) < lr.total:
            continue
        due = terms.due_on(lr, _delivered_on(session, lr))
        if due is not None:
            delays.setdefault(balances.payer_of(lr), []).append(max(0, (last_paid.date() - due).days))
    late_payers = sorted(
        (
            LatePayer(party=party, lrs_paid=len(days), lrs_paid_late=sum(1 for d in days if d > 0), average_days_late=round(sum(days) / len(days)))
            for party, days in delays.items()
            if sum(1 for d in days if d > 0) >= 2
        ),
        key=lambda p: p.average_days_late,
        reverse=True,
    )
    return Priorities(
        largest=owed.parties[:5],
        oldest_overdue=[
            OverdueLr(party=a.payer, lr_number=a.lr_number, balance=a.balance, days_overdue=(day - a.due_on).days)
            for a in overdue[:5]
        ],
        near_limit=sorted(near_limit, key=lambda x: x.used_pct, reverse=True),
        late_payers=late_payers[:5],
    )
