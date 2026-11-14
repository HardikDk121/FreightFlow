import uuid
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def set_tenant(session: Session, company_id: uuid.UUID) -> None:
    """Scope the current transaction to one company. Row-level security reads this value."""
    session.execute(
        text("SELECT set_config('app.company_id', :company_id, true)"),
        {"company_id": str(company_id)},
    )


def get_session() -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on any exception."""
    with SessionLocal() as session, session.begin():
        yield session
