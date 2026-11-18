import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user, require_roles
from app.models import Role, User
from app.payments import service
from app.payments.schemas import LrAccount, PaymentCreate, Receivables

router = APIRouter(tags=["payments"])
_cashier = require_roles(Role.ADMIN, Role.MANAGER, Role.CLERK)
_owner = require_roles(Role.ADMIN, Role.MANAGER)


@router.get("/lrs/{lr_id}/account", response_model=LrAccount)
def get_lr_account(lr_id: uuid.UUID, _: User = Depends(current_user), session: Session = Depends(get_session)) -> LrAccount:
    """What this LR is owed, what has been received, and each payment."""
    return service.lr_account(session, lr_id)


@router.post("/lrs/{lr_id}/payments", response_model=LrAccount, status_code=status.HTTP_201_CREATED)
def record_payment(
    lr_id: uuid.UUID, body: PaymentCreate, actor: User = Depends(_cashier), session: Session = Depends(get_session)
) -> LrAccount:
    """Record money received against an LR: an advance, a part payment, or the balance."""
    return service.record(session, actor, lr_id, body)


@router.get("/receivables", response_model=Receivables)
def get_receivables(_: User = Depends(_owner), session: Session = Depends(get_session)) -> Receivables:
    return service.receivables(session)


@router.get("/receivables/lrs", response_model=list[LrAccount])
def list_open_lrs(
    party: Annotated[str | None, Query(max_length=60)] = None,
    _: User = Depends(_owner),
    session: Session = Depends(get_session),
) -> list[LrAccount]:
    """LRs with money still owed, oldest first, optionally for one payer."""
    return service.open_accounts(session, party)
