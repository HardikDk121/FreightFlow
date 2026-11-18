import datetime as dt
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.chat.interpreter import HELP, REFUSAL, Reply, ToolCall, interpret, is_write_request
from app.chat.llm import interpret_with_model
from app.chat.schemas import ChatResponse
from app.clock import today
from app.dispatch import service as dispatch_service
from app.dispatch.schemas import PendingLr
from app.models import Challan, DispatchLine, Lr, Trip, Truck, User

# (answer, LR numbers used, questions worth asking next)
Answer = tuple[str, list[str], list[str]]

_STARTERS = ["What is pending?", "What was booked today?", "Which trucks are on the road?"]


def _days(n: int) -> str:
    return f"{n} day{'' if n == 1 else 's'}"


def _num(value: Decimal) -> str:
    """100.00 -> "100", 12.50 -> "12.5"."""
    return f"{value.normalize():f}"


def _money(value: Decimal) -> str:
    return f"Rs. {value:,.2f}"


def _pending_lines(rows: list[PendingLr]) -> str:
    return "\n".join(
        f"• {r.lr_number}: {r.pending} of {r.packages} packages for {r.consignee_name}, waiting {_days(r.days_waiting)}"
        for r in rows
    )


def pending_by_destination(session: Session, destination: str) -> Answer:
    rows = dispatch_service.pending_lrs(session, destination=destination)
    city = destination.upper()
    if not rows:
        return f"Nothing is pending for {city}.", [], ["What is pending?"]
    total = sum(r.pending for r in rows)
    return (
        f"{total} packages on {len(rows)} LR{'' if len(rows) == 1 else 's'} are pending for {city}, oldest first:\n"
        f"{_pending_lines(rows)}",
        [r.lr_number for r in rows],
        [f"Details of {rows[0].lr_number}", "Which goods have waited more than 3 days?"],
    )


def pending_older_than(session: Session, days: int) -> Answer:
    rows = dispatch_service.pending_lrs(session, older_than_days=days)
    if not rows:
        return f"No goods have waited more than {_days(days)}.", [], ["What is pending?"]
    return (
        f"{len(rows)} LR{'' if len(rows) == 1 else 's'} waiting more than {_days(days)}:\n{_pending_lines(rows)}",
        [r.lr_number for r in rows],
        [f"Details of {rows[0].lr_number}", "Which trucks are on the road?"],
    )


def pending_summary(session: Session) -> Answer:
    groups = dispatch_service.pending_destinations(session)
    if not groups:
        return "Nothing is pending. Every booked LR has been dispatched.", [], ["What was booked today?"]
    lines = "\n".join(
        f"• {g.to_city}: {g.packages} packages on {g.lr_count} LR{'' if g.lr_count == 1 else 's'}, "
        f"oldest waiting {_days(g.days_waiting)}"
        for g in groups
    )
    total = sum(g.packages for g in groups)
    return (
        f"{total} packages are pending across {len(groups)} destination{'' if len(groups) == 1 else 's'}:\n{lines}",
        [],
        [f"What is pending for {groups[0].to_city.title()}?", "Which goods have waited more than 3 days?"],
    )


def _lr_lines(lrs: list[Lr]) -> str:
    return "\n".join(
        f"• {lr.lr_number}: {lr.packages} packages of {lr.goods_description}, "
        f"{lr.consignor_name} to {lr.consignee_name}, {lr.to_city}"
        for lr in lrs
    )


def arrivals_on_date(session: Session, date: dt.date) -> Answer:
    lrs = list(session.scalars(select(Lr).where(Lr.lr_date == date, Lr.status == "confirmed").order_by(Lr.series_no)))
    label = "today" if date == today() else f"on {date.strftime('%d-%m-%Y')}"
    if not lrs:
        return f"No LRs were booked {label}.", [], ["What is pending?"]
    packages = sum(lr.packages for lr in lrs)
    return (
        f"{len(lrs)} LR{'' if len(lrs) == 1 else 's'} with {packages} packages booked {label}:\n{_lr_lines(lrs)}",
        [lr.lr_number for lr in lrs],
        [f"Details of {lrs[0].lr_number}", "What is pending?"],
    )


def recent_lrs(session: Session) -> Answer:
    lrs = list(session.scalars(select(Lr).order_by(Lr.created_at.desc()).limit(5)))
    if not lrs:
        return "No LRs have been booked yet.", [], []
    return f"The last {len(lrs)} LRs:\n{_lr_lines(lrs)}", [lr.lr_number for lr in lrs], [f"Details of {lrs[0].lr_number}"]


def search_lrs(session: Session, party: str) -> Answer:
    lrs = list(
        session.scalars(
            select(Lr)
            .where(or_(Lr.consignor_name.icontains(party, autoescape=True), Lr.consignee_name.icontains(party, autoescape=True)))
            .order_by(Lr.created_at.desc())
            .limit(10)
        )
    )
    if not lrs:
        return f"I found no LRs with a party named like “{party}”.", [], ["Show recent LRs"]
    return (
        f"{len(lrs)} LR{'' if len(lrs) == 1 else 's'} for “{party}”, newest first:\n{_lr_lines(lrs)}",
        [lr.lr_number for lr in lrs],
        [f"Details of {lrs[0].lr_number}"],
    )


def _trips_of(session: Session, lr: Lr) -> list[str]:
    """One line per trip that carried this LR: truck, driver, dates, packages."""
    rows = session.execute(
        select(DispatchLine, Trip, Truck.vehicle_number, Challan)
        .join(Trip, Trip.id == DispatchLine.trip_id)
        .join(Truck, Truck.id == Trip.truck_id)
        .join(Challan, Challan.id == DispatchLine.challan_id)
        .where(DispatchLine.lr_id == lr.id)
        .order_by(Trip.dispatched_at)
    ).all()
    lines = []
    for line, trip, vehicle, challan in rows:
        driver = f", driver {trip.driver_name}" if trip.driver_name else ""
        delivered = f", delivered {line.delivered_at.strftime('%d-%m-%Y')}" if line.delivered_at else ", not yet delivered"
        # Cargo added on the road is on a supplementary challan, issued where it was loaded.
        added = f", added at {challan.loaded_at} on challan {challan.challan_number}" if challan.seq else f", challan {challan.challan_number}"
        lines.append(
            f"{line.packages} packages on truck {vehicle} to {trip.destination}{driver}, "
            f"left {trip.dispatched_at.strftime('%d-%m-%Y')}{added}{delivered}"
        )
    return lines


def find_goods(session: Session, goods: str, packages: int | None = None) -> Answer:
    """LRs by what was carried, however long ago, with the trips that carried them."""
    query = select(Lr).where(Lr.goods_description.icontains(goods, autoescape=True), Lr.status == "confirmed")
    if packages is not None:
        query = query.where(Lr.packages == packages)
    lrs = list(session.scalars(query.order_by(Lr.created_at.desc()).limit(5)))
    what = f"{packages} packages of {goods}" if packages is not None else goods
    if not lrs:
        return f"I found no LR for {what}.", [], ["Show recent LRs"]
    blocks = []
    for lr in lrs:
        trips = _trips_of(session, lr) or ["Not dispatched yet"]
        eway = f", e-way bill {lr.eway_bill_no}" if lr.eway_bill_no else ""
        blocks.append(
            f"• {lr.lr_number}, booked {lr.lr_date.strftime('%d-%m-%Y')}: {lr.packages} packages of "
            f"{lr.goods_description}, {lr.consignor_name} to {lr.consignee_name}, {lr.to_city}{eway}\n"
            + "\n".join(f"   {trip}" for trip in trips)
        )
    return (
        f"{len(lrs)} LR{'' if len(lrs) == 1 else 's'} for {what}, newest first:\n" + "\n".join(blocks),
        [lr.lr_number for lr in lrs],
        [f"Details of {lrs[0].lr_number}"],
    )


def _lr_state(session: Session, lr: Lr) -> str:
    if lr.status == "cancelled":
        return f"Cancelled. Reason: {lr.cancel_reason}"
    sent, delivered = session.execute(
        select(
            func.coalesce(func.sum(DispatchLine.packages), 0),
            func.coalesce(func.sum(DispatchLine.packages).filter(DispatchLine.delivered_at.is_not(None)), 0),
        ).where(DispatchLine.lr_id == lr.id)
    ).one()
    if sent == 0:
        return f"All {lr.packages} packages are pending in the godown, waiting {_days((today() - lr.lr_date).days)}."
    if delivered == lr.packages:
        return f"All {lr.packages} packages are delivered."
    return f"{sent} of {lr.packages} packages dispatched, {delivered} delivered, {lr.packages - sent} pending."


def lr_details(session: Session, lr_number: str, fields: list[str]) -> Answer:
    """One LR. With `fields`, only what was asked about (plus where the goods are); without, everything."""
    lr = session.scalar(select(Lr).where(func.upper(Lr.lr_number) == lr_number.upper()))
    if lr is None:
        return f"I could not find LR {lr_number}. Check the number in the LRs tab.", [], ["Show recent LRs"]
    n = lr.lr_number
    weight = (
        "Weight was not recorded."
        if lr.weight is None
        else f"Weight {_num(lr.weight)} kg"
        + (f", charged weight {_num(lr.charged_weight)} kg." if lr.charged_weight is not None else ".")
    )
    charges = (
        f"Rate {_money(lr.rate)}, freight {_money(lr.freight)}, hamali {_money(lr.hamali)}, "
        f"other {_money(lr.other_charges)}, ST {_money(lr.st_charges)}. Total {_money(lr.total)}, {lr.freight_by}."
    )
    parts = {
        "parties": f"From {lr.consignor_name}"
        + (f" ({lr.consignor_gstin})" if lr.consignor_gstin else "")
        + f" to {lr.consignee_name}"
        + (f" ({lr.consignee_gstin})" if lr.consignee_gstin else "")
        + f", {lr.from_city} to {lr.to_city}.",
        "date": f"Booked on {lr.lr_date.strftime('%d-%m-%Y')}.",
        "goods": f"{lr.packages} packages of {lr.goods_description}.",
        "packages": f"{lr.packages} packages of {lr.goods_description}.",
        "weight": weight,
        "value": "Value was not recorded." if lr.value is None else f"Goods value {_money(lr.value)}.",
        "charges": charges,
        "eway": "No e-way bill number was recorded." if lr.eway_bill_no is None else f"E-way bill {lr.eway_bill_no}.",
        "status": " ".join([_lr_state(session, lr), *(f"{trip}." for trip in _trips_of(session, lr))]),
    }
    if fields:
        chosen = list(dict.fromkeys(parts[f] for f in fields))
        if "status" not in fields:
            chosen.append(parts["status"])
    else:
        chosen = [parts[k] for k in ("parties", "date", "goods", "weight", "value", "charges", "eway", "status")]
    suggestions = [q for q in (f"Weight of {n}", f"Charges on {n}", f"What is pending for {lr.to_city.title()}?")
                   if not (fields == ["weight"] and q.startswith("Weight")) and not (fields == ["charges"] and q.startswith("Charges"))]
    return f"LR {n}\n" + "\n".join(chosen), [n], suggestions


def _trip_line(session: Session, trip: Trip, vehicle: str) -> str:
    total, delivered = session.execute(
        select(func.count(), func.count(DispatchLine.delivered_at)).where(DispatchLine.trip_id == trip.id)
    ).one()
    driver = f", driver {trip.driver_name}" if trip.driver_name else ""
    return f"• {vehicle} to {trip.destination}{driver}: {delivered} of {total} LRs delivered"


def trips_on_road(session: Session) -> Answer:
    rows = session.execute(
        select(Trip, Truck.vehicle_number)
        .join(Truck, Truck.id == Trip.truck_id)
        .where(Trip.status == "dispatched")
        .order_by(Trip.dispatched_at)
    ).all()
    if not rows:
        return "No trucks are on the road right now.", [], ["What is pending?"]
    lines = "\n".join(_trip_line(session, trip, vehicle) for trip, vehicle in rows)
    return f"{len(rows)} truck{'' if len(rows) == 1 else 's'} on the road:\n{lines}", [], ["What is pending?"]


def truck_status(session: Session, vehicle_number: str) -> Answer:
    truck = session.scalar(select(Truck).where(Truck.vehicle_number == vehicle_number))
    if truck is None:
        return f"I could not find a truck numbered {vehicle_number}.", [], ["Which trucks are on the road?"]
    trip = session.scalar(select(Trip).where(Trip.truck_id == truck.id).order_by(Trip.dispatched_at.desc()).limit(1))
    if trip is None:
        return f"{vehicle_number} has not been sent on a trip yet.", [], ["Which trucks are on the road?"]
    if trip.status == "completed":
        return (
            f"{vehicle_number} is free. Its last trip, to {trip.destination}, was completed on "
            f"{trip.completed_at.strftime('%d-%m-%Y')}.",
            [],
            ["Which trucks are on the road?"],
        )
    return f"{vehicle_number} is on the road:\n{_trip_line(session, trip, vehicle_number)}", [], ["What is pending?"]


# The complete list of things the assistant can do. Every entry only reads.
TOOLS: dict[str, Callable[..., Answer]] = {
    "pending_by_destination": pending_by_destination,
    "pending_older_than": pending_older_than,
    "pending_summary": pending_summary,
    "arrivals_on_date": arrivals_on_date,
    "recent_lrs": recent_lrs,
    "search_lrs": search_lrs,
    "find_goods": find_goods,
    "lr_details": lr_details,
    "trips_on_road": trips_on_road,
    "truck_status": truck_status,
}


def ask(session: Session, user: User, message: str, context_lr_number: str | None) -> ChatResponse:
    cities = frozenset(session.scalars(select(func.lower(Lr.to_city)).distinct()))
    # Requests to change data are refused before any model sees them.
    result = None
    if not is_write_request(message):
        result = interpret_with_model(message, today(), cities, context_lr_number) or interpret(
            message, today(), cities, context_lr_number
        )
    if isinstance(result, ToolCall):
        answer, lr_numbers, suggestions = TOOLS[result.tool](session, **result.args)
        response = ChatResponse(answer=answer, tool=result.tool, lr_numbers=lr_numbers, suggestions=suggestions)
    elif isinstance(result, Reply):
        response = ChatResponse(answer=result.text, tool=None, lr_numbers=[], suggestions=_STARTERS)
    else:
        text = REFUSAL if is_write_request(message) else HELP
        response = ChatResponse(answer=text, tool=None, lr_numbers=[], suggestions=_STARTERS)
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
            "args": {k: str(v) for k, v in result.args.items()} if isinstance(result, ToolCall) else None,
            "lr_numbers": response.lr_numbers,
        },
    )
    return response
