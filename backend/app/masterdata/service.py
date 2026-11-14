import uuid

from psycopg.errors import UniqueViolation
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute, Session

from app import audit
from app.errors import AppError, conflict, not_found
from app.models import ItemType, Party, Truck, User


class MasterDataService[M: (Party, ItemType, Truck)]:
    """Search, read, create and update for one master-data table. Rows are deactivated, never deleted."""

    def __init__(self, model: type[M], *, label: str, key: InstrumentedAttribute[str]) -> None:
        self._model = model
        self._label = label
        self._key = key

    def search(self, session: Session, *, q: str | None, include_inactive: bool, limit: int, offset: int) -> list[M]:
        query = select(self._model).order_by(self._key).limit(limit).offset(offset)
        if not include_inactive:
            query = query.where(self._model.is_active)
        if q:
            query = query.where(self._key.icontains(q, autoescape=True))
        return list(session.scalars(query))

    def get(self, session: Session, row_id: uuid.UUID) -> M:
        row = session.get(self._model, row_id)
        if row is None:
            raise not_found(self._label)
        return row

    def create(self, session: Session, actor: User, data: BaseModel) -> M:
        row = self._model(company_id=actor.company_id, **data.model_dump())
        session.add(row)
        self._save(session, actor, row, "create", data.model_dump(mode="json"))
        return row

    def update(self, session: Session, actor: User, row_id: uuid.UUID, data: BaseModel) -> M:
        row = self.get(session, row_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(row, field, value)
        self._save(session, actor, row, "update", data.model_dump(exclude_unset=True, mode="json"))
        return row

    def _save(self, session: Session, actor: User, row: M, verb: str, detail: dict) -> None:
        try:
            session.flush()
        except IntegrityError as exc:
            if isinstance(exc.orig, UniqueViolation):
                raise conflict(f"A {self._label.lower()} with that {self._key.key} already exists.") from exc
            raise AppError(422, "invalid", f"{self._label} values break a database rule.") from exc
        audit.record(
            session,
            company_id=actor.company_id,
            actor_id=actor.id,
            action=f"{self._model.__tablename__}.{verb}",
            entity=self._model.__tablename__,
            entity_id=row.id,
            detail=detail,
        )


parties = MasterDataService(Party, label="Party", key=Party.name)
item_types = MasterDataService(ItemType, label="Item type", key=ItemType.name)
trucks = MasterDataService(Truck, label="Truck", key=Truck.vehicle_number)
