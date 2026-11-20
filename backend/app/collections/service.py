"""Collecting money from customers so that no single person controls what was due, what was paid,
and what reached the company.

  due        LRs booked (and sealed) in Rajkot
  paid       a money receipt issued by the app, a visit, and a collection the customer is told about
  arrived    the bank statement: UPI by its UTR, cash and cheques through a counted handover and a deposit

Collections, handovers and deposits are never edited; corrections are new records (a failed
collection, a shortage decision).
"""

import datetime as dt
import base64
import hashlib
import hmac
import uuid
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit, branches, tasks
from app.clock import start_of, today
from app.collections import balances
from app.config import get_settings
from app.collections.schemas import (
    CollectionRead,
    CreditTermsRead,
    CreditTermsUpsert,
    Custody,
    CustodyItem,
    DepositCreate,
    DepositRead,
    Alert,
    HandoverCreate,
    HandoverRead,
    Overview,
    PaymentIn,
    ReceiptCreate,
    ReceiptLineRead,
    ReceiptRead,
    ReceiptVerification,
    ShortageDecision,
    ShortageRead,
    VisitCreate,
    VisitRead,
)
from app.db import set_tenant
from app.errors import AppError, conflict, forbidden, not_found
from app.lr import service as lr_service
from app.models import (
    BankDeposit,
    BankStatementLine,
    CashHandover,
    Collection,
    CollectionAllocation,
    CollectionVisit,
    Company,
    CreditTerms,
    CustomerNotice,
    Lr,
    LrCharge,
    MoneyReceipt,
    MoneyReceiptLine,
    ReleaseApproval,
    Shortage,
    User,
)
from app.notify import Outbox
from app.permissions import P, has
from app.payments.service import receivables
from app.security import utcnow

# Cash of this much or more from one person in a day, or for one transaction, may not be received
# (Income-tax Act, 2025, section 186; formerly section 269ST of the 1961 Act).
LEGAL_CASH_LIMIT = Decimal("200000")

_PAISE = Decimal("0.01")


_VERIFY_LOOKUP = text("SELECT id, company_id FROM receipt_by_verify_hash(:h)")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(receipt_id: uuid.UUID) -> str:
    """The token in a receipt's verification QR. Derived from the server's secret, so the receipt can be
    printed again with the same QR; only its hash is stored, and it cannot be guessed from the number."""
    digest = hmac.new(get_settings().jwt_secret.encode(), f"receipt:{receipt_id}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode()


def _names(session: Session, ids) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    return dict(session.execute(select(User.id, User.name).where(User.id.in_(ids))).all())


# ---------------------------------------------------------------------------- receipts


def _custody_of(c: Collection, deposits: dict[uuid.UUID, BankDeposit], handovers: dict[uuid.UUID, CashHandover]) -> str:
    if c.status == "failed":
        return "failed"
    if c.status == "legacy":
        return "legacy"
    if c.method in ("upi", "bank_transfer"):
        return "in_bank" if c.status == "confirmed" else "awaiting_bank"
    deposit_id = c.deposit_id or (handovers[c.handover_id].deposit_id if c.handover_id in handovers else None)
    if c.status == "confirmed" or (deposit_id and deposits.get(deposit_id) and deposits[deposit_id].status == "banked"):
        return "in_bank"
    if deposit_id:
        return "deposited"
    return "handed_over" if c.handover_id else "with_collector"


def _collection_reads(session: Session, collections: list[Collection]) -> list[CollectionRead]:
    receipts = dict(
        session.execute(
            select(MoneyReceipt.id, MoneyReceipt.receipt_number).where(
                MoneyReceipt.id.in_({c.receipt_id for c in collections if c.receipt_id})
            )
        ).all()
    )
    handovers = {
        h.id: h
        for h in session.scalars(select(CashHandover).where(CashHandover.id.in_({c.handover_id for c in collections if c.handover_id})))
    }
    deposit_ids = {c.deposit_id for c in collections if c.deposit_id} | {h.deposit_id for h in handovers.values() if h.deposit_id}
    deposits = {d.id: d for d in session.scalars(select(BankDeposit).where(BankDeposit.id.in_(deposit_ids)))}
    names = _names(session, (c.collected_by for c in collections))
    return [
        CollectionRead(
            id=c.id,
            receipt_number=receipts.get(c.receipt_id),
            payer_name=c.payer_name,
            method=c.method,
            amount=c.amount,
            utr=c.utr,
            cheque_number=c.cheque_number,
            cheque_bank=c.cheque_bank,
            collected_by=names.get(c.collected_by, ""),
            collected_at=c.collected_at,
            status=c.status,
            custody=_custody_of(c, deposits, handovers),
            failed_reason=c.failed_reason,
        )
        for c in collections
    ]


def _receipt_read(session: Session, receipt: MoneyReceipt, token: str | None = None) -> ReceiptRead:
    lines = session.execute(
        select(MoneyReceiptLine, Lr).join(Lr, Lr.id == MoneyReceiptLine.lr_id).where(MoneyReceiptLine.receipt_id == receipt.id)
    ).all()
    owed = balances.balances(session, [lr for _, lr in lines])
    charges: dict[tuple[uuid.UUID, str], Decimal] = {
        (c.lr_id, c.kind): c.amount for c in session.scalars(select(LrCharge).where(LrCharge.receipt_id == receipt.id))
    }
    visits = list(
        session.scalars(select(CollectionVisit).where(CollectionVisit.receipt_id == receipt.id).order_by(CollectionVisit.visited_at))
    )
    collections = list(
        session.scalars(select(Collection).where(Collection.receipt_id == receipt.id).order_by(Collection.collected_at))
    )
    # What is left is what the receipt's LRs still owe, however it was paid: on this receipt, by a
    # bank transfer allocated later, or on another receipt.
    left = min(receipt.amount, sum((owed[lr.id] for _, lr in lines), Decimal(0)))
    balance = left if receipt.status == "open" else Decimal(0)
    collected = receipt.amount - balance if receipt.status != "cancelled" else Decimal(0)
    names = _names(session, [receipt.issued_by, *(v.collector_id for v in visits)])
    last_promise = next((v.promised_on for v in reversed(visits) if v.outcome != "refused"), None) if visits else None
    return ReceiptRead(
        id=receipt.id,
        receipt_number=receipt.receipt_number,
        payer_name=receipt.payer_name,
        payer_phone=receipt.payer_phone,
        amount=receipt.amount,
        collected=collected,
        balance=balance,
        status=receipt.status,
        issued_by=names.get(receipt.issued_by, ""),
        issued_at=receipt.issued_at,
        cancel_reason=receipt.cancel_reason,
        promised_on=last_promise if receipt.status == "open" else None,
        lines=[
            ReceiptLineRead(
                lr_id=lr.id,
                lr_number=lr.lr_number,
                lr_date=lr.lr_date,
                from_city=lr.from_city.upper(),
                to_city=lr.to_city.upper(),
                packages=lr.packages,
                weight=lr.weight,
                freight=lr.freight + lr.hamali + lr.other_charges,
                labour=charges.get((lr.id, "labour"), Decimal(0)),
                dc_charge=charges.get((lr.id, "dc_charge"), Decimal(0)),
                demurrage=charges.get((lr.id, "demurrage"), Decimal(0)),
                st_charge=lr.st_charges,
                amount=line.amount,
                balance=owed[lr.id],
            )
            for line, lr in sorted(lines, key=lambda row: (row[1].lr_date, row[1].series_no))
        ],
        visits=[
            VisitRead(
                id=v.id,
                collector=names.get(v.collector_id, ""),
                visited_at=v.visited_at,
                outcome=v.outcome,
                promised_on=v.promised_on,
                note=v.note,
            )
            for v in visits
        ],
        collections=_collection_reads(session, collections),
        verify_token=token,
    )


def issue_receipt(session: Session, actor: User, data: ReceiptCreate) -> ReceiptRead:
    """A numbered receipt for one payer's LRs. The amount is what the LRs owe right now; nobody types it."""
    lrs = session.scalars(select(Lr).where(Lr.id.in_(data.lr_ids)).order_by(Lr.id).with_for_update()).all()
    if len(lrs) != len(data.lr_ids):
        raise not_found("LR")
    payers = {balances.payer_of(lr).strip().lower() for lr in lrs}
    if len(payers) > 1:
        raise conflict("A receipt is for one payer. These LRs are paid by different parties.")
    owed = balances.balances(session, list(lrs))
    for lr in lrs:
        if lr.status != "confirmed":
            raise conflict(f"LR {lr.lr_number} is cancelled.")
        if owed[lr.id] <= 0:
            raise conflict(f"LR {lr.lr_number} has nothing left to collect.")
    already = session.scalar(
        select(MoneyReceipt.receipt_number)
        .join(MoneyReceiptLine, MoneyReceiptLine.receipt_id == MoneyReceipt.id)
        .where(MoneyReceiptLine.lr_id.in_(data.lr_ids), MoneyReceipt.status == "open")
        .limit(1)
    )
    if already is not None:
        raise conflict(f"Money receipt {already} is already open for one of these LRs.")
    extra: dict[uuid.UUID, Decimal] = {}
    for charge in data.charges:
        if charge.lr_id not in owed:
            raise conflict("A destination charge is for an LR that is not on this receipt.")
        extra[charge.lr_id] = extra.get(charge.lr_id, Decimal(0)) + charge.amount
    if len({(c.lr_id, c.kind) for c in data.charges}) != len(data.charges):
        raise conflict("Each charge can be added once per LR.")
    receipt_id = uuid.uuid4()
    token = verify_token(receipt_id)
    receipt = MoneyReceipt(
        id=receipt_id,
        company_id=actor.company_id,
        branch_id=branches.lr_branch(lrs[0]),
        receipt_number=lr_service.take_document_number(session, actor.company_id, "receipt"),
        payer_name=balances.payer_of(lrs[0]),
        payer_phone=data.payer_phone,
        amount=sum(owed.values(), Decimal(0)) + sum(extra.values(), Decimal(0)),
        status="open",
        verify_hash=_hash(token),
        issued_by=actor.id,
    )
    session.add(receipt)
    session.flush()
    session.add_all(
        MoneyReceiptLine(
            company_id=actor.company_id, receipt_id=receipt.id, lr_id=lr.id, amount=owed[lr.id] + extra.get(lr.id, Decimal(0))
        )
        for lr in lrs
    )
    session.add_all(
        LrCharge(
            company_id=actor.company_id,
            lr_id=c.lr_id,
            receipt_id=receipt.id,
            kind=c.kind,
            amount=c.amount.quantize(_PAISE),
            added_by=actor.id,
        )
        for c in data.charges
    )
    session.flush()
    session.refresh(receipt)
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="receipt.issue",
        entity="money_receipt",
        entity_id=receipt.id,
        detail={
            "receipt_number": receipt.receipt_number,
            "amount": str(receipt.amount),
            "lrs": [lr.lr_number for lr in lrs],
            "charges": [{"lr_id": str(c.lr_id), "kind": c.kind, "amount": str(c.amount)} for c in data.charges],
        },
    )
    return _receipt_read(session, receipt, token)


def _locked_receipt(session: Session, receipt_id: uuid.UUID) -> MoneyReceipt:
    receipt = session.get(MoneyReceipt, receipt_id, with_for_update=True)
    if receipt is None:
        raise not_found("Money receipt")
    return receipt


def get_receipt(session: Session, receipt_id: uuid.UUID) -> ReceiptRead:
    receipt = session.get(MoneyReceipt, receipt_id)
    if receipt is None:
        raise not_found("Money receipt")
    return _receipt_read(session, receipt)


def list_receipts(session: Session, *, status: str | None, limit: int, offset: int) -> list[ReceiptRead]:
    query = select(MoneyReceipt).order_by(MoneyReceipt.issued_at.desc()).limit(limit).offset(offset)
    if status is not None:
        query = query.where(MoneyReceipt.status == status)
    return [_receipt_read(session, r) for r in session.scalars(query)]


def cancel_receipt(session: Session, actor: User, receipt_id: uuid.UUID, reason: str) -> ReceiptRead:
    """Withdraw a receipt nothing has been collected on. Its number stays used."""
    receipt = _locked_receipt(session, receipt_id)
    if receipt.status != "open":
        raise conflict("Only an open receipt can be cancelled.")
    if session.scalar(select(Collection.id).where(Collection.receipt_id == receipt.id).limit(1)) is not None:
        raise conflict("Money has been recorded on this receipt, so it cannot be cancelled.")
    receipt.status = "cancelled"
    receipt.cancelled_by = actor.id
    receipt.cancelled_at = utcnow()
    receipt.cancel_reason = reason
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="receipt.cancel",
        entity="money_receipt",
        entity_id=receipt.id,
        detail={"receipt_number": receipt.receipt_number, "reason": reason},
    )
    return _receipt_read(session, receipt)


def verify(session: Session, token: str) -> ReceiptVerification:
    """For whoever scans the printed receipt: is it real, and what does the company's record say?"""
    row = session.execute(_VERIFY_LOOKUP, {"h": _hash(token)}).first()
    if row is None:
        raise not_found("Money receipt")
    set_tenant(session, row.company_id)
    receipt = session.get_one(MoneyReceipt, row.id)
    read = _receipt_read(session, receipt)
    return ReceiptVerification(
        company_name=session.get_one(Company, receipt.company_id).name,
        receipt_number=read.receipt_number,
        payer_name=read.payer_name,
        lr_numbers=[line.lr_number for line in read.lines],
        amount=read.amount,
        collected=read.collected,
        status=read.status,
        issued_on=read.issued_at.date(),
    )


# ---------------------------------------------------------------------------- visits and collections


def _allocate(session: Session, collection: Collection, lrs: list[Lr], amount: Decimal) -> None:
    """Spread the money over the LRs oldest first, never beyond what each still owes."""
    owed = balances.balances(session, lrs)
    left = amount
    for lr in sorted(lrs, key=lambda x: (x.lr_date, x.series_no)):
        part = min(left, owed[lr.id])
        if part <= 0:
            continue
        session.add(
            CollectionAllocation(company_id=collection.company_id, collection_id=collection.id, lr_id=lr.id, amount=part)
        )
        left -= part
        if left == 0:
            break
    if left > 0:
        raise conflict(f"Rs {left:,.2f} more than these LRs owe. Take the excess as a separate advance.")
    session.flush()


def _check_cash(session: Session, actor: User, receipt: MoneyReceipt, amount: Decimal) -> None:
    # The owner (and anyone given the permission) may take any amount; others have the per-receipt limit.
    if not has(actor, P.CASH_ANY_AMOUNT):
        limit = lr_service.collector_cash_limit(session, actor.company_id)
        taken = session.scalar(
            select(func.coalesce(func.sum(Collection.amount), 0)).where(
                Collection.receipt_id == receipt.id, Collection.method == "cash", Collection.status != "failed"
            )
        )
        if taken + amount > limit:
            raise conflict(
                f"Cash over Rs {limit:,.0f} on one receipt goes to the owner or the bank. "
                "Ask for UPI, a cheque or a bank transfer."
            )
    today_cash = session.scalar(
        select(func.coalesce(func.sum(Collection.amount), 0)).where(
            func.lower(Collection.payer_name) == receipt.payer_name.lower(),
            Collection.method == "cash",
            Collection.status != "failed",
            Collection.collected_at >= start_of(today()),
        )
    )
    if today_cash + amount >= LEGAL_CASH_LIMIT:
        raise conflict(
            "Cash of Rs 2,00,000 or more from one customer in a day is not allowed by law. "
            "Take the rest by UPI, cheque or bank transfer."
        )


def _notify(session: Session, outbox: Outbox, collection: Collection, receipt: MoneyReceipt | None, phone: str | None) -> None:
    """Tell the customer what was recorded, so an under-recorded amount is seen by the person who paid it."""
    if phone is None:
        return
    company = session.get_one(Company, collection.company_id)
    lr_numbers = session.scalars(
        select(Lr.lr_number)
        .join(CollectionAllocation, CollectionAllocation.lr_id == Lr.id)
        .where(CollectionAllocation.collection_id == collection.id)
        .order_by(Lr.lr_number)
    ).all()
    owing = sum((amount for _, amount in balances.payer_open_lrs(session, collection.payer_name)), Decimal(0))
    method = {"cash": "in cash", "upi": "by UPI", "cheque": "by cheque", "bank_transfer": "by bank transfer"}[collection.method]
    collector = session.get_one(User, collection.collected_by).name
    body = (
        f"{company.name}: Rs {collection.amount:,.2f} received {method} for LR {', '.join(lr_numbers)}"
        + (f", receipt {receipt.receipt_number}" if receipt else "")
        + f", recorded by {collector}. You now owe Rs {owing:,.2f}."
        + (f" Not right? Call {company.phone}." if company.phone else "")
    )
    for channel, send in (("sms", outbox.sms), ("whatsapp", outbox.whatsapp)):
        sent = send(phone, body)
        session.add(
            CustomerNotice(
                company_id=collection.company_id,
                collection_id=collection.id,
                channel=channel,
                phone=phone,
                body=body,
                status="sent" if sent else "not_sent",
                reason=None if sent else f"No {channel} provider is configured yet.",
            )
        )
    session.flush()


def record_visit(
    session: Session, actor: User, outbox: Outbox, receipt_id: uuid.UUID, data: VisitCreate
) -> ReceiptRead:
    """What happened when the collector called: paid, part paid, come later, or refused."""
    receipt = _locked_receipt(session, receipt_id)
    if receipt.status != "open":
        raise conflict(f"Receipt {receipt.receipt_number} is {receipt.status}.")
    if data.promised_on is not None and data.promised_on < today():
        raise AppError(422, "past_promise", "The promised date cannot be in the past.")
    read = _receipt_read(session, receipt)
    payment: PaymentIn | None = data.payment
    if payment is not None:
        if payment.amount > read.balance:
            raise conflict(f"Only Rs {read.balance:,.2f} is left on receipt {receipt.receipt_number}.")
        if data.outcome == "paid" and payment.amount != read.balance:
            raise AppError(422, "not_full", f"Paid in full means Rs {read.balance:,.2f}. Record a part payment instead.")
        if data.outcome == "part_paid" and payment.amount == read.balance:
            raise AppError(422, "is_full", "That is the full balance. Record it as paid.")
        if payment.method == "cash":
            _check_cash(session, actor, receipt, payment.amount)
    visit = CollectionVisit(
        company_id=actor.company_id,
        receipt_id=receipt.id,
        collector_id=actor.id,
        outcome=data.outcome,
        promised_on=data.promised_on,
        note=data.note,
    )
    session.add(visit)
    session.flush()
    collection = None
    if payment is not None:
        collection = Collection(
            company_id=actor.company_id,
            branch_id=receipt.branch_id,
            receipt_id=receipt.id,
            visit_id=visit.id,
            payer_name=receipt.payer_name,
            method=payment.method,
            amount=payment.amount.quantize(_PAISE),
            utr=payment.utr,
            cheque_number=payment.cheque_number,
            cheque_bank=payment.cheque_bank,
            cheque_date=payment.cheque_date,
            collected_by=actor.id,
            status="pending",
        )
        session.add(collection)
        try:
            with session.begin_nested():
                session.flush()
        except IntegrityError as exc:  # the unique index on UTR or cheque number
            raise conflict("This UTR or cheque has already been recorded against another payment.") from exc
        lrs = session.scalars(
            select(Lr).join(MoneyReceiptLine, MoneyReceiptLine.lr_id == Lr.id).where(MoneyReceiptLine.receipt_id == receipt.id)
        ).all()
        _allocate(session, collection, list(lrs), payment.amount)
        settle_paid_receipts(session, [lr.id for lr in lrs])
        _notify(session, outbox, collection, receipt, receipt.payer_phone)
    tasks.note_visit(session, actor, receipt.branch_id, receipt.payer_name, data.outcome, data.promised_on, data.note)
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="receipt.visit",
        entity="money_receipt",
        entity_id=receipt.id,
        detail={
            "receipt_number": receipt.receipt_number,
            "outcome": data.outcome,
            "amount": str(payment.amount) if payment else None,
            "method": payment.method if payment else None,
        },
    )
    return _receipt_read(session, receipt)


def settle_paid_receipts(session: Session, lr_ids: list[uuid.UUID]) -> None:
    """Close every open receipt for these LRs whose LRs no longer owe anything."""
    receipts = session.scalars(
        select(MoneyReceipt)
        .join(MoneyReceiptLine, MoneyReceiptLine.receipt_id == MoneyReceipt.id)
        .where(MoneyReceiptLine.lr_id.in_(lr_ids), MoneyReceipt.status == "open")
        .distinct()
    ).all()
    for receipt in receipts:
        lrs = session.scalars(
            select(Lr).join(MoneyReceiptLine, MoneyReceiptLine.lr_id == Lr.id).where(MoneyReceiptLine.receipt_id == receipt.id)
        ).all()
        if all(owed <= 0 for owed in balances.balances(session, list(lrs)).values()):
            receipt.status = "settled"
    session.flush()


def allocate_transfer(
    session: Session, actor: User, outbox: Outbox, line: BankStatementLine, payer: str, lr_ids: list[uuid.UUID] | None
) -> CollectionRead:
    """A customer paid straight into the bank: record it against their LRs, oldest first unless
    particular LRs are given, and tell them."""
    open_lrs = balances.payer_open_lrs(session, payer)
    if not open_lrs:
        raise conflict(f"{payer} owes nothing.")
    lrs = [lr for lr, _ in open_lrs if lr_ids is None or lr.id in lr_ids]
    if lr_ids is not None and len(lrs) != len(set(lr_ids)):
        raise conflict(f"Some of those LRs are not {payer}'s, or owe nothing.")
    collection = Collection(
        company_id=actor.company_id,
        branch_id=branches.lr_branch(lrs[0]),
        payer_name=lrs[0].consignee_name if lrs[0].freight_by == "ToPay" else lrs[0].consignor_name,
        method="bank_transfer",
        amount=line.credit,
        utr=None,
        collected_by=actor.id,
        status="confirmed",
        confirmed_at=utcnow(),
        bank_line_id=line.id,
    )
    session.add(collection)
    session.flush()
    _allocate(session, collection, lrs, line.credit)
    settle_paid_receipts(session, [lr.id for lr in lrs])
    phone = session.scalar(
        select(MoneyReceipt.payer_phone)
        .where(func.lower(MoneyReceipt.payer_name) == payer.strip().lower(), MoneyReceipt.payer_phone.is_not(None))
        .order_by(MoneyReceipt.issued_at.desc())
        .limit(1)
    )
    _notify(session, outbox, collection, None, phone)
    return _collection_reads(session, [collection])[0]


def fail_collection(session: Session, actor: User, collection_id: uuid.UUID, reason: str) -> CollectionRead:
    """A cheque bounced or a UPI payment was reversed: the amount is owed again."""
    collection = session.get(Collection, collection_id, with_for_update=True)
    if collection is None:
        raise not_found("Collection")
    if collection.status in ("failed", "legacy") or collection.method == "cash":
        raise conflict("Only a cheque, UPI or bank payment can be marked as failed.")
    collection.status = "failed"
    collection.failed_reason = reason
    collection.confirmed_at = None
    session.flush()
    # The money is owed again, so a receipt it settled is open again.
    lr_ids = session.scalars(select(CollectionAllocation.lr_id).where(CollectionAllocation.collection_id == collection.id)).all()
    for receipt in session.scalars(
        select(MoneyReceipt)
        .join(MoneyReceiptLine, MoneyReceiptLine.receipt_id == MoneyReceipt.id)
        .where(MoneyReceiptLine.lr_id.in_(lr_ids), MoneyReceipt.status == "settled")
        .distinct()
    ):
        receipt.status = "open"
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="collection.fail",
        entity="collection",
        entity_id=collection.id,
        detail={"amount": str(collection.amount), "reason": reason},
    )
    return _collection_reads(session, [collection])[0]


# ---------------------------------------------------------------------------- custody, handover, deposit


def _own_in_hand(session: Session, user_id: uuid.UUID, *, lock: bool = False) -> list[Collection]:
    query = select(Collection).where(
        Collection.collected_by == user_id,
        Collection.method.in_(("cash", "cheque")),
        Collection.status == "pending",
        Collection.handover_id.is_(None),
        Collection.deposit_id.is_(None),
    )
    return list(session.scalars(query.with_for_update() if lock else query))


def _received_in_hand(session: Session, user_id: uuid.UUID, *, lock: bool = False) -> tuple[list[CashHandover], list[Collection]]:
    """Handovers this person received and has not banked, and the cheques that came with them."""
    query = select(CashHandover).where(CashHandover.to_user == user_id, CashHandover.deposit_id.is_(None))
    handovers = list(session.scalars(query.with_for_update() if lock else query))
    cheques = list(
        session.scalars(
            select(Collection).where(
                Collection.handover_id.in_([h.id for h in handovers]),
                Collection.method == "cheque",
                Collection.deposit_id.is_(None),
                Collection.status == "pending",
            )
        )
    )
    return handovers, cheques


def custody(session: Session, user: User) -> Custody:
    own = _own_in_hand(session, user.id)
    handovers, received_cheques = _received_in_hand(session, user.id)
    items = [
        CustodyItem(
            collection_id=c.id,
            handover_id=None,
            kind=c.method,
            amount=c.amount,
            payer_name=c.payer_name,
            cheque_number=c.cheque_number,
            since=c.collected_at,
        )
        for c in [*own, *received_cheques]
    ] + [
        CustodyItem(
            collection_id=None, handover_id=h.id, kind="handover", amount=h.counted_cash, payer_name=None, cheque_number=None, since=h.handed_at
        )
        for h in handovers
        if h.counted_cash > 0
    ]
    items.sort(key=lambda i: i.since)
    cheques = [i for i in items if i.kind == "cheque"]
    return Custody(
        user_id=user.id,
        name=user.name,
        cash=sum((i.amount for i in items if i.kind != "cheque"), Decimal(0)),
        cheques=sum((i.amount for i in cheques), Decimal(0)),
        cheque_count=len(cheques),
        oldest=items[0].since if items else None,
        items=items,
    )


def holders(session: Session) -> list[Custody]:
    """Everyone holding cash or cheques, longest-held first."""
    users = session.scalars(select(User).where(User.is_active).order_by(User.name)).all()
    held = [c for c in (custody(session, u) for u in users) if c.items]
    return sorted(held, key=lambda c: c.oldest)


def _shortage(
    session: Session, actor: User, user_id: uuid.UUID, amount: Decimal, source: str, source_id: uuid.UUID, branch_id: uuid.UUID
) -> None:
    if amount <= 0:
        return
    shortage = Shortage(
        company_id=actor.company_id, branch_id=branch_id, user_id=user_id, amount=amount, source=source, source_id=source_id
    )
    session.add(shortage)
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="shortage.record",
        entity="shortage",
        entity_id=shortage.id,
        detail={"user_id": str(user_id), "amount": str(amount), "source": source},
    )


def _handover_read(session: Session, h: CashHandover) -> HandoverRead:
    names = _names(session, [h.from_user, h.to_user])
    cheque_count = session.scalar(
        select(func.count()).select_from(Collection).where(Collection.handover_id == h.id, Collection.method == "cheque")
    )
    return HandoverRead(
        id=h.id,
        from_name=names[h.from_user],
        to_name=names[h.to_user],
        expected_cash=h.expected_cash,
        counted_cash=h.counted_cash,
        shortage=h.expected_cash - h.counted_cash,
        cheque_count=cheque_count,
        handed_at=h.handed_at,
        from_confirmed_at=h.from_confirmed_at,
    )


def handover(session: Session, actor: User, data: HandoverCreate) -> HandoverRead:
    """The receiver takes everything the collector holds and enters what they actually counted.
    Less than expected is recorded at once as a shortage against the collector."""
    if data.from_user_id == actor.id:
        raise conflict("Someone else must receive your cash.")
    giver = session.get(User, data.from_user_id)
    if giver is None:
        raise not_found("User")
    held = _own_in_hand(session, giver.id, lock=True)
    cash = [c for c in held if c.method == "cash"]
    cheques = {c.id: c for c in held if c.method == "cheque"}
    if not held:
        raise conflict(f"{giver.name} is not holding any cash or cheques.")
    unknown = set(data.cheque_ids) - set(cheques)
    if unknown:
        raise conflict("One of those cheques is not with this person.")
    expected = sum((c.amount for c in cash), Decimal(0))
    if data.counted_cash > expected:
        raise conflict(f"The app expects Rs {expected:,.2f}. Count again: more than that cannot be accepted here.")
    record = CashHandover(
        company_id=actor.company_id,
        branch_id=branches.home_branch(session, giver),
        from_user=giver.id,
        to_user=actor.id,
        expected_cash=expected,
        counted_cash=data.counted_cash.quantize(_PAISE),
    )
    session.add(record)
    session.flush()
    for c in cash:
        c.handover_id = record.id
    for cheque_id in data.cheque_ids:
        cheques[cheque_id].handover_id = record.id
    session.flush()
    _shortage(session, actor, giver.id, expected - record.counted_cash, "handover", record.id, record.branch_id)
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="handover.receive",
        entity="cash_handover",
        entity_id=record.id,
        detail={"from": str(giver.id), "expected": str(expected), "counted": str(data.counted_cash), "cheques": len(data.cheque_ids)},
    )
    return _handover_read(session, record)


def confirm_handover(session: Session, actor: User, handover_id: uuid.UUID) -> HandoverRead:
    """The collector agrees the count. Until then the handover shows as unconfirmed."""
    record = session.get(CashHandover, handover_id, with_for_update=True)
    if record is None:
        raise not_found("Handover")
    if record.from_user != actor.id:
        raise forbidden()
    if record.from_confirmed_at is None:
        record.from_confirmed_at = utcnow()
        session.flush()
    return _handover_read(session, record)


def list_handovers(session: Session, limit: int) -> list[HandoverRead]:
    rows = session.scalars(select(CashHandover).order_by(CashHandover.handed_at.desc()).limit(limit))
    return [_handover_read(session, h) for h in rows]


def _deposit_read(session: Session, d: BankDeposit) -> DepositRead:
    cheques = session.scalars(select(Collection).where(Collection.deposit_id == d.id, Collection.method == "cheque")).all()
    return DepositRead(
        id=d.id,
        deposit_number=d.deposit_number,
        depositor=_names(session, [d.depositor])[d.depositor],
        expected_cash=d.expected_cash,
        cash_amount=d.cash_amount,
        shortage=d.expected_cash - d.cash_amount,
        cheque_count=len(cheques),
        cheque_total=sum((c.amount for c in cheques), Decimal(0)),
        slip_reference=d.slip_reference,
        deposited_at=d.deposited_at,
        status=d.status,
    )


def deposit(session: Session, actor: User, data: DepositCreate) -> DepositRead:
    """Everything the depositor holds in cash goes in one batch; cheques as chosen. Write the batch
    number on the slip so the statement line can be matched to it."""
    own = _own_in_hand(session, actor.id, lock=True)
    handovers, received_cheques = _received_in_hand(session, actor.id, lock=True)
    own_cash = [c for c in own if c.method == "cash"]
    cheques = {c.id: c for c in [*own, *received_cheques] if c.method == "cheque"}
    unknown = set(data.cheque_ids) - set(cheques)
    if unknown:
        raise conflict("One of those cheques is not with you.")
    expected = sum((c.amount for c in own_cash), Decimal(0)) + sum((h.counted_cash for h in handovers), Decimal(0))
    if expected == 0 and not data.cheque_ids:
        raise conflict("You are not holding any cash, and no cheques were chosen.")
    if data.cash_amount > expected:
        raise conflict(f"You hold Rs {expected:,.2f} in cash. A deposit cannot be more than that.")
    record = BankDeposit(
        company_id=actor.company_id,
        branch_id=branches.home_branch(session, actor),
        deposit_number=lr_service.take_document_number(session, actor.company_id, "deposit"),
        depositor=actor.id,
        expected_cash=expected,
        cash_amount=data.cash_amount.quantize(_PAISE),
        slip_reference=data.slip_reference,
        # A cheques-only batch has no cash to find on the statement; each cheque is matched on its own.
        status="in_transit" if data.cash_amount > 0 else "banked",
    )
    session.add(record)
    session.flush()
    for c in own_cash:
        c.deposit_id = record.id
    for h in handovers:
        h.deposit_id = record.id
    for cheque_id in data.cheque_ids:
        cheques[cheque_id].deposit_id = record.id
    session.flush()
    _shortage(session, actor, actor.id, expected - record.cash_amount, "deposit", record.id, record.branch_id)
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="deposit.record",
        entity="bank_deposit",
        entity_id=record.id,
        detail={"number": record.deposit_number, "expected": str(expected), "cash": str(data.cash_amount), "cheques": len(data.cheque_ids)},
    )
    return _deposit_read(session, record)


def list_deposits(session: Session, limit: int) -> list[DepositRead]:
    return [_deposit_read(session, d) for d in session.scalars(select(BankDeposit).order_by(BankDeposit.deposited_at.desc()).limit(limit))]


# ---------------------------------------------------------------------------- credit, release, gate pass


def _terms_read(session: Session, t: CreditTerms) -> CreditTermsRead:
    owing = sum((amount for _, amount in balances.payer_open_lrs(session, t.payer_name)), Decimal(0))
    return CreditTermsRead(
        id=t.id,
        payer_name=t.payer_name,
        payment_terms=t.payment_terms,
        credit_limit=t.credit_limit,
        credit_days=t.credit_days,
        note=t.note,
        reminders=t.reminders,
        is_active=t.is_active,
        outstanding=owing,
        available=max(t.credit_limit - owing, Decimal(0)) if t.credit_limit is not None else None,
        approved_by=_names(session, [t.approved_by])[t.approved_by],
    )


def upsert_credit(session: Session, actor: User, data: CreditTermsUpsert) -> CreditTermsRead:
    terms = session.scalar(select(CreditTerms).where(func.lower(CreditTerms.payer_name) == data.payer_name.lower()))
    if terms is None:
        terms = CreditTerms(company_id=actor.company_id, payer_name=data.payer_name, approved_by=actor.id)
        session.add(terms)
    terms.payment_terms = data.payment_terms
    terms.credit_limit = data.credit_limit
    terms.credit_days = data.credit_days
    terms.note = data.note
    terms.reminders = data.reminders
    terms.is_active = data.is_active
    terms.approved_by = actor.id
    terms.updated_at = utcnow()
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="credit.set",
        entity="credit_terms",
        entity_id=terms.id,
        detail={
            "payer": data.payer_name,
            "terms": data.payment_terms,
            "limit": str(data.credit_limit) if data.credit_limit is not None else None,
            "days": data.credit_days,
            "active": data.is_active,
        },
    )
    return _terms_read(session, terms)


def list_credit(session: Session) -> list[CreditTermsRead]:
    return [_terms_read(session, t) for t in session.scalars(select(CreditTerms).order_by(CreditTerms.payer_name))]


def approve_release(session: Session, actor: User, lr_id: uuid.UUID, reason: str) -> None:
    lr = session.get(Lr, lr_id)
    if lr is None:
        raise not_found("LR")
    if session.scalar(select(ReleaseApproval.id).where(ReleaseApproval.lr_id == lr_id)) is not None:
        raise conflict(f"Release of LR {lr.lr_number} is already approved.")
    approval = ReleaseApproval(company_id=actor.company_id, lr_id=lr_id, reason=reason, approved_by=actor.id)
    session.add(approval)
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="release.approve",
        entity="lr",
        entity_id=lr_id,
        detail={"lr_number": lr.lr_number, "reason": reason},
    )


# ---------------------------------------------------------------------------- shortages


def _shortage_read(s: Shortage, name: str) -> ShortageRead:
    return ShortageRead(
        id=s.id,
        user_id=s.user_id,
        name=name,
        amount=s.amount,
        source=s.source,
        status=s.status,
        salary_month=s.salary_month,
        note=s.note,
        created_at=s.created_at,
    )


def list_shortages(session: Session, status: str | None) -> list[ShortageRead]:
    query = select(Shortage).order_by(Shortage.created_at.desc())
    if status is not None:
        query = query.where(Shortage.status == status)
    rows = list(session.scalars(query))
    names = _names(session, (s.user_id for s in rows))
    return [_shortage_read(s, names[s.user_id]) for s in rows]


def decide_shortage(session: Session, actor: User, shortage_id: uuid.UUID, data: ShortageDecision) -> ShortageRead:
    shortage = session.get(Shortage, shortage_id, with_for_update=True)
    if shortage is None:
        raise not_found("Shortage")
    if shortage.status != "open":
        raise conflict("This shortage has already been decided.")
    shortage.status = data.decision
    shortage.salary_month = data.salary_month.replace(day=1) if data.salary_month else None
    shortage.decided_by = actor.id
    shortage.decided_at = utcnow()
    shortage.note = data.note
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="shortage.decide",
        entity="shortage",
        entity_id=shortage.id,
        detail={"decision": data.decision, "note": data.note},
    )
    return _shortage_read(shortage, _names(session, [shortage.user_id])[shortage.user_id])


# ---------------------------------------------------------------------------- the owner's view


def _sum(session: Session, column, *conditions) -> Decimal:
    return session.scalar(select(func.coalesce(func.sum(column), 0)).where(*conditions))


def overview(session: Session, date_from: dt.date, date_to: dt.date) -> Overview:
    start, end = start_of(date_from), start_of(date_to + dt.timedelta(days=1))
    in_period = (Collection.collected_at >= start, Collection.collected_at < end, Collection.status != "failed")
    custody_rows = holders(session)
    now = utcnow()
    exceptions: list[Alert] = []
    for c in custody_rows:
        if c.oldest and now - c.oldest > dt.timedelta(hours=24):
            exceptions.append(Alert(kind="cash_held", message=f"{c.name} has held Rs {c.cash + c.cheques:,.2f} for over a day.", ref=str(c.user_id)))
    for c in session.scalars(
        select(Collection).where(
            Collection.method == "upi", Collection.status == "pending", Collection.collected_at < now - dt.timedelta(days=2)
        )
    ):
        exceptions.append(
            Alert(kind="upi_unconfirmed", message=f"UPI Rs {c.amount:,.2f} from {c.payer_name} (UTR {c.utr}) is not in the bank statement after 2 days.", ref=str(c.id))
        )
    for d in session.scalars(
        select(BankDeposit).where(BankDeposit.status == "in_transit", BankDeposit.deposited_at < now - dt.timedelta(days=2))
    ):
        exceptions.append(
            Alert(kind="deposit_missing", message=f"Deposit {d.deposit_number} of Rs {d.cash_amount:,.2f} is not in the bank statement after 2 days.", ref=str(d.id))
        )
    open_shortages = session.scalars(select(Shortage).where(Shortage.status == "open")).all()
    names = _names(session, (s.user_id for s in open_shortages))
    for s in open_shortages:
        exceptions.append(Alert(kind="shortage", message=f"Shortage of Rs {s.amount:,.2f} by {names[s.user_id]} at {s.source}, awaiting your decision.", ref=str(s.id)))
    for line in session.scalars(
        select(BankStatementLine).where(BankStatementLine.status == "unmatched", BankStatementLine.credit > 0).order_by(BankStatementLine.txn_date)
    ):
        exceptions.append(Alert(kind="credit_unallocated", message=f"Bank credit Rs {line.credit:,.2f} on {line.txn_date:%d-%m-%Y} is not matched to anything.", ref=str(line.id)))
    for c in session.scalars(
        select(Collection).where(Collection.status == "failed", Collection.collected_at >= now - dt.timedelta(days=30))
    ):
        exceptions.append(Alert(kind="payment_failed", message=f"{c.method.upper()} Rs {c.amount:,.2f} from {c.payer_name} failed: {c.failed_reason}.", ref=str(c.id)))
    latest_visit = (
        select(CollectionVisit.receipt_id, func.max(CollectionVisit.visited_at).label("last"))
        .group_by(CollectionVisit.receipt_id)
        .subquery()
    )
    promised = session.execute(
        select(MoneyReceipt, CollectionVisit)
        .join(latest_visit, latest_visit.c.receipt_id == MoneyReceipt.id)
        .join(CollectionVisit, (CollectionVisit.receipt_id == MoneyReceipt.id) & (CollectionVisit.visited_at == latest_visit.c.last))
        .where(MoneyReceipt.status == "open", CollectionVisit.outcome.in_(("come_later", "refused")))
    ).all()
    for receipt, visit in promised:
        if visit.outcome == "refused":
            exceptions.append(Alert(kind="refused", message=f"{receipt.payer_name} refused to pay on {receipt.receipt_number}: {visit.note}", ref=str(receipt.id)))
        elif visit.promised_on < today():
            exceptions.append(Alert(kind="promise_passed", message=f"{receipt.payer_name} promised to pay {receipt.receipt_number} by {visit.promised_on:%d-%m-%Y}.", ref=str(receipt.id)))
    unannounced = session.scalars(
        select(Collection)
        .join(MoneyReceipt, MoneyReceipt.id == Collection.receipt_id)
        .where(MoneyReceipt.payer_phone.is_(None), Collection.status != "failed", Collection.collected_at >= start, Collection.collected_at < end)
    ).all()
    for c in unannounced:
        exceptions.append(Alert(kind="customer_not_told", message=f"Rs {c.amount:,.2f} from {c.payer_name} was recorded, but the receipt has no phone number, so the customer was not told.", ref=str(c.id)))

    return Overview(
        date_from=date_from,
        date_to=date_to,
        booked=_sum(session, Lr.total, Lr.status == "confirmed", Lr.lr_date >= date_from, Lr.lr_date <= date_to),
        collected_cash=_sum(session, Collection.amount, *in_period, Collection.method == "cash"),
        collected_upi=_sum(session, Collection.amount, *in_period, Collection.method == "upi"),
        collected_cheque=_sum(session, Collection.amount, *in_period, Collection.method == "cheque"),
        received_by_transfer=_sum(session, Collection.amount, *in_period, Collection.method == "bank_transfer"),
        handed_over_expected=_sum(session, CashHandover.expected_cash, CashHandover.handed_at >= start, CashHandover.handed_at < end),
        handed_over_counted=_sum(session, CashHandover.counted_cash, CashHandover.handed_at >= start, CashHandover.handed_at < end),
        banked=_sum(
            session,
            BankStatementLine.credit,
            BankStatementLine.status == "matched",
            BankStatementLine.txn_date >= date_from,
            BankStatementLine.txn_date <= date_to,
        ),
        shortages=_sum(session, Shortage.amount, Shortage.created_at >= start, Shortage.created_at < end),
        receivable=receivables(session).outstanding,
        custody=custody_rows,
        deposits_in_transit=_sum(session, BankDeposit.cash_amount, BankDeposit.status == "in_transit"),
        upi_unconfirmed=_sum(session, Collection.amount, Collection.method == "upi", Collection.status == "pending"),
        cheques_uncleared=_sum(session, Collection.amount, Collection.method == "cheque", Collection.status == "pending"),
        bank_credits_unallocated=_sum(session, BankStatementLine.credit, BankStatementLine.status == "unmatched"),
        exceptions=exceptions,
    )


def daily_summary(session: Session) -> str:
    """The evening message for the owner, replacing the phone call."""
    day = today()
    o = overview(session, day, day)
    held = ", ".join(f"{c.name} Rs {c.cash + c.cheques:,.0f}" for c in o.custody) or "nobody"
    return (
        f"FreightFlow {day:%d-%m-%Y}. Collected: cash Rs {o.collected_cash:,.0f}, UPI Rs {o.collected_upi:,.0f}, "
        f"cheques Rs {o.collected_cheque:,.0f}, transfers Rs {o.received_by_transfer:,.0f}. "
        f"Handed over Rs {o.handed_over_counted:,.0f} of Rs {o.handed_over_expected:,.0f} expected. "
        f"Holding now: {held}. Still owed by customers Rs {o.receivable:,.0f}. "
        f"{len(o.exceptions)} item(s) need your attention."
    )

