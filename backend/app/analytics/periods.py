"""Named periods, so a saved or scheduled report always means "last month" and not a fixed date."""

import datetime as dt
from typing import Literal

Period = Literal["today", "yesterday", "last_7_days", "last_30_days", "this_month", "last_month", "this_quarter", "last_quarter", "this_year", "last_year"]


def resolve(period: Period, day: dt.date) -> tuple[dt.date, dt.date]:
    quarter_start = day.replace(month=(day.month - 1) // 3 * 3 + 1, day=1)
    month_start = day.replace(day=1)
    previous_month_end = month_start - dt.timedelta(days=1)
    previous_quarter_end = quarter_start - dt.timedelta(days=1)
    return {
        "today": (day, day),
        "yesterday": (day - dt.timedelta(days=1), day - dt.timedelta(days=1)),
        "last_7_days": (day - dt.timedelta(days=6), day),
        "last_30_days": (day - dt.timedelta(days=29), day),
        "this_month": (month_start, day),
        "last_month": (previous_month_end.replace(day=1), previous_month_end),
        "this_quarter": (quarter_start, day),
        "last_quarter": (previous_quarter_end.replace(month=(previous_quarter_end.month - 1) // 3 * 3 + 1, day=1), previous_quarter_end),
        "this_year": (day.replace(month=1, day=1), day),
        "last_year": (day.replace(year=day.year - 1, month=1, day=1), day.replace(year=day.year - 1, month=12, day=31)),
    }[period]
