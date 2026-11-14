import uuid

from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    session: Session,
    *,
    company_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    entity: str,
    entity_id: uuid.UUID,
    detail: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            company_id=company_id,
            actor_id=actor_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            detail=detail,
        )
    )
