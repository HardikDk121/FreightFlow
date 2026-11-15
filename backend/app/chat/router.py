from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.chat import service
from app.chat.schemas import ChatRequest, ChatResponse
from app.db import get_session
from app.deps import current_user
from app.models import User

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def ask(body: ChatRequest, user: User = Depends(current_user), session: Session = Depends(get_session)) -> ChatResponse:
    """Answer a question from the fixed list of read-only tools. Every question is written to the audit log."""
    return service.ask(session, user, body.message, body.context_lr_number)
