import uuid
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def set_tenant(session: Session, company_id: uuid.UUID) -> None:
    """Scope the current transaction to one company, all branches. Row-level security reads these values.
    A signed-in user's request is then narrowed to their branch by `set_branches`."""
    session.execute(
        text("SELECT set_config('app.company_id', :company_id, true), set_config('app.branches', 'all', true)"),
        {"company_id": str(company_id)},
    )


def set_branches(session: Session, branch_ids: list[uuid.UUID]) -> None:
    """Limit the current transaction to these branches' records."""
    session.execute(
        text("SELECT set_config('app.branches', :branches, true)"), {"branches": ",".join(str(b) for b in branch_ids)}
    )


def get_session() -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on any exception."""
    with SessionLocal() as session, session.begin():
        yield session
