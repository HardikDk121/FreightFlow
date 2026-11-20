"""Payment reminders, sent by the app on a schedule instead of when someone remembers.

For each customer: a reminder two days before money falls due, one on the day, and one every
seven days while it stays overdue. Each is sent once (a unique index makes a second run a no-op)
and kept as history, whether or not it could be sent. Customers whose terms say no reminders are
left out."""

import datetime as dt
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.clock import today
from app.collections import credit
from app.db import get_session
from app.models import Company, MoneyReceipt, Party, Reminder, User
from app.notify import Outbox, get_outbox
from app.permissions import P, require

BEFORE_DUE_DAYS = 2
OVERDUE_EVERY_DAYS = 7


class ReminderRead(BaseModel):
    payer_name: str
    phone: str
    kind: str
    channel: str
    amount: Decimal
    status: str
    reason: str | None
    sent_on: dt.date


def phone_for(session: Session, payer: str) -> str | None:
    """The customer's number: from the party master, else the last money receipt that had one."""
    key = payer.strip().lower()
    phone = session.scalar(select(Party.phone).where(func.lower(Party.name) == key, Party.phone.is_not(None)).limit(1))
    return phone or session.scalar(
        select(MoneyReceipt.payer_phone)
        .where(func.lower(MoneyReceipt.payer_name) == key, MoneyReceipt.payer_phone.is_not(None))
        .order_by(MoneyReceipt.issued_at.desc())
        .limit(1)
    )


def run(session: Session, outbox: Outbox, company_id) -> int:
    """Send today's reminders. Returns how many were recorded."""
    from app.payments.service import open_accounts

    day = today()
    company = session.get_one(Company, company_id)
    due: dict[str, dict] = {}
    for a in open_accounts(session):
        if a.due_on is None:
            continue
        kind = None
        if a.due_on == day + dt.timedelta(days=BEFORE_DUE_DAYS):
            kind = "before_due"
        elif a.due_on == day:
            kind = "due"
        elif a.due_on < day:
            kind = "overdue"
        if kind is None:
            continue
        entry = due.setdefault(a.payer.strip().lower(), {"name": a.payer, "kinds": {}, "oldest": a.due_on, "lrs": []})
        entry["kinds"][kind] = entry["kinds"].get(kind, Decimal(0)) + a.balance
        entry["oldest"] = min(entry["oldest"], a.due_on)
        entry["lrs"].append(a.lr_number)
    sent = 0
    for entry in due.values():
        terms = credit.terms_for(session, entry["name"])
        if terms is not None and not terms.reminders:
            continue
        phone = phone_for(session, entry["name"])
        if phone is None:
            continue
        for kind, amount in entry["kinds"].items():
            if kind == "overdue" and (day - entry["oldest"]).days % OVERDUE_EVERY_DAYS != 1:
                continue  # the first overdue reminder goes the day after, then weekly
            when = {"before_due": f"is due on {day + dt.timedelta(days=BEFORE_DUE_DAYS):%d-%m-%Y}", "due": "is due today", "overdue": "is overdue"}[kind]
            body = (
                f"{company.name}: Rs {amount:,.2f} for LR {', '.join(entry['lrs'][:5])} {when}. "
                + (f"Pay to: {' '.join(company.bank_details.splitlines())}. " if company.bank_details else "")
                + (f"Questions: {company.phone}." if company.phone else "")
            )
            for channel, send in (("sms", outbox.sms), ("whatsapp", outbox.whatsapp)):
                # Insert first: if this reminder already went today, nothing is sent again.
                inserted = session.execute(
                    insert(Reminder)
                    .values(
                        id=uuid.uuid4(), company_id=company_id, payer_name=entry["name"], phone=phone,
                        kind=kind, channel=channel, amount=amount, body=body, status="not_sent", sent_on=day,
                    )
                    .on_conflict_do_nothing()
                    .returning(Reminder.id)
                ).first()
                if inserted is None:
                    continue
                ok = send(phone, body)
                reminder = session.get_one(Reminder, inserted[0])
                reminder.status = "sent" if ok else "not_sent"
                reminder.reason = None if ok else f"No {channel} provider is configured yet."
                sent += 1
    session.flush()
    return sent


router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.post("/run")
def run_now(
    actor: User = Depends(require(P.MONEY_OVERVIEW)), session: Session = Depends(get_session), outbox: Outbox = Depends(get_outbox)
) -> dict[str, int]:
    """Send today's reminders now (the daily job does this on its own). Running twice sends nothing new."""
    return {"recorded": run(session, outbox, actor.company_id)}


@router.get("", response_model=list[ReminderRead])
def history(
    payer: str | None = Query(default=None, max_length=60),
    _: User = Depends(require(P.MONEY_RECEIVABLES)),
    session: Session = Depends(get_session),
) -> list[ReminderRead]:
    query = select(Reminder).order_by(Reminder.created_at.desc()).limit(200)
    if payer:
        query = query.where(func.lower(Reminder.payer_name) == payer.strip().lower())
    return [ReminderRead.model_validate(r, from_attributes=True) for r in session.scalars(query)]
