from sqlalchemy.orm import Session

from app import audit
from app.company.schemas import CompanyUpdate
from app.models import Company, User


def get_company(session: Session, user: User) -> Company:
    # Present for every authenticated user: app_user.company_id is a foreign key.
    return session.get_one(Company, user.company_id)


def update_company(session: Session, actor: User, data: CompanyUpdate) -> Company:
    company = get_company(session, actor)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(company, field, value)
    session.flush()
    audit.record(
        session,
        company_id=company.id,
        actor_id=actor.id,
        action="company.update",
        entity="company",
        entity_id=company.id,
        detail=changes,
    )
    return company
