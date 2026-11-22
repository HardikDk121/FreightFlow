"""Run any analysis by name: one place for the endpoints, exports and scheduled reports."""

from sqlalchemy.orm import Session

from app.analytics import business, insights, service
from app.analytics.facts import Filters
from app.models import User
from app.permissions import P, has

# Analyses about money need the money-trail permission as well as analytics.
MONEY = {"finance", "trip_profit", "vendors"}

FUNCTIONS = {
    "overview": service.overview,
    "customers": service.customers,
    "lanes": service.lanes,
    "rates": service.rates,
    "execution": service.execution,
    "fleet": service.fleet,
    "finance": service.finance,
    "branches": service.branches,
    "insights": insights.insights,
    "trip_profit": business.trip_profit,
    "vendors": business.vendors,
    "rfqs": business.rfqs,
    "contracts": business.contracts,
}


def allowed(user: User, name: str) -> bool:
    return has(user, P.ANALYTICS) and (name not in MONEY or has(user, P.MONEY_OVERVIEW))


def run(session: Session, name: str, f: Filters, grain: service.Grain = "day"):
    if name == "trend":
        return service.trend(session, f, grain)
    return FUNCTIONS[name](session, f)
