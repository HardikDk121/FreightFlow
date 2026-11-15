import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Computed, Date, DateTime, Enum, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Role(enum.StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    DISPATCHER = "dispatcher"
    CLERK = "clerk"


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
    packages: Mapped[int] = mapped_column(Integer, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
