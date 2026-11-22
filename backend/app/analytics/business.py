"""Analyses of the hired-truck side of the business and of customer contracts: what each trip
earned after paying the truck owner, how each owner performs, how quotes compare, and whether
LRs follow the agreed rates."""

import datetime as dt
import uuid
from collections import defaultdict
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import contracts as contract_rules
from app.analytics import stats
from app.analytics.facts import Fact, Filters, days_between, load
from app.clock import start_of, today
from app.hire import service as hire
from app.models import Contract, DispatchLine, Rfq, RfqInvite, RfqQuote, TransitTime, Trip, Vendor

ZERO = Decimal(0)
LOW_MARGIN_PCT = 5


def _trips(session: Session, f: Filters) -> list[Trip]:
    query = select(Trip).where(
        Trip.dispatched_at >= start_of(f.date_from), Trip.dispatched_at < start_of(f.date_to + dt.timedelta(days=1))
    ).order_by(Trip.dispatched_at)
    if f.branch_id:
        query = query.where(Trip.branch_id == f.branch_id)
    if f.destination:
        query = query.where(func.upper(Trip.destination) == f.destination.strip().upper())
    return list(session.scalars(query))


def transit_times(session: Session) -> dict[str, tuple[int, int]]:
    return {t.destination: (t.days_min, t.days_max) for t in session.scalars(select(TransitTime))}


# ---------------------------------------------------------------- trip profit


class RouteMargin(BaseModel):
    destination: str
    trips: int
    revenue: Decimal
    hire: Decimal
    margin: Decimal
    margin_pct: float | None


class TripProfit(BaseModel):
    basis: str
    trips_with_hire: int
    trips_without_hire: int
    revenue: Decimal
    hire: Decimal
    expenses: Decimal
    deductions: Decimal
    margin: Decimal
    margin_pct: float | None
    hire_share_pct: float | None
    by_destination: list[RouteMargin]
    trips: list[hire.TripMoney]


def priced_trips(session: Session, f: Filters) -> tuple[list[hire.TripMoney], int]:
    """Trips in the period with a recorded hire, and how many have none yet."""
    money = hire.trip_money_many(session, _trips(session, f))
    priced = [m for m in money if m.hire is not None]
    return priced, len(money) - len(priced)


def trip_profit(session: Session, f: Filters) -> TripProfit:
    priced, unpriced = priced_trips(session, f)
    revenue = sum((m.revenue for m in priced), ZERO)
    hired = sum((m.hire for m in priced), ZERO)
    margin = sum((m.margin for m in priced), ZERO)
    routes: dict[str, list] = defaultdict(list)
    for m in priced:
        routes[m.destination].append(m)
    by_destination = sorted(
        (
            RouteMargin(
                destination=d, trips=len(ms), revenue=sum((m.revenue for m in ms), ZERO), hire=sum((m.hire for m in ms), ZERO),
                margin=sum((m.margin for m in ms), ZERO),
                margin_pct=stats.ratio(sum((m.margin for m in ms), ZERO) * 100, sum((m.revenue for m in ms), ZERO), 1),
            )
            for d, ms in routes.items()
        ),
        key=lambda r: r.margin_pct if r.margin_pct is not None else 0,
    )
    return TripProfit(
        basis=f"Trips dispatched {f.date_from:%d-%m-%Y} to {f.date_to:%d-%m-%Y}. Revenue is each LR's total (with charges at delivery) "
        "shared by the packages on the trip. Margin = revenue - hire + deductions - office expenses. Trips without a recorded hire are left out.",
        trips_with_hire=len(priced),
        trips_without_hire=unpriced,
        revenue=revenue,
        hire=hired,
        expenses=sum((m.expenses for m in priced), ZERO),
        deductions=sum((m.deductions for m in priced), ZERO),
        margin=margin,
        margin_pct=stats.ratio(margin * 100, revenue, 1),
        hire_share_pct=stats.ratio(hired * 100, revenue, 1),
        by_destination=by_destination,
        trips=sorted(priced, key=lambda m: m.margin_pct if m.margin_pct is not None else 0)[:100],
    )


# ---------------------------------------------------------------- truck owners


class VendorRow(BaseModel):
    vendor: str
    kind: str
    trips: int
    revenue_carried: Decimal
    hire: Decimal
    hire_share_pct: float | None
    margin_pct: float | None
    on_time_pct: float | None
    deductions: Decimal
    owed_now: Decimal
    quotes_given: int
    quotes_won: int
    win_rate_pct: float | None


class Vendors(BaseModel):
    basis: str
    rows: list[VendorRow]


def vendors(session: Session, f: Filters) -> Vendors:
    trips = _trips(session, f)
    money = {m.trip_id: m for m in hire.trip_money_many(session, trips)}
    usual = transit_times(session)
    unloaded = dict(session.execute(select(DispatchLine.trip_id, func.max(DispatchLine.delivered_at)).group_by(DispatchLine.trip_id)).all())
    owed = {v.vendor_id: v.owed for v in hire.payables(session).vendors}
    rows: dict[uuid.UUID, dict] = {}
    for trip in trips:
        m = money[trip.id]
        if m.vendor_id is None:
            continue
        r = rows.setdefault(m.vendor_id, {"trips": 0, "revenue": ZERO, "hire": ZERO, "margin": ZERO, "deductions": ZERO, "judged": 0, "on_time": 0})
        r["trips"] += 1
        r["revenue"] += m.revenue
        r["hire"] += m.hire
        r["margin"] += m.margin
        r["deductions"] += m.deductions
        window = usual.get(trip.destination.upper())
        if window and trip.status == "completed" and unloaded.get(trip.id):
            r["judged"] += 1
            if days_between(trip.dispatched_at, unloaded[trip.id]) <= window[1]:
                r["on_time"] += 1
    quotes = session.execute(
        select(RfqQuote.vendor_id, func.count(func.distinct(RfqQuote.rfq_id)))
        .join(Rfq, Rfq.id == RfqQuote.rfq_id)
        .where(Rfq.created_at >= start_of(f.date_from), Rfq.created_at < start_of(f.date_to + dt.timedelta(days=1)))
        .group_by(RfqQuote.vendor_id)
    ).all()
    wins = dict(
        session.execute(
            select(RfqQuote.vendor_id, func.count())
            .join(Rfq, Rfq.awarded_quote_id == RfqQuote.id)
            .where(Rfq.created_at >= start_of(f.date_from), Rfq.created_at < start_of(f.date_to + dt.timedelta(days=1)))
            .group_by(RfqQuote.vendor_id)
        ).all()
    )
    given = dict(quotes)
    all_ids = set(rows) | set(given)
    names = {v.id: v for v in session.scalars(select(Vendor).where(Vendor.id.in_(all_ids)))} if all_ids else {}
    out = []
    for vid in all_ids:
        r = rows.get(vid, {"trips": 0, "revenue": ZERO, "hire": ZERO, "margin": ZERO, "deductions": ZERO, "judged": 0, "on_time": 0})
        out.append(
            VendorRow(
                vendor=names[vid].name, kind=names[vid].kind, trips=r["trips"], revenue_carried=r["revenue"], hire=r["hire"],
                hire_share_pct=stats.ratio(r["hire"] * 100, r["revenue"], 1), margin_pct=stats.ratio(r["margin"] * 100, r["revenue"], 1),
                on_time_pct=stats.ratio(r["on_time"] * 100, r["judged"], 1), deductions=r["deductions"], owed_now=owed.get(vid, ZERO),
                quotes_given=given.get(vid, 0), quotes_won=wins.get(vid, 0), win_rate_pct=stats.ratio(wins.get(vid, 0) * 100, given.get(vid, 0), 1),
            )
        )
    out.sort(key=lambda r: r.trips, reverse=True)
    return Vendors(
        basis=f"Trips dispatched {f.date_from:%d-%m-%Y} to {f.date_to:%d-%m-%Y}; quotes on requests made in the same dates. "
        "On time: unloaded within the longest usual transit time for the destination (only destinations with a usual time are judged). "
        "Owed now is across all trips.",
        rows=out,
    )


# ---------------------------------------------------------------- quotes (RFQ and bidding)


class RfqSummary(BaseModel):
    basis: str
    requests: int
    awarded: int
    cancelled: int
    open: int
    vendors_invited: int
    quotes_received: int
    response_rate_pct: float | None
    avg_quotes_per_request: float | None
    awarded_total: Decimal
    # What awarding saved against the highest latest quote, and against each winner's own first quote.
    saved_vs_highest: Decimal
    saved_by_revisions: Decimal
    median_hours_to_award: float | None


def rfqs(session: Session, f: Filters) -> RfqSummary:
    query = select(Rfq).where(Rfq.created_at >= start_of(f.date_from), Rfq.created_at < start_of(f.date_to + dt.timedelta(days=1)))
    if f.destination:
        query = query.where(Rfq.destination == f.destination.strip().upper())
    requests = list(session.scalars(query))
    ids = [r.id for r in requests]
    invites = session.scalar(select(func.count()).select_from(RfqInvite).where(RfqInvite.rfq_id.in_(ids))) if ids else 0
    quotes = list(session.scalars(select(RfqQuote).where(RfqQuote.rfq_id.in_(ids)).order_by(RfqQuote.received_at))) if ids else []
    responders = {(q.rfq_id, q.vendor_id) for q in quotes}
    by_rfq: dict[uuid.UUID, dict[uuid.UUID, list[RfqQuote]]] = defaultdict(lambda: defaultdict(list))
    for q in quotes:
        by_rfq[q.rfq_id][q.vendor_id].append(q)
    awarded_total = saved_highest = saved_revisions = ZERO
    hours = []
    for r in requests:
        if r.status != "awarded":
            continue
        winner = session.get_one(RfqQuote, r.awarded_quote_id)
        latest = [qs[-1].amount for qs in by_rfq[r.id].values()]
        awarded_total += winner.amount
        saved_highest += max(latest) - winner.amount
        saved_revisions += by_rfq[r.id][winner.vendor_id][0].amount - winner.amount
        hours.append(round((r.closed_at - r.created_at).total_seconds() / 3600, 1))
    return RfqSummary(
        basis=f"Requests for quotes made {f.date_from:%d-%m-%Y} to {f.date_to:%d-%m-%Y}. A vendor's latest quote counts; revisions are kept.",
        requests=len(requests),
        awarded=sum(1 for r in requests if r.status == "awarded"),
        cancelled=sum(1 for r in requests if r.status == "cancelled"),
        open=sum(1 for r in requests if r.status == "open"),
        vendors_invited=invites,
        quotes_received=len(responders),
        response_rate_pct=stats.ratio(len(responders) * 100, invites, 1),
        avg_quotes_per_request=stats.ratio(len(responders), len(requests), 1),
        awarded_total=awarded_total,
        saved_vs_highest=saved_highest,
        saved_by_revisions=saved_revisions,
        median_hours_to_award=stats.median(hours),
    )


# ---------------------------------------------------------------- contracts


class OffRate(BaseModel):
    lr_number: str
    lr_date: dt.date
    destination: str
    charged: str
    agreed: str


class ContractRow(BaseModel):
    party: str
    starts_on: dt.date
    ends_on: dt.date
    status: str
    days_left: int
    destinations: int
    lrs: int
    revenue: Decimal
    on_rate: int
    off_rate: list[OffRate]
    # Bookings for this customer after the contract ended (should it be renewed?).
    lrs_after_expiry: int


class Contracts(BaseModel):
    basis: str
    rows: list[ContractRow]


def _charged(x: Fact) -> tuple[str, Decimal]:
    return (x.charge_basis or "per_kg", x.rate)


def contracts(session: Session, f: Filters) -> Contracts:
    day = today()
    facts = load(session, f.model_copy(update={"customer": None, "customer_role": "payer"}))
    by_payer: dict[str, list[Fact]] = defaultdict(list)
    for x in facts:
        by_payer[x.payer.lower()].append(x)
    rows = []
    for c in session.scalars(select(Contract).where(Contract.starts_on <= f.date_to, Contract.ends_on >= f.date_from - dt.timedelta(days=366))):
        read = contract_rules.read(session, c, day)
        agreed = {r.destination: r for r in read.rates}
        lrs, on_rate, off = [], 0, []
        for x in by_payer.get(c.party_name.lower(), []):
            if c.starts_on <= x.lr_date <= c.ends_on and x.destination in agreed:
                lrs.append(x)
                basis, rate = _charged(x)
                rule = agreed[x.destination]
                if basis == rule.basis and rate == rule.rate:
                    on_rate += 1
                else:
                    off.append(OffRate(lr_number=x.lr_number, lr_date=x.lr_date, destination=x.destination,
                                       charged=f"{rate} {basis.replace('_', ' ')}", agreed=f"{rule.rate} {rule.basis.replace('_', ' ')}"))
        after = sum(1 for x in by_payer.get(c.party_name.lower(), []) if x.lr_date > c.ends_on)
        rows.append(
            ContractRow(
                party=c.party_name, starts_on=c.starts_on, ends_on=c.ends_on, status=read.status, days_left=read.days_left,
                destinations=len(agreed), lrs=len(lrs), revenue=sum((x.revenue for x in lrs), ZERO), on_rate=on_rate, off_rate=off[:50],
                lrs_after_expiry=after,
            )
        )
    rows.sort(key=lambda r: (r.status not in ("expiring", "expired"), r.days_left))
    return Contracts(
        basis=f"{f.describe()}. An LR is under a contract when its payer, date and destination match. "
        "Off rate: charged on a different basis or rate from the agreed one.",
        rows=rows,
    )
