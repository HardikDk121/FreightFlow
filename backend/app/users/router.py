import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.auth.schemas import TokenPair
from app.db import get_session
from app.deps import current_user, require_roles
from app.models import Role, User
from app.users import service
from app.users.schemas import (
    AdminPasswordReset,
    ChangePasswordRequest,
    InviteCreated,
    InviteRequest,
    ProfileUpdate,
    UserAdminUpdate,
    UserRead,
)

router = APIRouter(tags=["users"])
_admin = require_roles(Role.ADMIN)


@router.get("/me", response_model=UserRead)
def get_me(user: User = Depends(current_user)) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/me", response_model=UserRead)
def update_me(
    body: ProfileUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> UserRead:
    return UserRead.model_validate(service.update_profile(session, user, body))


@router.post("/me/password", response_model=TokenPair)
def change_my_password(
    body: ChangePasswordRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> TokenPair:
    return service.change_password(session, user, body.current_password, body.new_password)


@router.get("/users", response_model=list[UserRead])
def list_users(_: User = Depends(_admin), session: Session = Depends(get_session)) -> list[UserRead]:
    return [UserRead.model_validate(u) for u in service.list_users(session)]


@router.post("/users/invites", response_model=InviteCreated, status_code=status.HTTP_201_CREATED)
def invite_user(
    body: InviteRequest,
    actor: User = Depends(_admin),
    session: Session = Depends(get_session),
) -> InviteCreated:
    return service.create_invite(session, actor, body)


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: uuid.UUID,
    body: UserAdminUpdate,
    actor: User = Depends(_admin),
    session: Session = Depends(get_session),
) -> UserRead:
    return UserRead.model_validate(service.update_user(session, actor, user_id, body))


@router.post("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_user_password(
    user_id: uuid.UUID,
    body: AdminPasswordReset,
    actor: User = Depends(_admin),
    session: Session = Depends(get_session),
) -> Response:
    service.reset_password(session, actor, user_id, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
