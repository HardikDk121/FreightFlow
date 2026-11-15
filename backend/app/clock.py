import datetime as dt
from zoneinfo import ZoneInfo

# The business runs on Indian time; "today" and "days waiting" follow it, not the server's clock.
_BUSINESS_ZONE = ZoneInfo("Asia/Kolkata")


def today() -> dt.date:
    return dt.datetime.now(_BUSINESS_ZONE).date()
