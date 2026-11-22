"""The analyses. Each takes the same filters, reads the same LR facts (and, where money moved, the
collection records), and says how its figures were worked out in `basis`."""

import datetime as dt
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import stats
from app.analytics.facts import Fact, Filters, days_between, load
from app.clock import start_of, today
from app.models import Branch, CashHandover, Collection, DispatchLine, Lr, Shortage, TransitTime, Trip, Truck
from app.payments import service as payments

Grain = Literal["day", "week", "month", "quarter", "year"]
ZERO = Decimal(0)


def _sum(values) -> Decimal:
    return sum(values, ZERO)


def _weight(facts: list[Fact]) -> Decimal:
    return _sum(x.chargeable_weight or ZERO for x in facts)


# ---------------------------------------------------------------- overview


class Kpi(BaseModel):
    key: str
    label: str
    value: float | None
    previous: float | None
    change_pct: float | None
    unit: str  # "count", "rupees", "kg", "days", "percent", "rupees_per_kg"


class Overview(BaseModel):
    basis: str
    kpis: list[Kpi]


def _kpis(facts: list[Fact]) -> dict[str, float | None]:
    revenue, weight = _sum(x.revenue for x in facts), _weight(facts)
    paid = _sum(x.paid for x in facts)
    transit = [d for d in (days_between(x.first_dispatch, x.unloaded) for x in facts if x.fully_unloaded) if d is not None]
    to_pod = [d for d in (days_between(x.lr_date, x.pod) for x in facts) if d is not None]
    to_pay = [d for d in (days_between(x.lr_date, x.settled) for x in facts) if d is not None]
    return {
        "lrs": len(facts),
        "revenue": float(revenue),
        "weight": float(weight),
        "packages": sum(x.packages for x in facts),
        "revenue_per_lr": float(revenue / len(facts)) if facts else None,
        "revenue_per_kg": stats.ratio(revenue, weight),
        "collected": float(paid),
        "collection_rate": stats.ratio(paid * 100, revenue, 1),
        "outstanding": float(revenue - paid),
        "delivered_pct": stats.ratio(sum(1 for x in facts if x.pod) * 100, len(facts), 1),
        "median_transit_days": stats.median(transit),
        "median_days_to_delivery": stats.median(to_pod),
        "median_days_to_payment": stats.median(to_pay),
        "customers": len({x.payer.lower() for x in facts}),
    }


_KPI_LABELS = {
    "lrs": ("LRs booked", "count"),
    "revenue": ("Revenue booked", "rupees"),
    "weight": ("Chargeable weight", "kg"),
    "packages": ("Packages", "count"),
    "revenue_per_lr": ("Revenue per LR", "rupees"),
    "revenue_per_kg": ("Revenue per kg", "rupees_per_kg"),
    "collected": ("Collected on these LRs", "rupees"),
    "collection_rate": ("Collected so far", "percent"),
    "outstanding": ("Still owed on these LRs", "rupees"),
    "delivered_pct": ("Signed for by consignee", "percent"),
    "median_transit_days": ("Median days on the road", "days"),
    "median_days_to_delivery": ("Median days, booking to signature", "days"),
    "median_days_to_payment": ("Median days, booking to paid in full", "days"),
    "customers": ("Paying customers", "count"),
}


def overview(session: Session, f: Filters) -> Overview:
    now, before = _kpis(load(session, f)), _kpis(load(session, f.previous()))
    return Overview(
        basis=f"{f.describe()}. Compared with the {(f.date_to - f.date_from).days + 1} days before. "
        "Revenue is the LR total plus charges added at delivery. Medians ignore LRs not yet at that stage.",
        kpis=[
            Kpi(key=k, label=label, value=now[k], previous=before[k], change_pct=stats.change_pct(now[k] or 0, before[k] or 0), unit=unit)
            for k, (label, unit) in _KPI_LABELS.items()
        ],
    )


# ---------------------------------------------------------------- trend


class TrendPoint(BaseModel):
    period: str  # first day of the bucket, ISO
    label: str
    lrs: int
    revenue: Decimal
    weight: Decimal
    collected: Decimal


class Trend(BaseModel):
    basis: str
    grain: Grain
    points: list[TrendPoint]


def _bucket(day: dt.date, grain: Grain) -> dt.date:
    if grain == "day":
        return day
    if grain == "week":
        return day - dt.timedelta(days=day.weekday())
    if grain == "month":
        return day.replace(day=1)
    if grain == "quarter":
        return day.replace(month=(day.month - 1) // 3 * 3 + 1, day=1)
    return day.replace(month=1, day=1)


def _label(start: dt.date, grain: Grain) -> str:
    return {
        "day": f"{start:%d %b}",
        "week": f"Week of {start:%d %b}",
        "month": f"{start:%b %Y}",
        "quarter": f"Q{(start.month - 1) // 3 + 1} {start.year}",
        "year": f"{start.year}",
    }[grain]


def _next(start: dt.date, grain: Grain) -> dt.date:
    if grain == "day":
        return start + dt.timedelta(days=1)
    if grain == "week":
        return start + dt.timedelta(days=7)
    months = {"month": 1, "quarter": 3, "year": 12}[grain]
    month = start.month - 1 + months
    return start.replace(year=start.year + month // 12, month=month % 12 + 1, day=1)


def collections_in(session: Session, f: Filters):
    """Money recorded in the period (by collection date), within the same branch and customer filters."""
    query = select(Collection).where(
        Collection.status != "failed",
        Collection.collected_at >= start_of(f.date_from),
        Collection.collected_at < start_of(f.date_to + dt.timedelta(days=1)),
    )
    if f.branch_id:
        query = query.where(Collection.branch_id == f.branch_id)
    if f.customer and f.customer_role == "payer":
        query = query.where(func.lower(Collection.payer_name) == f.customer.strip().lower())
    return list(session.scalars(query))


def trend(session: Session, f: Filters, grain: Grain) -> Trend:
    facts = load(session, f)
    buckets: dict[dt.date, list] = {}
    start = _bucket(f.date_from, grain)
    while start <= f.date_to:
        buckets[start] = [0, ZERO, ZERO, ZERO]
        start = _next(start, grain)
    for x in facts:
        b = buckets[_bucket(x.lr_date, grain)]
        b[0] += 1
        b[1] += x.revenue
        b[2] += x.chargeable_weight or ZERO
    for c in collections_in(session, f):
        key = _bucket(c.collected_at.date(), grain)
        if key in buckets:
            buckets[key][3] += c.amount
    return Trend(
        basis=f"{f.describe()}. Collections are money recorded in each period, whichever LR it was for.",
        grain=grain,
        points=[
            TrendPoint(period=k.isoformat(), label=_label(k, grain), lrs=v[0], revenue=v[1], weight=v[2], collected=v[3])
            for k, v in buckets.items()
        ],
    )


# ---------------------------------------------------------------- customers


class CustomerRow(BaseModel):
    customer: str
    lrs: int
    revenue: Decimal
    share_pct: float | None
    weight: Decimal
    revenue_per_kg: float | None
    first_booking: dt.date
    last_booking: dt.date
    active_days: int
    avg_days_between_bookings: float | None
    outstanding: Decimal
    median_days_to_pay: float | None
    previous_revenue: Decimal
    growth_pct: float | None
    # What they owe today across all their LRs, not only this period's (payers only).
    owes_now: Decimal | None
    overdue_now: Decimal | None


class Customers(BaseModel):
    basis: str
    rows: list[CustomerRow]
    top3_share_pct: float | None


def _key(x: Fact, role: str) -> str:
    return {"payer": x.payer, "consignor": x.consignor, "consignee": x.consignee}[role]


def customers(session: Session, f: Filters, limit: int = 100) -> Customers:
    facts, before = load(session, f), load(session, f.previous())
    groups: dict[str, list[Fact]] = defaultdict(list)
    for x in facts:
        groups[_key(x, f.customer_role).lower()].append(x)
    previous: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for x in before:
        previous[_key(x, f.customer_role).lower()] += x.revenue
    owing = {}
    if f.customer_role == "payer":
        for p in payments.receivables(session).parties:
            owing[p.party.lower()] = (p.outstanding, p.overdue)
    total = _sum(x.revenue for x in facts)
    rows = []
    for key, items in groups.items():
        dates = sorted(x.lr_date for x in items)
        revenue = _sum(x.revenue for x in items)
        weight = _weight(items)
        to_pay = [d for d in (days_between(x.lr_date, x.settled) for x in items) if d is not None]
        rows.append(
            CustomerRow(
                customer=_key(items[0], f.customer_role),
                lrs=len(items),
                revenue=revenue,
                share_pct=stats.ratio(revenue * 100, total, 1),
                weight=weight,
                revenue_per_kg=stats.ratio(revenue, weight),
                first_booking=dates[0],
                last_booking=dates[-1],
                active_days=len(set(dates)),
                avg_days_between_bookings=round((dates[-1] - dates[0]).days / (len(set(dates)) - 1), 1) if len(set(dates)) > 1 else None,
                outstanding=_sum(x.balance for x in items),
                median_days_to_pay=stats.median(to_pay),
                previous_revenue=previous[key],
                growth_pct=stats.change_pct(revenue, previous[key]),
                owes_now=owing.get(key, (ZERO, ZERO))[0] if f.customer_role == "payer" else None,
                overdue_now=owing.get(key, (ZERO, ZERO))[1] if f.customer_role == "payer" else None,
            )
        )
    rows.sort(key=lambda r: r.revenue, reverse=True)
    return Customers(
        basis=f"{f.describe()}. Grouped by {f.customer_role}. Growth compares with the same length of time before. "
        "\"Owes now\" is across all their LRs, as in receivables.",
        rows=rows[:limit],
        top3_share_pct=stats.ratio(_sum(r.revenue for r in rows[:3]) * 100, total, 1),
    )


# ---------------------------------------------------------------- lanes and rates


class LaneRow(BaseModel):
    origin: str
    destination: str
    lrs: int
    revenue: Decimal
    share_pct: float | None
    weight: Decimal
    packages: int
    revenue_per_kg: float | None
    median_transit_days: float | None
    customers: int


class Lanes(BaseModel):
    basis: str
    rows: list[LaneRow]


def lanes(session: Session, f: Filters) -> Lanes:
    facts = load(session, f)
    groups: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    for x in facts:
        groups[(x.origin, x.destination)].append(x)
    total = _sum(x.revenue for x in facts)
    rows = []
    for (origin, destination), items in groups.items():
        revenue, weight = _sum(x.revenue for x in items), _weight(items)
        transit = [d for d in (days_between(x.first_dispatch, x.unloaded) for x in items if x.fully_unloaded) if d is not None]
        rows.append(
            LaneRow(
                origin=origin,
                destination=destination,
                lrs=len(items),
                revenue=revenue,
                share_pct=stats.ratio(revenue * 100, total, 1),
                weight=weight,
                packages=sum(x.packages for x in items),
                revenue_per_kg=stats.ratio(revenue, weight),
                median_transit_days=stats.median(transit),
                customers=len({x.payer.lower() for x in items}),
            )
        )
    rows.sort(key=lambda r: r.revenue, reverse=True)
    return Lanes(basis=f"{f.describe()}. A lane is origin to destination city.", rows=rows)


class RateStats(BaseModel):
    origin: str
    destination: str
    unit: Literal["per_kg", "per_article"]
    samples: int
    mean: float | None
    median: float | None
    minimum: float | None
    maximum: float | None
    p25: float | None
    p75: float | None


class RateOutlier(BaseModel):
    lr_number: str
    lr_date: dt.date
    customer: str
    origin: str
    destination: str
    unit: str
    rate: float
    lane_median: float
    direction: Literal["high", "low"]


class RatePoint(BaseModel):
    month: str
    lrs: int
    avg_rate_per_kg: float | None
    avg_rate_per_article: float | None


class Rates(BaseModel):
    basis: str
    lanes: list[RateStats]
    outliers: list[RateOutlier]
    # Month by month, for the filtered customer and/or lane.
    history: list[RatePoint]


def _unit_rate(x: Fact) -> tuple[str, float] | None:
    """The LR's freight as a rate: per article if charged per article, else per chargeable kg."""
    if x.charge_basis == "per_article":
        return ("per_article", float(x.rate_per_article)) if x.rate_per_article else None
    return ("per_kg", float(x.rate_per_kg)) if x.rate_per_kg else None


def rates(session: Session, f: Filters) -> Rates:
    facts = load(session, f)
    groups: dict[tuple[str, str, str], list[tuple[Fact, float]]] = defaultdict(list)
    for x in facts:
        unit = _unit_rate(x)
        if unit is not None:
            groups[(x.origin, x.destination, unit[0])].append((x, unit[1]))
    lane_rows, outliers = [], []
    for (origin, destination, unit), items in groups.items():
        values = [v for _, v in items]
        lane_rows.append(
            RateStats(
                origin=origin, destination=destination, unit=unit, samples=len(values),
                mean=round(sum(values) / len(values), 2), median=stats.median(values),
                minimum=min(values), maximum=max(values), p25=stats.percentile(values, 25), p75=stats.percentile(values, 75),
            )
        )
        fence = stats.fences(values)
        if fence is None:
            continue
        mid = stats.median(values)
        for x, v in items:
            if v < fence[0] or v > fence[1]:
                outliers.append(
                    RateOutlier(
                        lr_number=x.lr_number, lr_date=x.lr_date, customer=x.payer, origin=origin, destination=destination,
                        unit=unit, rate=v, lane_median=mid, direction="high" if v > fence[1] else "low",
                    )
                )
    history: list[RatePoint] = []
    if f.customer or (f.origin and f.destination) or f.destination:
        months: dict[dt.date, list[Fact]] = defaultdict(list)
        for x in facts:
            months[x.lr_date.replace(day=1)].append(x)
        for month in sorted(months):
            items = months[month]
            per_kg = [float(x.rate_per_kg) for x in items if x.charge_basis != "per_article" and x.rate_per_kg]
            per_article = [float(x.rate_per_article) for x in items if x.charge_basis == "per_article" and x.rate_per_article]
            history.append(
                RatePoint(
                    month=f"{month:%b %Y}", lrs=len(items),
                    avg_rate_per_kg=round(sum(per_kg) / len(per_kg), 2) if per_kg else None,
                    avg_rate_per_article=round(sum(per_article) / len(per_article), 2) if per_article else None,
                )
            )
    lane_rows.sort(key=lambda r: r.samples, reverse=True)
    outliers.sort(key=lambda o: abs(o.rate - o.lane_median) / (o.lane_median or 1), reverse=True)
    return Rates(
        basis=f"{f.describe()}. Rate is freight per chargeable kg, or per article for LRs charged per article; "
        "LRs with no freight are left out. Unusual: outside 1.5 times the middle half of the lane's rates "
        "(needs 5 LRs on the lane).",
        lanes=lane_rows,
        outliers=outliers[:50],
        history=history,
    )


# ---------------------------------------------------------------- execution


class Duration(BaseModel):
    stage: str
    samples: int
    median_days: float | None
    p90_days: float | None


class PendingLr(BaseModel):
    lr_number: str
    customer: str
    destination: str
    stage: str
    days: int


class DelayedLr(BaseModel):
    lr_number: str
    origin: str
    destination: str
    transit_days: float
    lane_median_days: float


class Execution(BaseModel):
    basis: str
    stages: dict[str, int]
    durations: list[Duration]
    pending: list[PendingLr]
    delayed: list[DelayedLr]
    on_time_pct: float | None


def execution(session: Session, f: Filters) -> Execution:
    facts = load(session, f)
    day = today()
    stages = {"awaiting_dispatch": 0, "in_transit": 0, "awaiting_delivery": 0, "delivered": 0}
    for x in facts:
        stages[x.stage] += 1
    spans = {
        "Booking to dispatch": [days_between(x.lr_date, x.first_dispatch) for x in facts if x.first_dispatch],
        "On the road (dispatch to unloading)": [days_between(x.first_dispatch, x.unloaded) for x in facts if x.fully_unloaded],
        "Unloading to consignee's signature": [days_between(x.unloaded, x.pod) for x in facts if x.pod and x.unloaded],
        "Booking to consignee's signature": [days_between(x.lr_date, x.pod) for x in facts if x.pod],
    }
    durations = [
        Duration(stage=name, samples=len(v), median_days=stats.median([d for d in v if d is not None]), p90_days=stats.percentile([d for d in v if d is not None], 90))
        for name, v in spans.items()
    ]
    pending = []
    for x in facts:
        if x.stage == "delivered":
            continue
        since = {"awaiting_dispatch": x.lr_date, "in_transit": x.first_dispatch, "awaiting_delivery": x.unloaded}[x.stage] or x.lr_date
        pending.append(PendingLr(lr_number=x.lr_number, customer=x.consignee, destination=x.destination, stage=x.stage, days=int(days_between(since, day) or 0)))
    pending.sort(key=lambda p: -p.days)
    by_lane: dict[tuple[str, str], list[tuple[Fact, float]]] = defaultdict(list)
    for x in facts:
        if x.fully_unloaded and x.first_dispatch:
            by_lane[(x.origin, x.destination)].append((x, days_between(x.first_dispatch, x.unloaded)))
    usual = {t.destination: t.days_max for t in session.scalars(select(TransitTime))}
    delayed, judged, on_time = [], 0, 0
    for (origin, destination), items in by_lane.items():
        if destination in usual:
            # The time the office tells customers ("Raipur 4 to 5 days"): later than the longest is late.
            limit, expected = float(usual[destination]), float(usual[destination])
        elif len(items) >= 5:
            mid = stats.median([d for _, d in items])
            limit, expected = max(mid * 1.5, mid + 1), mid
        else:
            continue
        for x, d in items:
            judged += 1
            if d > limit:
                delayed.append(DelayedLr(lr_number=x.lr_number, origin=origin, destination=destination, transit_days=d, lane_median_days=expected))
            else:
                on_time += 1
    delayed.sort(key=lambda d: d.transit_days - d.lane_median_days, reverse=True)
    return Execution(
        basis=f"{f.describe()}. Late: on the road longer than the usual transit time set for the destination "
        "(\"Raipur 4 to 5 days\" means late after 5). Destinations without one: more than 1.5 times the route's median "
        "and at least a day longer, judged once the route has 5 trips.",
        stages=stages,
        durations=durations,
        pending=pending[:50],
        delayed=delayed[:50],
        on_time_pct=stats.ratio(on_time * 100, judged, 1),
    )


# ---------------------------------------------------------------- fleet


class TruckRow(BaseModel):
    vehicle_number: str
    trips: int
    lrs: int
    packages: int
    weight_carried: Decimal
    avg_payload_used_pct: float | None
    days_on_road: float
    median_trip_days: float | None


class Fleet(BaseModel):
    basis: str
    rows: list[TruckRow]


def fleet(session: Session, f: Filters) -> Fleet:
    query = (
        select(Trip, Truck)
        .join(Truck, Truck.id == Trip.truck_id)
        .where(Trip.dispatched_at >= start_of(f.date_from), Trip.dispatched_at < start_of(f.date_to + dt.timedelta(days=1)))
    )
    if f.branch_id:
        query = query.where(Trip.branch_id == f.branch_id)
    per_truck: dict[uuid.UUID, dict] = {}
    now = dt.datetime.now(dt.UTC)
    for trip, truck in session.execute(query):
        row = per_truck.setdefault(truck.id, {"truck": truck, "trips": 0, "lrs": set(), "packages": 0, "weight": ZERO, "loads": [], "days": []})
        lines = session.execute(select(DispatchLine, Lr).join(Lr, Lr.id == DispatchLine.lr_id).where(DispatchLine.trip_id == trip.id)).all()
        weight = _sum((lr.weight or ZERO) * line.packages / lr.packages for line, lr in lines)
        row["trips"] += 1
        row["lrs"].update(lr.id for _, lr in lines)
        row["packages"] += sum(line.packages for line, _ in lines)
        row["weight"] += weight
        row["loads"].append(float(weight) * 100 / float(truck.payload_kg) if truck.payload_kg else None)
        row["days"].append(days_between(trip.dispatched_at, trip.completed_at or now))
    rows = [
        TruckRow(
            vehicle_number=r["truck"].vehicle_number,
            trips=r["trips"],
            lrs=len(r["lrs"]),
            packages=r["packages"],
            weight_carried=r["weight"].quantize(Decimal("0.01")),
            avg_payload_used_pct=round(sum(v for v in r["loads"] if v is not None) / len([v for v in r["loads"] if v is not None]), 1) if any(v is not None for v in r["loads"]) else None,
            days_on_road=round(sum(r["days"]), 1),
            median_trip_days=stats.median(r["days"]),
        )
        for r in per_truck.values()
    ]
    rows.sort(key=lambda r: r.trips, reverse=True)
    return Fleet(
        basis=f"Trips dispatched {f.date_from:%d-%m-%Y} to {f.date_to:%d-%m-%Y}. Weight carried counts each LR's weight "
        "for the packages on that trip; payload used is that weight against the truck's payload. Trips still on the road count to today.",
        rows=rows,
    )


# ---------------------------------------------------------------- finance


class MonthRow(BaseModel):
    month: str
    revenue_booked: Decimal
    collected_cash: Decimal
    collected_upi: Decimal
    collected_cheque: Decimal
    collected_bank: Decimal
    collected_total: Decimal
    confirmed_by_bank: Decimal
    shortages: Decimal
    # From trips dispatched in the month: what was carried, what the truck owners and the office cost.
    trip_revenue: Decimal
    truck_hire: Decimal
    trip_expenses: Decimal
    trip_margin: Decimal


class Finance(BaseModel):
    basis: str
    months: list[MonthRow]
    totals: MonthRow
    receivable_now: Decimal
    overdue_now: Decimal
    median_days_to_payment: float | None
    expenses_note: str


def finance(session: Session, f: Filters) -> Finance:
    months: dict[dt.date, dict[str, Decimal]] = {}
    start = f.date_from.replace(day=1)
    keys = (
        "revenue_booked", "collected_cash", "collected_upi", "collected_cheque", "collected_bank", "collected_total",
        "confirmed_by_bank", "shortages", "trip_revenue", "truck_hire", "trip_expenses", "trip_margin",
    )
    while start <= f.date_to:
        months[start] = {k: ZERO for k in keys}
        start = _next(start, "month")
    facts = load(session, f)
    for x in facts:
        months[x.lr_date.replace(day=1)]["revenue_booked"] += x.revenue
    method_key = {"cash": "collected_cash", "upi": "collected_upi", "cheque": "collected_cheque", "bank_transfer": "collected_bank", "legacy": "collected_cash"}
    for c in collections_in(session, f):
        m = months.get(c.collected_at.date().replace(day=1))
        if m is None:
            continue
        m[method_key.get(c.method, "collected_cash")] += c.amount
        m["collected_total"] += c.amount
        if c.status == "confirmed":
            m["confirmed_by_bank"] += c.amount
    shortage_query = select(Shortage).where(Shortage.created_at >= start_of(f.date_from), Shortage.created_at < start_of(f.date_to + dt.timedelta(days=1)))
    if f.branch_id:
        shortage_query = shortage_query.where(Shortage.branch_id == f.branch_id)
    for s in session.scalars(shortage_query):
        m = months.get(s.created_at.date().replace(day=1))
        if m is not None:
            m["shortages"] += s.amount
    from app.analytics.business import priced_trips

    priced, unpriced = priced_trips(session, f)
    for m in priced:
        bucket = months.get(m.dispatched_at.date().replace(day=1))
        if bucket is not None:
            bucket["trip_revenue"] += m.revenue
            bucket["truck_hire"] += m.hire - m.deductions
            bucket["trip_expenses"] += m.expenses
            bucket["trip_margin"] += m.margin
    rows = [MonthRow(month=f"{k:%b %Y}", **v) for k, v in months.items()]
    totals = MonthRow(month="Total", **{k: _sum(getattr(r, k) for r in rows) for k in keys})
    owed = payments.receivables(session)
    to_pay = [d for d in (days_between(x.lr_date, x.settled) for x in facts) if d is not None]
    return Finance(
        basis=f"{f.describe()}. Revenue is by booking month; collections by the month the money was recorded; "
        "\"confirmed by bank\" is money already matched to the bank statement.",
        months=rows,
        totals=totals,
        receivable_now=owed.outstanding,
        overdue_now=owed.overdue,
        median_days_to_payment=stats.median(to_pay),
        expenses_note=(
            f"{unpriced} trip(s) in this period have no hire recorded, so their cost is missing from the margin."
            if unpriced else "Diesel, tolls and driver pay are the truck owner's, paid out of the hire."
        ),
    )


# ---------------------------------------------------------------- branches


class BranchRow(BaseModel):
    branch: str
    lrs_booked: int
    revenue_booked: Decimal
    lrs_delivered: int
    median_days_unload_to_signature: float | None
    collected: Decimal
    collection_rate_pct: float | None
    cash_handed_over_short: Decimal


class Branches(BaseModel):
    basis: str
    rows: list[BranchRow]


def branches(session: Session, f: Filters) -> Branches:
    facts = load(session, f)
    names = dict(session.execute(select(Branch.id, Branch.name)).all())
    rows = []
    for branch_id, name in names.items():
        booked = [x for x in facts if x.branch_id == branch_id]
        delivering = [x for x in facts if (x.delivery_branch_id or x.branch_id) == branch_id]
        if not booked and not delivering:
            continue
        lag = [days_between(x.unloaded, x.pod) for x in delivering if x.pod and x.unloaded]
        revenue = _sum(x.revenue for x in delivering)
        paid = _sum(x.paid for x in delivering)
        short = session.scalar(
            select(func.coalesce(func.sum(CashHandover.expected_cash - CashHandover.counted_cash), 0)).where(
                CashHandover.branch_id == branch_id,
                CashHandover.handed_at >= start_of(f.date_from),
                CashHandover.handed_at < start_of(f.date_to + dt.timedelta(days=1)),
            )
        )
        rows.append(
            BranchRow(
                branch=name,
                lrs_booked=len(booked),
                revenue_booked=_sum(x.revenue for x in booked),
                lrs_delivered=sum(1 for x in delivering if x.pod),
                median_days_unload_to_signature=stats.median([d for d in lag if d is not None]),
                collected=paid,
                collection_rate_pct=stats.ratio(paid * 100, revenue, 1),
                cash_handed_over_short=short,
            )
        )
    return Branches(
        basis=f"{f.describe()}. Booked: LRs booked at the branch. Delivered and collected: LRs the branch delivers.",
        rows=rows,
    )
