"""Automatic insights: rules that read the same analytics and say what deserves attention, with
the numbers behind each one. Rules, not guesses: each states its threshold."""

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.analytics import business, service, stats
from app.analytics.facts import Filters, load
from app.clock import today

# Thresholds, named so the rules can be read and tuned.
REVENUE_SWING_PCT = 20
CONCENTRATION_PCT = 50
QUIET_FACTOR = 2  # a regular customer is quiet after twice their usual gap with no booking
SLOW_DELIVERY_DAYS = 2
# Truck owners are usually settled within this many days of dispatch.
OWNER_PAY_DAYS = 15


class Insight(BaseModel):
    severity: Literal["high", "medium", "info"]
    title: str
    detail: str
    # Which analysis to open for the records behind it.
    analysis: str


def insights(session: Session, f: Filters) -> list[Insight]:
    found: list[Insight] = []
    facts, before = load(session, f), load(session, f.previous())
    revenue, previous = sum((x.revenue for x in facts), Decimal(0)), sum((x.revenue for x in before), Decimal(0))
    change = stats.change_pct(revenue, previous)
    if change is not None and abs(change) >= REVENUE_SWING_PCT:
        found.append(Insight(
            severity="high" if change < 0 else "info",
            title=f"Revenue {'down' if change < 0 else 'up'} {abs(change):.0f}%",
            detail=f"Rs {revenue:,.0f} booked against Rs {previous:,.0f} in the same length of time before.",
            analysis="overview",
        ))
    customers = service.customers(session, f, limit=1000)
    if customers.top3_share_pct and customers.top3_share_pct >= CONCENTRATION_PCT and len(customers.rows) > 3:
        names = ", ".join(r.customer for r in customers.rows[:3])
        found.append(Insight(
            severity="medium",
            title=f"{customers.top3_share_pct:.0f}% of revenue from three customers",
            detail=f"{names}. Losing one would hurt; worth widening the customer base.",
            analysis="customers",
        ))
    for row in customers.rows:
        if row.growth_pct is not None and row.growth_pct <= -50 and row.previous_revenue >= 5000:
            found.append(Insight(
                severity="medium",
                title=f"{row.customer} booked {abs(row.growth_pct):.0f}% less",
                detail=f"Rs {row.revenue:,.0f} against Rs {row.previous_revenue:,.0f} before. Worth a call.",
                analysis="customers",
            ))
    # Regular customers gone quiet: looked over the last 120 days, whatever the chosen period.
    day = today()
    recent = load(session, f.model_copy(update={"date_from": day - dt.timedelta(days=120), "date_to": day}))
    dates: dict[str, list[dt.date]] = defaultdict(list)
    for x in recent:
        dates[x.payer].append(x.lr_date)
    for customer, booked in dates.items():
        unique = sorted(set(booked))
        if len(unique) < 4:
            continue
        gap = (unique[-1] - unique[0]).days / (len(unique) - 1)
        silent = (day - unique[-1]).days
        if gap > 0 and silent > max(QUIET_FACTOR * gap, 7):
            found.append(Insight(
                severity="medium",
                title=f"{customer} has gone quiet",
                detail=f"Usually books every {gap:.0f} days; nothing for {silent} days (last on {unique[-1]:%d-%m-%Y}).",
                analysis="customers",
            ))
    rates = service.rates(session, f)
    if rates.outliers:
        low = [o for o in rates.outliers if o.direction == "low"]
        found.append(Insight(
            severity="medium" if low else "info",
            title=f"{len(rates.outliers)} LRs at unusual rates",
            detail=(f"{len(low)} charged well below their lane's usual rate, e.g. {low[0].lr_number} at Rs {low[0].rate} against {low[0].lane_median}. "
                    if low else "") + "Check for typing mistakes or discounts given without approval.",
            analysis="rates",
        ))
    execution = service.execution(session, f)
    waiting = [p for p in execution.pending if p.stage == "awaiting_delivery" and p.days >= SLOW_DELIVERY_DAYS]
    if waiting:
        found.append(Insight(
            severity="high",
            title=f"{len(waiting)} LRs unloaded but not signed for",
            detail=f"Oldest: {waiting[0].lr_number} for {waiting[0].customer}, {waiting[0].days} days. Ask the branch for the signed gate pass.",
            analysis="execution",
        ))
    if execution.delayed:
        lanes = defaultdict(int)
        for d in execution.delayed:
            lanes[f"{d.origin} to {d.destination}"] += 1
        worst = max(lanes, key=lanes.get)
        found.append(Insight(
            severity="medium",
            title=f"{len(execution.delayed)} trips slower than usual",
            detail=f"Most on {worst} ({lanes[worst]}).",
            analysis="execution",
        ))
    finance = service.finance(session, f)
    if finance.overdue_now > 0:
        found.append(Insight(
            severity="high" if finance.overdue_now > finance.receivable_now / 3 else "medium",
            title=f"Rs {finance.overdue_now:,.0f} overdue",
            detail=f"Of Rs {finance.receivable_now:,.0f} owed in total. See ageing and collection tasks.",
            analysis="finance",
        ))
    if finance.totals.shortages > 0:
        found.append(Insight(
            severity="high",
            title=f"Rs {finance.totals.shortages:,.0f} in cash shortages",
            detail="Money that should have been handed over or banked but was not, in this period.",
            analysis="finance",
        ))
    unconfirmed = finance.totals.collected_total - finance.totals.confirmed_by_bank - finance.totals.collected_cash
    if unconfirmed > 0:
        found.append(Insight(
            severity="info",
            title=f"Rs {unconfirmed:,.0f} by UPI, cheque or transfer not yet seen in the bank",
            detail="Import the latest bank statement to confirm it.",
            analysis="finance",
        ))
    profit = business.trip_profit(session, f)
    losing = [t for t in profit.trips if t.margin is not None and t.margin < 0]
    thin = [t for t in profit.trips if t.margin_pct is not None and 0 <= t.margin_pct < business.LOW_MARGIN_PCT]
    if losing:
        found.append(Insight(
            severity="high",
            title=f"{len(losing)} trip(s) lost money",
            detail=f"Worst: trip {losing[0].trip_no} to {losing[0].destination}, Rs {losing[0].margin:,.0f} "
                   f"(carried Rs {losing[0].revenue:,.0f}, hire Rs {losing[0].hire:,.0f}). The truck went out too empty or the hire was too high.",
            analysis="trip_profit",
        ))
    if thin:
        found.append(Insight(
            severity="medium",
            title=f"{len(thin)} trip(s) earned under {business.LOW_MARGIN_PCT}%",
            detail="Fill trucks fuller before dispatch, or get more quotes before agreeing the hire.",
            analysis="trip_profit",
        ))
    if profit.trips_without_hire:
        found.append(Insight(
            severity="medium",
            title=f"{profit.trips_without_hire} trip(s) have no hire recorded",
            detail="Their profit cannot be worked out until the hire agreed with the truck owner is entered.",
            analysis="trip_profit",
        ))
    for c in business.contracts(session, f).rows:
        if c.status == "expiring":
            found.append(Insight(severity="medium", title=f"{c.party}'s contract ends in {c.days_left} days",
                                 detail=f"On {c.ends_on:%d-%m-%Y}. Time to agree the next rates.", analysis="contracts"))
        elif c.status == "expired" and c.lrs_after_expiry:
            found.append(Insight(severity="high", title=f"{c.party} still booking after their contract ended",
                                 detail=f"{c.lrs_after_expiry} LR(s) since {c.ends_on:%d-%m-%Y}. Renew it or charge normal rates.", analysis="contracts"))
        if c.off_rate:
            found.append(Insight(severity="medium", title=f"{len(c.off_rate)} LR(s) for {c.party} off the agreed rate",
                                 detail=f"For example {c.off_rate[0].lr_number}: charged {c.off_rate[0].charged}, agreed {c.off_rate[0].agreed}.",
                                 analysis="contracts"))
    from app.hire.service import payables

    late_pay = [t for t in payables(session).trips if t.status == "completed" and (day - t.dispatched_at.date()).days > OWNER_PAY_DAYS]
    if late_pay:
        found.append(Insight(
            severity="info",
            title=f"{len(late_pay)} delivered trip(s) with the truck owner still unpaid",
            detail=f"Rs {sum((t.owed_to_owner for t in late_pay), Decimal(0)):,.0f} in all, over {OWNER_PAY_DAYS} days after dispatch. "
                   "Settle or record deductions, so owners keep giving trucks.",
            analysis="vendors",
        ))
    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(found, key=lambda i: order[i.severity])
