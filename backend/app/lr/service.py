import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import audit
from app.errors import conflict, not_found
from app.lr.schemas import LrDefaults, LrFields, LrSettingsUpdate, LrSuggestions
from app.models import DispatchLine, ItemType, Lr, LrSettings, User
from app.security import utcnow


def _settings(session: Session, company_id: uuid.UUID, *, for_update: bool = False) -> LrSettings:
    """The company's LR settings row, created with defaults the first time it is needed."""
    session.execute(insert(LrSettings).values(company_id=company_id).on_conflict_do_nothing())
    query = select(LrSettings).where(LrSettings.company_id == company_id)
    if for_update:
        query = query.with_for_update()
    return session.scalars(query).one()


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


def create(session: Session, actor: User, data: LrFields) -> Lr:
    """Assign the next number and save. The settings row lock makes concurrent saves take turns,
    and a failed save rolls the counter back, so the series has no gaps."""
    # A foreign key is checked outside row-level security, so confirm the item type is this company's.
    if data.item_type_id is not None and session.get(ItemType, data.item_type_id) is None:
        raise not_found("Item type")
    settings = _settings(session, actor.company_id, for_update=True)
    number = settings.next_number
    lr = Lr(
        company_id=actor.company_id,
        prefix=settings.prefix,
        series_no=number,
        lr_number=f"{settings.prefix}-{number}",
        created_by=actor.id,
        **data.model_dump(mode="python"),
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


def search(session: Session, *, q: str | None, limit: int, offset: int) -> list[Lr]:
    query = select(Lr).order_by(Lr.created_at.desc()).limit(limit).offset(offset)
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
