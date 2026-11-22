"""Saved report definitions: an analysis, its filters with a named period, and an optional schedule."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints

from app.analytics import periods
from app.analytics.custom import CustomReport
from app.analytics.facts import CustomerRole, Filters, Stage

Analysis = Literal[
    "overview", "trend", "customers", "lanes", "rates", "execution", "fleet", "finance", "branches", "insights",
    "trip_profit", "vendors", "rfqs", "contracts",
]


class SavedFilters(BaseModel):
    period: periods.Period = "last_30_days"
    branch_id: uuid.UUID | None = None
    customer: str | None = Field(default=None, max_length=60)
    customer_role: CustomerRole = "payer"
    origin: str | None = Field(default=None, max_length=30)
    destination: str | None = Field(default=None, max_length=30)
    freight_by: Literal["Paid", "ToPay", "TBB"] | None = None
    stage: Stage | None = None

    def resolve(self, day: dt.date) -> Filters:
        date_from, date_to = periods.resolve(self.period, day)
        return Filters(date_from=date_from, date_to=date_to, **self.model_dump(exclude={"period"}))


class SavedReportIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
    analysis: Analysis | Literal["custom"]
    filters: SavedFilters = SavedFilters()
    custom: CustomReport | None = None
    # daily: every morning; weekly: Mondays; monthly: the 1st.
    schedule: Literal["none", "daily", "weekly", "monthly"] = "none"
    recipients: list[EmailStr] = Field(default_factory=list, max_length=10)
    is_active: bool = True


class SavedReportRead(SavedReportIn):
    id: uuid.UUID
    last_sent_on: dt.date | None
