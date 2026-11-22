"""Build-your-own reports over the LR facts or the collection records: pick the grouping, the
measures and the filters. Only listed fields can be used, so a report cannot reach arbitrary data."""

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.analytics import service, stats
from app.analytics.facts import Fact, Filters, days_between, load

LrGroup = Literal["none", "payer", "consignor", "consignee", "origin", "destination", "lane", "freight_by", "charge_basis", "stage", "day", "week", "month"]
LrMeasure = Literal["lrs", "revenue", "freight", "paid", "balance", "packages", "weight", "revenue_per_kg", "median_days_to_delivery"]
CollectionGroup = Literal["none", "method", "status", "payer", "day", "week", "month"]
CollectionMeasure = Literal["collections", "amount"]

_LR_COLUMNS = {
    "lr_number": "LR", "lr_date": "Date", "payer": "Payer", "consignor": "Consignor", "consignee": "Consignee",
    "origin": "From", "destination": "To", "freight_by": "Freight by", "stage": "Stage", "packages": "Packages",
    "chargeable_weight": "Weight", "freight": "Freight", "revenue": "Revenue", "paid": "Paid", "balance": "Balance",
}
_MEASURE_LABELS = {
    "lrs": "LRs", "revenue": "Revenue", "freight": "Freight", "paid": "Paid", "balance": "Balance", "packages": "Packages",
    "weight": "Weight (kg)", "revenue_per_kg": "Revenue per kg", "median_days_to_delivery": "Median days to signature",
    "collections": "Collections", "amount": "Amount",
}


class CustomReport(BaseModel):
    """A report definition. With group "none" over LRs, `measures` are ignored and the LR rows are listed."""

    dataset: Literal["lrs", "collections"] = "lrs"
    group_by: str = "none"
    measures: list[str] = Field(default_factory=lambda: ["lrs", "revenue"], max_length=9)
    sort_by: str | None = None
    descending: bool = True
    limit: int = Field(default=500, ge=1, le=5000)


class Table(BaseModel):
    title: str
    basis: str
    columns: list[str]
    rows: list[list[str | float | int | None]]


def _group_key(x: Fact, group: str) -> str:
    if group == "lane":
        return f"{x.origin} to {x.destination}"
    if group == "day":
        return x.lr_date.isoformat()
    if group == "week":
        return (x.lr_date - dt.timedelta(days=x.lr_date.weekday())).isoformat()
    if group == "month":
        return x.lr_date.strftime("%Y-%m")
    return str(getattr(x, group) if group != "charge_basis" else (x.charge_basis or "as entered"))


def _measure(items: list[Fact], m: str) -> float | int | None:
    if m == "lrs":
        return len(items)
    if m == "packages":
        return sum(x.packages for x in items)
    if m == "weight":
        return float(sum((x.chargeable_weight or Decimal(0)) for x in items))
    if m == "revenue_per_kg":
        return stats.ratio(sum((x.revenue for x in items), Decimal(0)), sum((x.chargeable_weight or Decimal(0)) for x in items))
    if m == "median_days_to_delivery":
        return stats.median([d for d in (days_between(x.lr_date, x.pod) for x in items) if d is not None])
    return float(sum((getattr(x, m) for x in items), Decimal(0)))


def _sorted(columns: list[str], rows: list[list], report: CustomReport) -> list[list]:
    if report.sort_by in columns:
        i = columns.index(report.sort_by)
        rows.sort(key=lambda r: (r[i] is None, r[i]), reverse=report.descending)
    return rows[: report.limit]


def run(session: Session, f: Filters, report: CustomReport) -> Table:
    if report.dataset == "lrs":
        allowed_groups, allowed_measures = LrGroup.__args__, LrMeasure.__args__
    else:
        allowed_groups, allowed_measures = CollectionGroup.__args__, CollectionMeasure.__args__
    if report.group_by not in allowed_groups or any(m not in allowed_measures for m in report.measures):
        raise ValueError(f"For {report.dataset}, group by one of {', '.join(allowed_groups)} and measure from {', '.join(allowed_measures)}.")
    if report.dataset == "collections":
        return _collections(session, f, report)
    facts = load(session, f)
    if report.group_by == "none":
        columns = list(_LR_COLUMNS.values())
        rows = [[_cell(getattr(x, key)) for key in _LR_COLUMNS] for x in facts]
        return Table(title="LRs", basis=f.describe(), columns=columns, rows=_sorted(columns, rows, report))
    groups: dict[str, list[Fact]] = defaultdict(list)
    for x in facts:
        groups[_group_key(x, report.group_by)].append(x)
    columns = [report.group_by.replace("_", " ").title(), *(_MEASURE_LABELS[m] for m in report.measures)]
    rows = [[key, *(_measure(items, m) for m in report.measures)] for key, items in groups.items()]
    return Table(title=f"LRs by {report.group_by.replace('_', ' ')}", basis=f.describe(), columns=columns, rows=_sorted(columns, rows, report))


def _cell(value) -> str | float | int | None:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return value


def _collections(session: Session, f: Filters, report: CustomReport) -> Table:
    items = service.collections_in(session, f)
    def key(c) -> str:
        if report.group_by == "day":
            return c.collected_at.date().isoformat()
        if report.group_by == "week":
            d = c.collected_at.date()
            return (d - dt.timedelta(days=d.weekday())).isoformat()
        if report.group_by == "month":
            return c.collected_at.strftime("%Y-%m")
        return {"method": c.method, "status": c.status, "payer": c.payer_name}.get(report.group_by, "All")
    groups: dict[str, list] = defaultdict(list)
    for c in items:
        groups[key(c)].append(c)
    measures = report.measures or ["collections", "amount"]
    columns = [report.group_by.title() if report.group_by != "none" else "All", *(_MEASURE_LABELS[m] for m in measures)]
    rows = [[k, *((len(v) if m == "collections" else float(sum(c.amount for c in v))) for m in measures)] for k, v in groups.items()]
    return Table(
        title=f"Collections by {report.group_by}",
        basis=f"Money recorded {f.date_from:%d-%m-%Y} to {f.date_to:%d-%m-%Y}, failed payments excluded.",
        columns=columns,
        rows=_sorted(columns, rows, report),
    )
