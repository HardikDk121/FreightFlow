"""What each LR is owed: its total less every collection allocated to it that has not failed.
The one place balances are worked out, so receipts, receivables and the dashboard agree."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Collection, CollectionAllocation, Lr, LrCharge, MoneyReceipt


def payer_of(lr: Lr) -> str:
    """Who pays: the consignee on a to-pay LR, otherwise the consignor."""
    return lr.consignee_name if lr.freight_by == "ToPay" else lr.consignor_name


def charges_subquery():
    """lr_id -> charges added at the destination (labour, door delivery, demurrage) on receipts not cancelled."""
    return (
        select(LrCharge.lr_id, func.sum(LrCharge.amount).label("charges"))
        .join(MoneyReceipt, MoneyReceipt.id == LrCharge.receipt_id)
        .where(MoneyReceipt.status != "cancelled")
        .group_by(LrCharge.lr_id)
        .subquery()
    )


def charges_by_lr(session: Session, lr_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    if not lr_ids:
        return {}
    charges = charges_subquery()
    rows = session.execute(select(charges.c.lr_id, charges.c.charges).where(charges.c.lr_id.in_(lr_ids))).all()
    return {lr_id: amount for lr_id, amount in rows}


def paid_subquery():
    """lr_id -> amount received, counting every collection except failed ones."""
    return (
        select(CollectionAllocation.lr_id, func.sum(CollectionAllocation.amount).label("paid"))
        .join(Collection, Collection.id == CollectionAllocation.collection_id)
        .where(Collection.status != "failed")
        .group_by(CollectionAllocation.lr_id)
        .subquery()
    )


def paid_by_lr(session: Session, lr_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    if not lr_ids:
        return {}
    paid = paid_subquery()
    rows = session.execute(select(paid.c.lr_id, paid.c.paid).where(paid.c.lr_id.in_(lr_ids))).all()
    return {lr_id: amount for lr_id, amount in rows}


def balances(session: Session, lrs: list[Lr]) -> dict[uuid.UUID, Decimal]:
    ids = [lr.id for lr in lrs]
    paid, charges = paid_by_lr(session, ids), charges_by_lr(session, ids)
    return {lr.id: lr.total + charges.get(lr.id, Decimal(0)) - paid.get(lr.id, Decimal(0)) for lr in lrs}


def payer_open_lrs(session: Session, payer: str) -> list[tuple[Lr, Decimal]]:
    """The payer's confirmed LRs that still owe something, oldest first, with what each owes."""
    paid, charges = paid_subquery(), charges_subquery()
    owed = Lr.total + func.coalesce(charges.c.charges, 0) - func.coalesce(paid.c.paid, 0)
    payer_column = func.lower(func.trim(func.coalesce(Lr.consignee_name, "")))
    consignor = func.lower(func.trim(Lr.consignor_name))
    key = payer.strip().lower()
    rows = session.execute(
        select(Lr, owed)
        .outerjoin(paid, paid.c.lr_id == Lr.id)
        .outerjoin(charges, charges.c.lr_id == Lr.id)
        .where(Lr.status == "confirmed", owed > 0)
        .where(
            ((Lr.freight_by == "ToPay") & (payer_column == key)) | ((Lr.freight_by != "ToPay") & (consignor == key))
        )
        .order_by(Lr.lr_date, Lr.series_no)
    ).all()
    return [(lr, amount) for lr, amount in rows]
