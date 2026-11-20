import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel

class PaymentRead(BaseModel):
    """Money set against this LR, from one collection."""

    collection_id: uuid.UUID
    amount: Decimal
    method: str
    # pending (not yet seen by the bank), confirmed, failed, legacy (recorded before these controls)
    status: str
    reference: str | None
    receipt_number: str | None
    collected_by: str
    collected_on: dt.date


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
    # advance, before_delivery, at_delivery (the default for anyone without terms) or credit
    payment_terms: str
    credit_days: int | None
    credit_limit: Decimal | None


class Receivables(BaseModel):
    outstanding: Decimal
    overdue: Decimal
    parties: list[PartyOutstanding]


class AgeingRow(BaseModel):
    party: str
    not_due: Decimal = Decimal(0)
    days_0_7: Decimal = Decimal(0)
    days_8_15: Decimal = Decimal(0)
    days_16_30: Decimal = Decimal(0)
    days_31_60: Decimal = Decimal(0)
    days_60_plus: Decimal = Decimal(0)
    total: Decimal = Decimal(0)


class Ageing(BaseModel):
    """Outstanding money by days past its due date."""

    rows: list[AgeingRow]
    totals: AgeingRow


class OverdueLr(BaseModel):
    party: str
    lr_number: str
    balance: Decimal
    days_overdue: int


class LimitUse(BaseModel):
    party: str
    outstanding: Decimal
    credit_limit: Decimal
    used_pct: int


class LatePayer(BaseModel):
    party: str
    lrs_paid: int
    lrs_paid_late: int
    average_days_late: int


class Priorities(BaseModel):
    largest: list[PartyOutstanding]
    oldest_overdue: list[OverdueLr]
    near_limit: list[LimitUse]
    late_payers: list[LatePayer]
