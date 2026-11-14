from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.schemas import AcceptInviteRequest, LoginRequest, RefreshRequest, RegisterRequest, TokenPair
from app.db import get_session
from app.deps import current_user
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, session: Session = Depends(get_session)) -> TokenPair:
    return service.register(session, body)


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, session: Session = Depends(get_session)) -> TokenPair:
    return service.login(session, body.login, body.password)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, session: Session = Depends(get_session)) -> TokenPair:
    return service.refresh(session, body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    body: RefreshRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Response:
    service.logout(session, user, body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invites/accept", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def accept_invite(body: AcceptInviteRequest, session: Session = Depends(get_session)) -> TokenPair:
    return service.accept_invite(session, body)
