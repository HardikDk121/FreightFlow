"""Small statistics helpers, kept separate so every analysis computes medians and outliers the same way."""

import statistics
from decimal import Decimal


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def percentile(values: list[float], p: float) -> float | None:
    """The p-th percentile (0-100), by linear interpolation; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = (len(ordered) - 1) * p / 100
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (rank - low), 2)


def fences(values: list[float]) -> tuple[float, float] | None:
    """Tukey fences: below Q1 - 1.5 IQR or above Q3 + 1.5 IQR is unusual. Needs at least 5 values."""
    if len(values) < 5:
        return None
    q1, q3 = percentile(values, 25), percentile(values, 75)
    iqr = q3 - q1
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr


def change_pct(now: Decimal | float, before: Decimal | float) -> float | None:
    """Percentage change from before to now; None when there was nothing before."""
    if not before:
        return None
    return round((float(now) - float(before)) * 100 / float(before), 1)


def ratio(part: Decimal | float, whole: Decimal | float, places: int = 2) -> float | None:
    return round(float(part) / float(whole), places) if whole else None
