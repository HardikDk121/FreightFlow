import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user
from app.models import User
from app.payments import service
from app.payments.schemas import Ageing, LrAccount, Priorities, Receivables
from app.permissions import P, require

router = APIRouter(tags=["payments"])
# The register clerk issues money receipts, so sees what each payer owes.
_owner = require(P.MONEY_RECEIVABLES)


@router.get("/lrs/{lr_id}/account", response_model=LrAccount)
def get_lr_account(lr_id: uuid.UUID, _: User = Depends(current_user), session: Session = Depends(get_session)) -> LrAccount:
    """What this LR is owed, what has been received, and each collection set against it."""
    return service.lr_account(session, lr_id)


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


@router.get("/receivables/ageing", response_model=Ageing)
def get_ageing(_: User = Depends(_owner), session: Session = Depends(get_session)) -> Ageing:
    """Outstanding by days past due: not due, 0-7, 8-15, 16-30, 31-60 and over 60 days."""
    return service.ageing(session)


@router.get("/receivables/priorities", response_model=Priorities)
def get_priorities(_: User = Depends(_owner), session: Session = Depends(get_session)) -> Priorities:
    """Where the money is stuck, for deciding whom to chase first."""
    return service.priorities(session)
