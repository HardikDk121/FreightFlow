import uuid
from datetime import timedelta

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.auth.schemas import AcceptInviteRequest, RegisterRequest, TokenPair
from app.config import get_settings
from app.db import SessionLocal, set_tenant
from app.errors import AppError, conflict, unauthorized
from app.models import AuthToken, Branch, Company, Role, User, UserInvite
from app.security import (
    company_id_from_token,
    encode_access_token,
    hash_password,
    hash_token,
    new_opaque_token,
    utcnow,
    verify_password,
)

# Verified against when the login is unknown, so both failure paths cost one hash.
_DUMMY_HASH = hash_password("freightflow-timing-equaliser")
_BAD_LOGIN = "Email, phone or password is incorrect."


def issue_tokens(session: Session, user: User) -> TokenPair:
    settings = get_settings()
    token, digest = new_opaque_token(user.company_id)
    session.add(
        AuthToken(
            company_id=user.company_id,
            user_id=user.id,
            token_hash=digest,
            expires_at=utcnow() + timedelta(days=settings.refresh_ttl_days),
        )
    )
    session.flush()
    return TokenPair(
        access_token=encode_access_token(user.id, user.company_id),
        refresh_token=token,
        expires_in=settings.access_ttl_minutes * 60,
    )


def revoke_all_tokens(session: Session, user_id: uuid.UUID) -> None:
    session.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user_id, AuthToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def add_user(session: Session, user: User) -> None:
    """Insert a user; email and phone are unique across all companies."""
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:
        raise conflict("That email or phone is already registered.") from exc


def register(session: Session, data: RegisterRequest) -> TokenPair:
    company = Company(id=uuid.uuid4(), name=data.company_name)
    set_tenant(session, company.id)
    session.add(company)
    session.flush()
    session.add(Branch(company_id=company.id, name="Head office", is_head_office=True))
    session.flush()
    user = User(
        company_id=company.id,
        name=data.name,
        email=data.email,
        phone=data.phone,
        password_hash=hash_password(data.password),
        role=Role.ADMIN,
    )
    add_user(session, user)
    audit.record(
        session,
        company_id=company.id,
        actor_id=user.id,
        action="company.register",
        entity="company",
        entity_id=company.id,
    )
    return issue_tokens(session, user)


def login(session: Session, login_id: str, password: str) -> TokenPair:
    # The caller's company is unknown here, so this one lookup goes through a
    # SECURITY DEFINER function that returns ids only.
    row = session.execute(
        text("SELECT id, company_id FROM auth_user_by_login(:login)"), {"login": login_id.strip()}
    ).first()
    if row is None:
        verify_password(_DUMMY_HASH, password)
        raise unauthorized(_BAD_LOGIN)
    set_tenant(session, row.company_id)
    user = session.get(User, row.id)
    if user is None or not verify_password(user.password_hash, password) or not user.is_active:
        raise unauthorized(_BAD_LOGIN)
    return issue_tokens(session, user)


def refresh(session: Session, refresh_token: str) -> TokenPair:
    company_id = company_id_from_token(refresh_token)
    set_tenant(session, company_id)
    stored = session.scalar(
        select(AuthToken).where(AuthToken.token_hash == hash_token(refresh_token)).with_for_update()
    )
    if stored is None:
        raise unauthorized()
    if stored.revoked_at is not None:
        if stored.rotated:
            # An already-exchanged token was presented again: treat it as stolen and end
            # every session. This runs in its own transaction because the request's one
            # rolls back on the 401.
            with SessionLocal.begin() as side:
                set_tenant(side, company_id)
                revoke_all_tokens(side, stored.user_id)
        raise unauthorized()
    user = session.get(User, stored.user_id)
    if stored.expires_at <= utcnow() or user is None or not user.is_active:
        raise unauthorized()
    stored.revoked_at = utcnow()
    stored.rotated = True
    return issue_tokens(session, user)


def logout(session: Session, user: User, refresh_token: str) -> None:
    session.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user.id,
            AuthToken.token_hash == hash_token(refresh_token),
            AuthToken.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )


def accept_invite(session: Session, data: AcceptInviteRequest) -> TokenPair:
    invalid = AppError(400, "invalid_invite", "This invite is invalid, used or expired.")
    try:
        company_id = company_id_from_token(data.token)
    except AppError as exc:
        raise invalid from exc
    set_tenant(session, company_id)
    invite = session.scalar(
        select(UserInvite).where(UserInvite.token_hash == hash_token(data.token)).with_for_update()
    )
    if invite is None or invite.accepted_at is not None or invite.expires_at <= utcnow():
        raise invalid
    user = User(
        company_id=company_id,
        name=data.name,
        email=invite.email,
        phone=data.phone,
        password_hash=hash_password(data.password),
        role=invite.role,
        branch_id=invite.branch_id,
    )
    add_user(session, user)
    invite.accepted_at = utcnow()
    audit.record(
        session,
        company_id=company_id,
        actor_id=user.id,
        action="user.accept_invite",
        entity="app_user",
        entity_id=user.id,
        detail={"invited_by": str(invite.invited_by), "role": invite.role.value},
    )
    return issue_tokens(session, user)
