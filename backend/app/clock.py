import datetime as dt
from zoneinfo import ZoneInfo

# The business runs on Indian time; "today" and "days waiting" follow it, not the server's clock.
_BUSINESS_ZONE = ZoneInfo("Asia/Kolkata")


def today() -> dt.date:
    return dt.datetime.now(_BUSINESS_ZONE).date()


def midnight_after(day: dt.date) -> dt.datetime:
    """The instant `day` ends in business time."""
    return dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min, _BUSINESS_ZONE)
