import datetime as dt
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.chat.interpreter import HELP, REFUSAL, interpret, is_write_request
from app.chat.schemas import ChatResponse
from app.clock import today
from app.dispatch import service as dispatch_service
from app.dispatch.schemas import PendingLr
from app.models import DispatchLine, Lr, User

Answer = tuple[str, list[str]]  # (text, LR numbers used)


def _lines(rows: list[PendingLr]) -> str:
    return "\n".join(
        f"- {r.lr_number}: {r.pending} of {r.packages} packages, {r.consignee_name}, {r.to_city}, "
        f"waiting {r.days_waiting} day{'' if r.days_waiting == 1 else 's'}"
        for r in rows
    )


def pending_by_destination(session: Session, destination: str) -> Answer:
    rows = dispatch_service.pending_lrs(session, destination=destination)
    if not rows:
        return f"Nothing is pending for {destination.upper()}.", []
    return f"Pending for {destination.upper()}, oldest first:\n{_lines(rows)}", [r.lr_number for r in rows]


def pending_older_than(session: Session, days: int) -> Answer:
    rows = dispatch_service.pending_lrs(session, older_than_days=days)
    if not rows:
        return f"No goods have waited more than {days} days.", []
    return f"Waiting more than {days} days:\n{_lines(rows)}", [r.lr_number for r in rows]


def pending_summary(session: Session) -> Answer:
    groups = dispatch_service.pending_destinations(session)
    if not groups:
        return "Nothing is pending.", []
    text = "\n".join(
        f"- {g.to_city}: {g.packages} packages on {g.lr_count} LR{'' if g.lr_count == 1 else 's'}, "
        f"oldest waiting {g.days_waiting} day{'' if g.days_waiting == 1 else 's'}"
        for g in groups
    )
    return f"Pending by destination:\n{text}", []


def arrivals_on_date(session: Session, date: dt.date) -> Answer:
    lrs = session.scalars(
        select(Lr).where(Lr.lr_date == date, Lr.status == "confirmed").order_by(Lr.series_no)
    ).all()
    label = date.strftime("%d-%m-%Y")
    if not lrs:
        return f"No LRs were booked on {label}.", []
    text = "\n".join(
        f"- {lr.lr_number}: {lr.packages} packages of {lr.goods_description}, "
        f"{lr.consignor_name} to {lr.consignee_name}, {lr.to_city}"
        for lr in lrs
    )
    return f"Booked on {label}:\n{text}", [lr.lr_number for lr in lrs]


def lr_status(session: Session, lr_number: str) -> Answer:
    lr = session.scalar(select(Lr).where(func.upper(Lr.lr_number) == lr_number.upper()))
    if lr is None:
        return f"I could not find LR {lr_number}.", []
    route = f"{lr.consignor_name} to {lr.consignee_name}, {lr.to_city}"
    if lr.status == "cancelled":
        return f"LR {lr.lr_number} ({route}) is cancelled. Reason: {lr.cancel_reason}", [lr.lr_number]
    sent, delivered = session.execute(
        select(
            func.coalesce(func.sum(DispatchLine.packages), 0),
            func.coalesce(func.sum(DispatchLine.packages).filter(DispatchLine.delivered_at.is_not(None)), 0),
        ).where(DispatchLine.lr_id == lr.id)
    ).one()
    if sent == 0:
        waited = (today() - lr.lr_date).days
        state = f"all {lr.packages} packages are pending, waiting {waited} day{'' if waited == 1 else 's'}"
    elif delivered == lr.packages:
        state = f"all {lr.packages} packages are delivered"
    else:
        state = f"{sent} of {lr.packages} packages dispatched, {delivered} delivered, {lr.packages - sent} pending"
    return f"LR {lr.lr_number} ({route}): {state}.", [lr.lr_number]


# The complete list of things the assistant can do. Every entry only reads.
TOOLS: dict[str, Callable[..., Answer]] = {
    "pending_by_destination": pending_by_destination,
    "pending_older_than": pending_older_than,
    "pending_summary": pending_summary,
    "arrivals_on_date": arrivals_on_date,
    "lr_status": lr_status,
}


def ask(session: Session, user: User, message: str) -> ChatResponse:
    call = interpret(message, today())
    if call is None:
        response = ChatResponse(answer=REFUSAL if is_write_request(message) else HELP, tool=None, lr_numbers=[])
    else:
        answer, lr_numbers = TOOLS[call.tool](session, **call.args)
        response = ChatResponse(answer=answer, tool=call.tool, lr_numbers=lr_numbers)
    audit.record(
        session,
        company_id=user.company_id,
        actor_id=user.id,
        action="chat.ask",
        entity="chat",
        entity_id=user.id,
        detail={
            "message": message,
            "tool": response.tool,
            "args": {k: str(v) for k, v in call.args.items()} if call else None,
            "lr_numbers": response.lr_numbers,
        },
    )
    return response
