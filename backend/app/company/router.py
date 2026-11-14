from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.company import service
from app.company.schemas import CompanyRead, CompanyUpdate
from app.db import get_session
from app.deps import current_user, require_roles
from app.models import Role, User

router = APIRouter(prefix="/company", tags=["company"])


@router.get("", response_model=CompanyRead)
def get_company(user: User = Depends(current_user), session: Session = Depends(get_session)) -> CompanyRead:
    return CompanyRead.model_validate(service.get_company(session, user))


@router.patch("", response_model=CompanyRead)
def update_company(
    body: CompanyUpdate,
    actor: User = Depends(require_roles(Role.ADMIN)),
    session: Session = Depends(get_session),
) -> CompanyRead:
    return CompanyRead.model_validate(service.update_company(session, actor, body))
