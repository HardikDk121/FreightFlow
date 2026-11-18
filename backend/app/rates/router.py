from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user
from app.models import User
from app.rates import service
from app.rates.schemas import QuoteRead, QuoteRequest

router = APIRouter(prefix="/rates", tags=["rates"])


@router.get("/classes", response_model=list[str])
def list_goods_classes(_: User = Depends(current_user), session: Session = Depends(get_session)) -> list[str]:
    """The classes of goods that have a rate, for the LR form's picker."""
    return service.goods_classes(session)


@router.post("/quote", response_model=QuoteRead)
def quote_freight(body: QuoteRequest, _: User = Depends(current_user), session: Session = Depends(get_session)) -> QuoteRead:
    """Freight for these goods to this destination, with the working shown. Saves nothing."""
    return service.price(session, body)
