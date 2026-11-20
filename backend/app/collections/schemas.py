import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.validators import Phone

Money = Annotated[Decimal, Field(gt=0, le=Decimal("99999999.99"), decimal_places=2)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
PayerName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Method = Literal["cash", "upi", "cheque"]


class DestinationCharge(BaseModel):
    """Charged at delivery, as on the paper money receipt: labour, door delivery (DC) or demurrage."""

    lr_id: uuid.UUID
    kind: Literal["labour", "dc_charge", "demurrage"]
    amount: Money


class ReceiptCreate(BaseModel):
    lr_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    charges: list[DestinationCharge] = Field(default_factory=list, max_length=150)
    # Where the customer is told what was collected. Without it, collections on this receipt
    # are flagged on the owner's dashboard because the customer cannot confirm them.
    payer_phone: Phone | None = None

    @model_validator(mode="after")
    def _distinct(self) -> "ReceiptCreate":
        if len(set(self.lr_ids)) != len(self.lr_ids):
            raise ValueError("An LR can appear once on a receipt.")
        return self


class PaymentIn(BaseModel):
    method: Method
    amount: Money
    utr: Annotated[str, StringConstraints(pattern=r"^[0-9]{12}$")] | None = None
    cheque_number: Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")] | None = None
    cheque_bank: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40)] | None = None
    cheque_date: dt.date | None = None

    @model_validator(mode="after")
    def _details(self) -> "PaymentIn":
        if self.method == "upi" and self.utr is None:
            raise ValueError("A UPI payment needs the 12-digit UTR from the customer's payment screen.")
        if self.method == "cheque" and (self.cheque_number is None or self.cheque_bank is None):
            raise ValueError("A cheque needs its 6-digit number and the bank's name.")
        return self


class VisitCreate(BaseModel):
    outcome: Literal["paid", "part_paid", "come_later", "refused"]
    promised_on: dt.date | None = None
    note: Note | None = None
    payment: PaymentIn | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "VisitCreate":
        paying = self.outcome in ("paid", "part_paid")
        if paying != (self.payment is not None):
            raise ValueError("Record a payment exactly when the customer paid something.")
        if (self.outcome == "come_later") != (self.promised_on is not None):
            raise ValueError("\"Come later\" needs the date the customer promised, and only then.")
        if self.outcome == "refused" and self.note is None:
            raise ValueError("Say why the customer refused.")
        return self


class ReceiptLineRead(BaseModel):
    lr_id: uuid.UUID
    lr_number: str
    lr_date: dt.date
    from_city: str
    to_city: str
    packages: int
    weight: Decimal | None
    # The paper receipt's particulars: freight (with hamali and other charges), the destination
    # charges added on this receipt, and the LR's ST charge.
    freight: Decimal
    labour: Decimal
    dc_charge: Decimal
    demurrage: Decimal
    st_charge: Decimal
    amount: Decimal
    balance: Decimal


class VisitRead(BaseModel):
    id: uuid.UUID
    collector: str
    visited_at: dt.datetime
    outcome: str
    promised_on: dt.date | None
    note: str | None


class CollectionRead(BaseModel):
    id: uuid.UUID
    receipt_number: str | None
    payer_name: str
    method: str
    amount: Decimal
    utr: str | None
    cheque_number: str | None
    cheque_bank: str | None
    collected_by: str
    collected_at: dt.datetime
    # pending (not yet seen by the bank), confirmed, failed, legacy (recorded before these controls)
    status: str
    # Where the money is now: with_collector, handed_over, deposited, in_bank, failed
    custody: str
    failed_reason: str | None


class ReceiptRead(BaseModel):
    id: uuid.UUID
    receipt_number: str
    payer_name: str
    payer_phone: str | None
    amount: Decimal
    collected: Decimal
    balance: Decimal
    status: str
    issued_by: str
    issued_at: dt.datetime
    cancel_reason: str | None
    # The last promise made on a "come later" visit, if the receipt is still open.
    promised_on: dt.date | None
    lines: list[ReceiptLineRead]
    visits: list[VisitRead]
    collections: list[CollectionRead]
    # Present only right after the receipt is issued: the link printed as the verification QR.
    verify_token: str | None = None


class ReceiptVerification(BaseModel):
    """What anyone holding the printed receipt may see: enough to tell a real receipt from a fake."""

    company_name: str
    receipt_number: str
    payer_name: str
    lr_numbers: list[str]
    amount: Decimal
    collected: Decimal
    status: str
    issued_on: dt.date


class CustodyItem(BaseModel):
    collection_id: uuid.UUID | None
    handover_id: uuid.UUID | None
    kind: Literal["cash", "cheque", "handover"]
    amount: Decimal
    payer_name: str | None
    cheque_number: str | None
    since: dt.datetime


class Custody(BaseModel):
    """What one person is holding right now, and since when."""

    user_id: uuid.UUID
    name: str
    cash: Decimal
    cheques: Decimal
    cheque_count: int
    oldest: dt.datetime | None
    items: list[CustodyItem]


class HandoverCreate(BaseModel):
    from_user_id: uuid.UUID
    counted_cash: Annotated[Decimal, Field(ge=0, le=Decimal("99999999.99"), decimal_places=2)]
    # Cheques the receiver actually has in hand. Any not listed stay with the collector.
    cheque_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class HandoverRead(BaseModel):
    id: uuid.UUID
    from_name: str
    to_name: str
    expected_cash: Decimal
    counted_cash: Decimal
    shortage: Decimal
    cheque_count: int
    handed_at: dt.datetime
    from_confirmed_at: dt.datetime | None


class DepositCreate(BaseModel):
    cash_amount: Annotated[Decimal, Field(ge=0, le=Decimal("99999999.99"), decimal_places=2)]
    cheque_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    slip_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None = None


class DepositRead(BaseModel):
    id: uuid.UUID
    deposit_number: str
    depositor: str
    expected_cash: Decimal
    cash_amount: Decimal
    shortage: Decimal
    cheque_count: int
    cheque_total: Decimal
    slip_reference: str | None
    deposited_at: dt.datetime
    status: str


class FailRequest(BaseModel):
    reason: Reason


class CreditTermsUpsert(BaseModel):
    payer_name: PayerName
    # advance and before_delivery: paid before the goods leave; at_delivery: paid on delivery;
    # credit: released before payment, up to the limit, due the given days after delivery (or booking).
    payment_terms: Literal["advance", "before_delivery", "at_delivery", "credit"] = "credit"
    credit_limit: Money | None = None
    credit_days: int | None = Field(default=None, ge=1, le=365)
    note: Note | None = None
    # Send automatic payment reminders to this customer.
    reminders: bool = True
    is_active: bool = True

    @model_validator(mode="after")
    def _shape(self) -> "CreditTermsUpsert":
        if (self.payment_terms == "credit") != (self.credit_limit is not None and self.credit_days is not None):
            raise ValueError("Credit needs a limit and a number of days; other terms take neither.")
        return self


class CreditTermsRead(BaseModel):
    id: uuid.UUID
    payer_name: str
    payment_terms: str
    credit_limit: Decimal | None
    credit_days: int | None
    note: str | None
    reminders: bool
    is_active: bool
    outstanding: Decimal
    # What is left before the limit, for customers on credit.
    available: Decimal | None
    approved_by: str


class ReleaseApprovalCreate(BaseModel):
    reason: Reason


class ShortageRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    amount: Decimal
    source: str
    status: str
    salary_month: dt.date | None
    note: str | None
    created_at: dt.datetime


class ShortageDecision(BaseModel):
    decision: Literal["recover_from_salary", "written_off", "found"]
    salary_month: dt.date | None = None
    note: Note

    @model_validator(mode="after")
    def _month(self) -> "ShortageDecision":
        if (self.decision == "recover_from_salary") != (self.salary_month is not None):
            raise ValueError("Give the salary month exactly when recovering from salary.")
        return self


class Alert(BaseModel):
    kind: str
    message: str
    ref: str | None


class Overview(BaseModel):
    """The owner's money trail for a period, what is held where right now, and what needs attention."""

    date_from: dt.date
    date_to: dt.date
    booked: Decimal
    collected_cash: Decimal
    collected_upi: Decimal
    collected_cheque: Decimal
    received_by_transfer: Decimal
    handed_over_expected: Decimal
    handed_over_counted: Decimal
    banked: Decimal
    shortages: Decimal
    receivable: Decimal
    custody: list[Custody]
    deposits_in_transit: Decimal
    upi_unconfirmed: Decimal
    cheques_uncleared: Decimal
    bank_credits_unallocated: Decimal
    exceptions: list[Alert]
