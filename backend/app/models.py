import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Role(enum.StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    DISPATCHER = "dispatcher"
    CLERK = "clerk"
    # Goes to customers with the money receipt and records what they paid.
    COLLECTOR = "collector"
    # Keeps the branch register: issues receipts, receives and counts handovers, deposits.
    REGISTER_CLERK = "register_clerk"
    # Payments, receipts, cash reconciliation and financial reports.
    ACCOUNTANT = "accountant"


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _company_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("company.id"), nullable=False)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


def _measure() -> Mapped[float]:
    return mapped_column(Numeric(10, 2, asdecimal=False), nullable=False)


_role_type = Enum(
    Role, name="user_role", values_callable=lambda e: [m.value for m in e], create_type=False
)


class Company(Base):
    __tablename__ = "company"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(Text)
    # Printed on the LR header with the name, address and GSTIN.
    tagline: Mapped[str | None] = mapped_column(Text)
    # Account name, number, IFSC (and UPI ID, when there is one), printed on money receipts.
    bank_details: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class User(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    phone: Mapped[str | None] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[Role] = mapped_column(_role_type, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False, default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # None: works across all branches. The owner (admin) always does.
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branch.id"))
    permissions_granted: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    permissions_revoked: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class AuthToken(Base):
    """A refresh token. Only its hash is stored."""

    __tablename__ = "auth_token"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # True when the token was revoked by being exchanged for a new one.
    rotated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created_at()


class UserInvite(Base):
    __tablename__ = "user_invite"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    role: Mapped[Role] = mapped_column(_role_type, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branch.id"))
    created_at: Mapped[datetime] = _created_at()


class Party(Base):
    """A consignor or consignee."""

    __tablename__ = "party"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6, asdecimal=False))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6, asdecimal=False))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class ItemType(Base):
    """Item master: the size and weight of one unit of a goods type."""

    __tablename__ = "item_type"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    length_cm: Mapped[float] = _measure()
    width_cm: Mapped[float] = _measure()
    height_cm: Mapped[float] = _measure()
    unit_weight_kg: Mapped[float] = _measure()
    stackable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Truck(Base):
    __tablename__ = "truck"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    vehicle_number: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    inner_length_cm: Mapped[float] = _measure()
    inner_width_cm: Mapped[float] = _measure()
    inner_height_cm: Mapped[float] = _measure()
    payload_kg: Mapped[float] = _measure()
    model_year: Mapped[int | None] = mapped_column(Integer)
    insurance_expiry: Mapped[date | None] = mapped_column(Date)
    fitness_expiry: Mapped[date | None] = mapped_column(Date)
    # Where the truck stands when it is not on a trip: the last stop of its last trip.
    current_station: Mapped[str | None] = mapped_column(Text)
    # The truck's owner, from whom it is hired.
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendor.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class AuditLog(Base):
    """Append-only. The app database role has no UPDATE or DELETE on this table."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[uuid.UUID] = _company_fk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()


class LrSettings(Base):
    """One row per company: the LR number series and the values a new LR starts with."""

    __tablename__ = "lr_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("company.id"), primary_key=True)
    prefix: Mapped[str] = mapped_column(Text, nullable=False, default="LR")
    next_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    from_city: Mapped[str | None] = mapped_column(Text)
    default_st_charges: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    next_trip_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_receipt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_gate_pass_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_deposit_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    collector_cash_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("25000"))
    credit_from: Mapped[str] = mapped_column(Text, nullable=False, default="delivery")
    overdue_hold_days: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    credit_controls_from: Mapped[date | None] = mapped_column(Date)
    # "MR" prints MR-90012; empty prints 90012, to continue a paper series.
    receipt_prefix: Mapped[str] = mapped_column(Text, nullable=False, default="MR")
    gate_pass_prefix: Mapped[str] = mapped_column(Text, nullable=False, default="GP")
    next_rfq_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = _updated_at()


class Lr(Base):
    """A printed LR. Values are a snapshot of what was printed; editing a party later does not change them."""

    __tablename__ = "lr"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    prefix: Mapped[str] = mapped_column(Text, nullable=False)
    series_no: Mapped[int] = mapped_column(Integer, nullable=False)
    lr_number: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="confirmed")
    lr_date: Mapped[date] = mapped_column(Date, nullable=False)
    from_city: Mapped[str] = mapped_column(Text, nullable=False)
    to_city: Mapped[str] = mapped_column(Text, nullable=False)
    freight_by: Mapped[str] = mapped_column(Text, nullable=False)
    consignor_name: Mapped[str] = mapped_column(Text, nullable=False)
    consignor_gstin: Mapped[str | None] = mapped_column(Text)
    consignee_name: Mapped[str] = mapped_column(Text, nullable=False)
    consignee_gstin: Mapped[str | None] = mapped_column(Text)
    goods_description: Mapped[str] = mapped_column(Text, nullable=False)
    packages: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    charged_weight: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    freight: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    hamali: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    other_charges: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    st_charges: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), Computed("freight + hamali + other_charges + st_charges", persisted=True)
    )
    value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    eway_bill_no: Mapped[str | None] = mapped_column(Text)
    # What one package is, when known. Gives the load planner its size and weight.
    item_type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_type.id"))
    # E-way bill. The first block is what the clerk enters; the ewb_* block is the engine's
    # decision at booking, then the bill's progress. States are two-digit GST state codes.
    from_state: Mapped[str | None] = mapped_column(Text)
    to_state: Mapped[str | None] = mapped_column(Text)
    goods_category: Mapped[str] = mapped_column(Text, nullable=False, default="regular")
    trip_leg: Mapped[str] = mapped_column(Text, nullable=False, default="direct")
    distance_km: Mapped[int | None] = mapped_column(Integer)
    hsn_code: Mapped[str | None] = mapped_column(Text)
    consignor_pan: Mapped[str | None] = mapped_column(Text)
    consignee_pan: Mapped[str | None] = mapped_column(Text)
    enrolment_id: Mapped[str | None] = mapped_column(Text)
    ewb_status: Mapped[str] = mapped_column(Text, nullable=False, default="not_assessed")
    ewb_responsible: Mapped[str | None] = mapped_column(Text)
    ewb_part_b_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ewb_reason: Mapped[str | None] = mapped_column(Text)
    ewb_vehicle_number: Mapped[str | None] = mapped_column(Text)
    ewb_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Pricing: what one package weighs, and the rate rule the freight was worked out from.
    weight_per_package: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    # per_kg, per_article or matrix; null on LRs saved before the basis was recorded.
    charge_basis: Mapped[str | None] = mapped_column(Text)
    # Where it was booked, and the branch that delivers it (from the destination city).
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), nullable=False)
    delivery_branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branch.id"))
    credit_override_reason: Mapped[str | None] = mapped_column(Text)
    rate_rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rate_rule.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)


class Trip(Base):
    """One truck sent out with a set of LRs. Created at dispatch; completed when every line is delivered."""

    __tablename__ = "trip"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    truck_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("truck.id"), nullable=False)
    # Counts up per company. Challans are numbered from it: CH-12, then CH-12/S1 for added cargo.
    trip_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # The branch that sent it out, and the branches whose stops it serves (they see it too).
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), nullable=False)
    stop_branch_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    # The stations in the order the truck reaches them. `destination` is the last one.
    route: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    driver_name: Mapped[str | None] = mapped_column(Text)
    driver_phone: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="dispatched")
    dispatched_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DispatchLine(Base):
    """Packages of one LR loaded on one trip. An LR split across trucks has one line per trip."""

    __tablename__ = "dispatch_line"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip.id"), nullable=False)
    lr_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lr.id"), nullable=False)
    # The sealed document this loading is recorded on.
    challan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("challan.id"), nullable=False)
    packages: Mapped[int] = mapped_column(Integer, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))


class PasswordReset(Base):
    """A six-digit reset code, stored as a keyed hash. Single use, short-lived, five wrong tries at most."""

    __tablename__ = "password_reset"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class AuthThrottle(Base):
    __tablename__ = "auth_throttle"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Station(Base):
    """A delivery station, the zone whose rates it uses, and what it adds per kg on top."""

    __tablename__ = "station"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    zone: Mapped[str] = mapped_column(Text, nullable=False)
    surcharge_per_kg: Mapped[float] = mapped_column(Numeric(8, 2, asdecimal=False), nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Route(Base):
    """Stations one truck serves in a single run, in order."""

    __tablename__ = "route"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    stops: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class RateRule(Base):
    """How freight is charged for one class of goods in one zone."""

    __tablename__ = "rate_rule"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    goods_class: Mapped[str] = mapped_column(Text, nullable=False)
    zone: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    rate: Mapped[float | None] = mapped_column(Numeric(10, 2, asdecimal=False))
    slabs: Mapped[list[dict] | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Challan(Base):
    """A sealed list of what was put on a truck at one place. A trip has one primary challan and
    one supplementary challan for each time cargo is added on the road. The database role the API
    runs as cannot change a challan's trip, number, requester or requested lines."""

    __tablename__ = "challan"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    challan_number: Mapped[str] = mapped_column(Text, nullable=False)
    loaded_at: Mapped[str] = mapped_column(Text, nullable=False)
    insert_before: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    requested_lines: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    driver_name: Mapped[str | None] = mapped_column(Text)
    driver_signature: Mapped[list | None] = mapped_column(JSONB)
    shortage_note: Mapped[str | None] = mapped_column(Text)
    voided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(Text)
    prev_hash: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)


class MoneyReceipt(Base):
    """A numbered demand for payment, issued only by the app, for one payer's LRs."""

    __tablename__ = "money_receipt"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), nullable=False)
    receipt_number: Mapped[str] = mapped_column(Text, nullable=False)
    payer_name: Mapped[str] = mapped_column(Text, nullable=False)
    payer_phone: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    verify_hash: Mapped[str] = mapped_column(Text, nullable=False)
    issued_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)


class MoneyReceiptLine(Base):
    __tablename__ = "money_receipt_line"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("money_receipt.id"), nullable=False)
    lr_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lr.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class CollectionVisit(Base):
    """One call on a customer: paid, part paid, asked to come later, or refused."""

    __tablename__ = "collection_visit"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("money_receipt.id"), nullable=False)
    collector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    visited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    promised_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)


class Collection(Base):
    """Money received from a customer, and where it is now. Counts as reaching the company only
    when the bank statement shows it (status confirmed)."""

    __tablename__ = "collection"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), nullable=False)
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("money_receipt.id"))
    visit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_visit.id"))
    payer_name: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    utr: Mapped[str | None] = mapped_column(Text)
    cheque_number: Mapped[str | None] = mapped_column(Text)
    cheque_bank: Mapped[str | None] = mapped_column(Text)
    cheque_date: Mapped[date | None] = mapped_column(Date)
    collected_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bank_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_statement_line.id"))
    handover_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cash_handover.id"))
    deposit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_deposit.id"))
    failed_reason: Mapped[str | None] = mapped_column(Text)


class CollectionAllocation(Base):
    """How much of a collection settles each LR."""

    __tablename__ = "collection_allocation"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection.id"), nullable=False)
    lr_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lr.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class CashHandover(Base):
    """A collector's cash and cheques passed to a second person, who counts them against what the app expects."""

    __tablename__ = "cash_handover"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), nullable=False)
    from_user: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    to_user: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    expected_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    counted_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    handed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    from_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deposit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_deposit.id"))


class BankDeposit(Base):
    __tablename__ = "bank_deposit"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), nullable=False)
    deposit_number: Mapped[str] = mapped_column(Text, nullable=False)
    depositor: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    expected_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    cash_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    slip_reference: Mapped[str | None] = mapped_column(Text)
    deposited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(Text, nullable=False, default="in_transit")
    bank_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_statement_line.id"))


class BankImport(Base):
    __tablename__ = "bank_import"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    lines_read: Mapped[int] = mapped_column(Integer, nullable=False)
    lines_new: Mapped[int] = mapped_column(Integer, nullable=False)
    imported_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BankStatementLine(Base):
    __tablename__ = "bank_statement_line"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_import.id"), nullable=False)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    narration: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(Text)
    refs: Mapped[str] = mapped_column(Text, nullable=False, default="")
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal(0))
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal(0))
    balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    row_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="unmatched")
    matched_kind: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    note: Mapped[str | None] = mapped_column(Text)


class StatementFormat(Base):
    __tablename__ = "statement_format"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("company.id"), primary_key=True)
    columns: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = _updated_at()


class Shortage(Base):
    """Money that should have been handed over or banked but was not, against a named person."""

    __tablename__ = "shortage"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    salary_month: Mapped[date | None] = mapped_column(Date)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class CreditTerms(Base):
    """The owner's standing approval to release a regular customer's to-pay goods before payment."""

    __tablename__ = "credit_terms"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    payer_name: Mapped[str] = mapped_column(Text, nullable=False)
    # advance, before_delivery, at_delivery, or credit (which needs a limit and days).
    payment_terms: Mapped[str] = mapped_column(Text, nullable=False, default="credit")
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    credit_days: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    reminders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    updated_at: Mapped[datetime] = _updated_at()


class ReleaseApproval(Base):
    __tablename__ = "release_approval"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    lr_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lr.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GatePass(Base):
    """Release of a consignee's goods at the destination, as on the paper gate pass: several LRs, the local
    vehicle and its driver, and, once delivered, the consignee's signature as proof of delivery."""

    __tablename__ = "gate_pass"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), nullable=False)
    gate_pass_number: Mapped[str] = mapped_column(Text, nullable=False)
    consignee_name: Mapped[str] = mapped_column(Text, nullable=False)
    auto_no: Mapped[str | None] = mapped_column(Text)
    driver_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="issued")
    issued_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pod_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receiver_name: Mapped[str | None] = mapped_column(Text)
    receiver_phone: Mapped[str | None] = mapped_column(Text)
    signature: Mapped[list | None] = mapped_column(JSONB)
    photo: Mapped[bytes | None] = mapped_column(LargeBinary)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    pod_recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    void_reason: Mapped[str | None] = mapped_column(Text)
    voided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class CustomerNotice(Base):
    __tablename__ = "customer_notice"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection.id"), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class IdempotencyKey(Base):
    __tablename__ = "idempotency_key"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("company.id"), primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()


class Branch(Base):
    __tablename__ = "branch"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    cities: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    is_head_office: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class LrCharge(Base):
    """A charge added at the destination on a money receipt: labour, door delivery (DC) or demurrage."""

    __tablename__ = "lr_charge"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    lr_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lr.id"), nullable=False)
    receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("money_receipt.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GatePassLine(Base):
    __tablename__ = "gate_pass_line"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    gate_pass_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gate_pass.id"), nullable=False)
    lr_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lr.id"), nullable=False)
    packages: Mapped[int] = mapped_column(Integer, nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)


class CollectionTask(Base):
    """One customer to collect from, created by the app when money falls due, assigned to a person."""

    __tablename__ = "collection_task"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), nullable=False)
    payer_name: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    amount_due: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    oldest_due: Mapped[date] = mapped_column(Date, nullable=False)
    next_action_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_on: Mapped[date] = mapped_column(Date, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class TaskAttempt(Base):
    __tablename__ = "task_attempt"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_task.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    promised_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Reminder(Base):
    __tablename__ = "reminder"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    payer_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    sent_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class ApprovalRequest(Base):
    """Staff ask; the owner (or someone given the permission) decides."""

    __tablename__ = "approval_request"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    lr_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lr.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)


class SavedReport(Base):
    __tablename__ = "saved_report"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    analysis: Mapped[str] = mapped_column(Text, nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    custom: Mapped[dict | None] = mapped_column(JSONB)
    schedule: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    recipients: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    last_sent_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _created_at()


class Vendor(Base):
    """A truck owner or broker the company hires trucks from."""

    __tablename__ = "vendor"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text)
    pan: Mapped[str | None] = mapped_column(Text)
    bank_details: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class TripHire(Base):
    __tablename__ = "trip_hire"

    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip.id"), primary_key=True)
    company_id: Mapped[uuid.UUID] = _company_fk()
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendor.id"), nullable=False)
    hire_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    rfq_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rfq.id"))
    note: Mapped[str | None] = mapped_column(Text)
    agreed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VendorPayment(Base):
    __tablename__ = "vendor_payment"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip.id"), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendor.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    paid_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TripDeduction(Base):
    __tablename__ = "trip_deduction"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TripExpense(Base):
    __tablename__ = "trip_expense"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contract(Base):
    __tablename__ = "contract"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    party_name: Mapped[str] = mapped_column(Text, nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    terms: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class ContractRate(Base):
    __tablename__ = "contract_rate"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contract.id"), nullable=False)
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)


class TransitTime(Base):
    __tablename__ = "transit_time"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    days_min: Mapped[int] = mapped_column(Integer, nullable=False)
    days_max: Mapped[int] = mapped_column(Integer, nullable=False)


class Rfq(Base):
    __tablename__ = "rfq"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), nullable=False)
    rfq_number: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    truck_type: Mapped[str | None] = mapped_column(Text)
    needed_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    awarded_quote_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rfq_quote.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RfqInvite(Base):
    __tablename__ = "rfq_invite"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    rfq_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rfq.id"), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendor.id"), nullable=False)
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RfqQuote(Base):
    __tablename__ = "rfq_quote"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_fk()
    rfq_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rfq.id"), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendor.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    vehicle_number: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
