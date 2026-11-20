import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.auth import service as auth_service
from app.auth.schemas import TokenPair
from app.config import get_settings
from app.errors import AppError, conflict, forbidden, not_found
from app.models import Branch, Role, User, UserInvite
from app.permissions import SENSITIVE
from app.security import hash_password, new_opaque_token, utcnow, verify_password
from app.users.schemas import InviteCreated, InviteRequest, ProfileUpdate, UserAdminUpdate


def update_profile(session: Session, user: User, data: ProfileUpdate) -> User:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    try:
        session.flush()
    except IntegrityError as exc:
        raise conflict("That phone is already registered.") from exc
    return user


def change_password(session: Session, user: User, current: str, new: str) -> TokenPair:
    if not verify_password(user.password_hash, current):
        raise AppError(400, "wrong_password", "Current password is incorrect.")
    user.password_hash = hash_password(new)
    auth_service.revoke_all_tokens(session, user.id)
    audit.record(
        session,
        company_id=user.company_id,
        actor_id=user.id,
        action="user.change_password",
        entity="app_user",
        entity_id=user.id,
    )
    return auth_service.issue_tokens(session, user)


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.name)))


def _check_branch(session: Session, branch_id: uuid.UUID | None) -> None:
    if branch_id is not None and session.get(Branch, branch_id) is None:
        raise not_found("Branch")


def create_invite(session: Session, actor: User, data: InviteRequest) -> InviteCreated:
    if session.scalar(select(User.id).where(User.email == data.email)) is not None:
        raise conflict("A user with that email already exists in this company.")
    _check_branch(session, data.branch_id)
    if data.role == Role.ADMIN and actor.role != Role.ADMIN:
        raise forbidden()
    token, digest = new_opaque_token(actor.company_id)
    invite = UserInvite(
        company_id=actor.company_id,
        email=data.email,
        role=data.role,
        branch_id=data.branch_id,
        token_hash=digest,
        invited_by=actor.id,
        expires_at=utcnow() + timedelta(hours=get_settings().invite_ttl_hours),
    )
    session.add(invite)
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="user.invite",
        entity="user_invite",
        entity_id=invite.id,
        detail={"email": data.email, "role": data.role.value},
    )
    return InviteCreated(token=token, email=invite.email, role=invite.role, expires_at=invite.expires_at)


def _get_user(session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id, with_for_update=True)
    if user is None:
        raise not_found("User")
    return user


def update_user(session: Session, actor: User, user_id: uuid.UUID, data: UserAdminUpdate) -> User:
    target = _get_user(session, user_id)
    changes = data.model_dump(exclude_unset=True)
    # Owners, and owner-level permissions, are given and taken only by an owner.
    sensitive = set(changes.get("permissions_granted") or ()) & SENSITIVE
    if actor.role != Role.ADMIN and (target.role == Role.ADMIN or changes.get("role") == Role.ADMIN or sensitive):
        raise forbidden()
    if "branch_id" in changes:
        _check_branch(session, changes["branch_id"])
    for key in ("permissions_granted", "permissions_revoked"):
        if key in changes:
            changes[key] = sorted({p.value for p in changes[key]})
    stays_active_admin = changes.get("role", target.role) == Role.ADMIN and changes.get(
        "is_active", target.is_active
    )
    if target.role == Role.ADMIN and target.is_active and not stays_active_admin:
        other_admins = session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == Role.ADMIN, User.is_active, User.id != target.id)
        )
        if other_admins == 0:
            raise conflict("A company must keep at least one active admin.")
    for field, value in changes.items():
        setattr(target, field, value)
    if not target.is_active:
        auth_service.revoke_all_tokens(session, target.id)
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="user.update",
        entity="app_user",
        entity_id=target.id,
        detail=data.model_dump(exclude_unset=True, mode="json"),
    )
    return target


def reset_password(session: Session, actor: User, user_id: uuid.UUID, new_password: str) -> None:
    target = _get_user(session, user_id)
    target.password_hash = hash_password(new_password)
    auth_service.revoke_all_tokens(session, target.id)
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="user.reset_password",
        entity="app_user",
        entity_id=target.id,
    )
