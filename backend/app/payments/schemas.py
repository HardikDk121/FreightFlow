import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Mode = Literal["cash", "upi", "neft", "cheque"]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class PaymentCreate(BaseModel):
    amount: Annotated[Decimal, Field(gt=0, le=Decimal("99999999.99"), decimal_places=2)]
    mode: Mode
    # UPI or NEFT reference, or cheque number.
    reference: Short | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    received_on: dt.date | None = None  # today when left out


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount: Decimal
    mode: str
    reference: str | None
    note: str | None
    received_on: dt.date


class LrAccount(BaseModel):
    """What one LR is owed and what has come in against it."""

    lr_id: uuid.UUID
    lr_number: str
    lr_date: dt.date
    freight_by: str
    # Who pays: the consignee on a to-pay LR, otherwise the consignor.
    payer: str
    total: Decimal
    paid: Decimal
    balance: Decimal
    # Null while a to-pay LR is still undelivered: nothing is due yet.
    due_on: dt.date | None
    overdue: bool
    payments: list[PaymentRead]


class PartyOutstanding(BaseModel):
    party: str
    lr_count: int
    outstanding: Decimal
    overdue: Decimal
    oldest_lr_date: dt.date


class Receivables(BaseModel):
    outstanding: Decimal
    overdue: Decimal
    parties: list[PartyOutstanding]
