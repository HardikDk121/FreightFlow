import datetime as dt
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import audit, branches
from app.errors import AppError, conflict, not_found
from app.eway.rules import Consignment, Requirement, evaluate
from app.collections import credit
from app.lr.schemas import LrCreate, LrDefaults, LrFields, LrSettingsUpdate, LrSuggestions, PartySuggestion
from app.models import (
    CollectionAllocation,
    DispatchLine,
    GatePass,
    ItemType,
    Lr,
    LrSettings,
    MoneyReceipt,
    MoneyReceiptLine,
    Party,
    RateRule,
    User,
)
from app.security import utcnow


def _settings(session: Session, company_id: uuid.UUID, *, for_update: bool = False) -> LrSettings:
    """The company's LR settings row, created with defaults the first time it is needed."""
    session.execute(insert(LrSettings).values(company_id=company_id).on_conflict_do_nothing())
    query = select(LrSettings).where(LrSettings.company_id == company_id)
    if for_update:
        query = query.with_for_update()
    return session.scalars(query).one()


def take_trip_number(session: Session, company_id: uuid.UUID) -> int:
    """The next trip number for this company. The settings row lock makes concurrent dispatches
    take turns, and a failed dispatch rolls the counter back."""
    settings = _settings(session, company_id, for_update=True)
    number = settings.next_trip_number
    settings.next_trip_number = number + 1
    return number


_COUNTERS = {
    "receipt": ("next_receipt_number", "receipt_prefix"),
    "gate_pass": ("next_gate_pass_number", "gate_pass_prefix"),
    "deposit": ("next_deposit_number", None),
}


def take_document_number(session: Session, company_id: uuid.UUID, kind: str) -> str:
    """The next number for a money receipt, gate pass or deposit batch, gap-free like LR numbers.
    Receipts and gate passes take the company's prefix ("MR-12"), or none to continue a paper
    series ("90013"); deposits are always "DEP-n", the form written on bank slips."""
    column, prefix_column = _COUNTERS[kind]
    settings = _settings(session, company_id, for_update=True)
    number = getattr(settings, column)
    setattr(settings, column, number + 1)
    prefix = getattr(settings, prefix_column) if prefix_column else "DEP"
    return f"{prefix}-{number}" if prefix else str(number)


def collector_cash_limit(session: Session, company_id: uuid.UUID):
    return _settings(session, company_id).collector_cash_limit


def get_settings(session: Session, user: User) -> LrSettings:
    return _settings(session, user.company_id)


def update_settings(session: Session, actor: User, data: LrSettingsUpdate) -> LrSettings:
    settings = _settings(session, actor.company_id, for_update=True)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(settings, field, value)
    highest = session.scalar(select(func.max(Lr.series_no)).where(Lr.prefix == settings.prefix))
    if highest is not None and settings.next_number <= highest:
        raise conflict(f"LR {settings.prefix}-{highest} already exists. The next number must be higher.")
    # The next receipt or gate pass number must not have been used already.
    for model, column, prefix, number, label in (
        (MoneyReceipt, MoneyReceipt.receipt_number, settings.receipt_prefix, settings.next_receipt_number, "Money receipt"),
        (GatePass, GatePass.gate_pass_number, settings.gate_pass_prefix, settings.next_gate_pass_number, "Gate pass"),
    ):
        candidate = f"{prefix}-{number}" if prefix else str(number)
        if session.scalar(select(model.id).where(column == candidate)) is not None:
            raise conflict(f"{label} {candidate} already exists. Choose a higher next number.")
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="lr_settings.update",
        entity="lr_settings",
        entity_id=actor.company_id,
        detail=data.model_dump(exclude_unset=True, mode="json"),
    )
    return settings


def defaults(session: Session, user: User) -> LrDefaults:
    settings = _settings(session, user.company_id)
    return LrDefaults(
        next_lr_number=f"{settings.prefix}-{settings.next_number}",
        from_city=settings.from_city,
        st_charges=settings.default_st_charges,
    )


def suggestions(session: Session, consignor_name: str | None, consignor_gstin: str | None) -> LrSuggestions:
    """Match on GSTIN when given, since names are spelled many ways; otherwise on the name."""
    if consignor_gstin:
        match = Lr.consignor_gstin == consignor_gstin.strip().upper()
    elif consignor_name and consignor_name.strip():
        match = func.lower(Lr.consignor_name) == consignor_name.strip().lower()
    else:
        return LrSuggestions()
    latest = session.scalars(
        select(Lr).where(match, Lr.status == "confirmed").order_by(Lr.created_at.desc()).limit(1)
    ).first()
    if latest is None:
        return LrSuggestions()
    return LrSuggestions(
        freight_by=latest.freight_by,
        packages=latest.packages,
        goods_description=latest.goods_description,
        consignor_gstin=latest.consignor_gstin,
        item_type_id=latest.item_type_id,
    )


def _check_matrix_freight(session: Session, data: LrFields) -> None:
    """Freight from the rate matrix is priced again here, so it cannot be typed over."""
    from app.rates.schemas import QuoteRequest
    from app.rates.service import price

    rule = session.get_one(RateRule, data.rate_rule_id)
    quote = price(
        session,
        QuoteRequest(
            goods_class=rule.goods_class,
            to_city=data.to_city,
            packages=data.packages,
            weight_per_package=data.weight_per_package,
            total_weight=data.charged_weight or data.weight,
        ),
    )
    if quote.freight != data.freight:
        raise AppError(422, "freight_mismatch", f"The rate matrix gives Rs {quote.freight:,.2f} for this LR, not Rs {data.freight:,.2f}.")


def create(session: Session, actor: User, data: LrCreate) -> Lr:
    """Assign the next number and save. The settings row lock makes concurrent saves take turns,
    and a failed save rolls the counter back, so the series has no gaps."""
    # A foreign key is checked outside row-level security, so confirm the item type is this company's.
    if data.item_type_id is not None and session.get(ItemType, data.item_type_id) is None:
        raise not_found("Item type")
    if data.rate_rule_id is not None and session.get(RateRule, data.rate_rule_id) is None:
        raise not_found("Rate")
    if data.charge_basis == "matrix":
        _check_matrix_freight(session, data)
    total = data.freight + data.hamali + data.other_charges + data.st_charges
    payer = data.consignee_name if data.freight_by == "ToPay" else data.consignor_name
    override = credit.booking_check(session, actor, payer, data.freight_by, total, data.credit_override_reason)
    requirement = evaluate(
        Consignment(
            value=data.value,
            from_state=data.from_state,
            to_state=data.to_state,
            category=data.goods_category,
            consignor_registered=data.consignor_gstin is not None,
            consignee_registered=data.consignee_gstin is not None,
            distance_km=data.distance_km,
            leg=data.trip_leg,
        )
    )
    if requirement.required is None:
        raise AppError(422, "value_needed", requirement.reason)
    if requirement.required and data.distance_km is None:
        raise AppError(422, "distance_needed", "This LR needs an e-way bill, so enter the distance in km.")
    settings = _settings(session, actor.company_id, for_update=True)
    number = settings.next_number
    lr = Lr(
        ewb_status=_ewb_status(requirement, data.eway_bill_no),
        ewb_responsible=requirement.responsible,
        ewb_part_b_required=requirement.part_b_required,
        ewb_reason=f"{requirement.reason} ({requirement.rule})",
        company_id=actor.company_id,
        prefix=settings.prefix,
        series_no=number,
        lr_number=f"{settings.prefix}-{number}",
        created_by=actor.id,
        credit_override_reason=override,
        branch_id=branches.home_branch(session, actor),
        delivery_branch_id=branches.delivering_branch(session, data.to_city),
        **data.model_dump(mode="python", exclude={"credit_override_reason"}),
    )
    session.add(lr)
    settings.next_number = number + 1
    session.flush()
    session.refresh(lr)
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="lr.create",
        entity="lr",
        entity_id=lr.id,
        detail={"lr_number": lr.lr_number},
    )
    return lr


def _ewb_status(requirement: Requirement, eway_bill_no: str | None) -> str:
    if not requirement.required:
        return "exempt" if requirement.rule == "Rule 138(14)" else "not_required"
    if eway_bill_no is None:
        return "pending"
    # With Part A done, the bill covers the road only once a vehicle is entered in Part B.
    return "awaiting_part_b" if requirement.part_b_required else "active"


def set_eway_bill(session: Session, actor: User, lr_id: uuid.UUID, eway_bill_no: str) -> Lr:
    """Record the e-way bill number once it has been generated. It is entered once and then locked,
    like the rest of Part A."""
    lr = get(session, lr_id, for_update=True)
    if lr.status == "cancelled":
        raise conflict("This LR is cancelled.")
    if lr.eway_bill_no is not None:
        raise conflict(f"LR {lr.lr_number} already has e-way bill {lr.eway_bill_no}.")
    lr.eway_bill_no = eway_bill_no
    if lr.ewb_status == "pending":
        lr.ewb_status = "awaiting_part_b" if lr.ewb_part_b_required else "active"
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="lr.set_eway_bill",
        entity="lr",
        entity_id=lr.id,
        detail={"lr_number": lr.lr_number, "eway_bill_no": eway_bill_no},
    )
    return lr


def search(
    session: Session,
    *,
    q: str | None,
    limit: int,
    offset: int,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> list[Lr]:
    query = select(Lr).order_by(Lr.created_at.desc()).limit(limit).offset(offset)
    if date_from is not None:
        query = query.where(Lr.lr_date >= date_from)
    if date_to is not None:
        query = query.where(Lr.lr_date <= date_to)
    if q:
        query = query.where(
            or_(
                Lr.lr_number.icontains(q, autoescape=True),
                Lr.consignor_name.icontains(q, autoescape=True),
                Lr.consignee_name.icontains(q, autoescape=True),
            )
        )
    return list(session.scalars(query))


def get(session: Session, lr_id: uuid.UUID, *, for_update: bool = False) -> Lr:
    lr = session.get(Lr, lr_id, with_for_update=for_update)
    if lr is None:
        raise not_found("LR")
    return lr


def cancel(session: Session, actor: User, lr_id: uuid.UUID, reason: str) -> Lr:
    lr = get(session, lr_id, for_update=True)
    if lr.status == "cancelled":
        raise conflict("This LR is already cancelled.")
    if session.scalar(select(DispatchLine.id).where(DispatchLine.lr_id == lr.id).limit(1)) is not None:
        raise conflict("This LR has already been dispatched, so it cannot be cancelled.")
    if session.scalar(select(CollectionAllocation.id).where(CollectionAllocation.lr_id == lr.id).limit(1)) is not None:
        raise conflict("Money has been received against this LR, so it cannot be cancelled.")
    open_receipt = session.scalar(
        select(MoneyReceipt.receipt_number)
        .join(MoneyReceiptLine, MoneyReceiptLine.receipt_id == MoneyReceipt.id)
        .where(MoneyReceiptLine.lr_id == lr.id, MoneyReceipt.status == "open")
    )
    if open_receipt is not None:
        raise conflict(f"Money receipt {open_receipt} is open for this LR. Cancel the receipt first.")
    lr.status = "cancelled"
    lr.cancelled_by = actor.id
    lr.cancelled_at = utcnow()
    lr.cancel_reason = reason
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="lr.cancel",
        entity="lr",
        entity_id=lr.id,
        detail={"lr_number": lr.lr_number, "reason": reason},
    )
    return lr


def booked_between(session: Session, date_from: dt.date, date_to: dt.date) -> list[Lr]:
    return list(
        session.scalars(select(Lr).where(Lr.lr_date.between(date_from, date_to)).order_by(Lr.lr_date, Lr.series_no))
    )


def suggest_parties(session: Session, q: str, role: str, limit: int = 6) -> list[PartySuggestion]:
    """Names from past LRs first (they carry the GSTIN and city actually used), then the party master."""
    name = Lr.consignor_name if role == "consignor" else Lr.consignee_name
    gstin = Lr.consignor_gstin if role == "consignor" else Lr.consignee_gstin
    found: dict[str, PartySuggestion] = {}
    past = session.execute(
        select(name, gstin, Lr.to_city)
        .where(name.icontains(q, autoescape=True), Lr.status == "confirmed")
        .order_by(Lr.created_at.desc())
        .limit(50)
    ).all()
    for party_name, party_gstin, to_city in past:
        found.setdefault(
            party_name.lower(),
            PartySuggestion(name=party_name, gstin=party_gstin, city=to_city if role == "consignee" else None),
        )
    master = session.scalars(
        select(Party).where(Party.name.icontains(q, autoescape=True), Party.is_active).order_by(Party.name).limit(limit)
    )
    for party in master:
        found.setdefault(party.name.lower(), PartySuggestion(name=party.name.upper(), gstin=party.gstin, city=None))
    return list(found.values())[:limit]
