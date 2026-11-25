"""Password reset by emailed code, and login-email recovery by SMS.

Both answer the same way whether or not the account exists, and send their message after the
response has gone out, so neither the reply nor its timing reveals who has an account.
"""

import datetime as dt
import hashlib
import hmac
import secrets

from fastapi import BackgroundTasks
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app import audit
from app.auth.service import normalize_login, revoke_all_tokens
from app.config import get_settings
from app.db import SessionLocal, set_tenant
from app.errors import AppError
from app.models import AuthThrottle, PasswordReset, User
from app.notify import Outbox
from app.security import hash_password, utcnow

MAX_PER_ACCOUNT_PER_HOUR = 3
MAX_PER_IP_PER_HOUR = 10
MAX_CODE_ATTEMPTS = 5
_INVALID_CODE = AppError(400, "invalid_code", "That code is wrong or has expired. Ask for a new one.")


def throttle_key(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value.strip().lower()}".encode()).hexdigest()


def throttle(session: Session, limits: dict[str, int]) -> None:
    """Count this request against each key, and refuse it if any key is over its hourly limit.
    Keys are hashes, and the limit applies whether or not an account exists."""
    since = utcnow() - dt.timedelta(hours=1)
    for key_hash, limit in limits.items():
        used = session.scalar(
            select(func.count()).select_from(AuthThrottle).where(
                AuthThrottle.key_hash == key_hash, AuthThrottle.created_at > since
            )
        )
        if used >= limit:
            raise AppError(429, "too_many_requests", "Too many requests. Try again in an hour.")
    session.add_all(AuthThrottle(key_hash=key_hash) for key_hash in limits)
    session.flush()


def _find_user(session: Session, login: str) -> User | None:
    """The active user with this email or phone, with the transaction scoped to their company."""
    row = session.execute(text("SELECT id, company_id FROM auth_user_by_login(:login)"), {"login": normalize_login(login)}).first()
    if row is None:
        return None
    set_tenant(session, row.company_id)
    user = session.get(User, row.id)
    return user if user is not None and user.is_active else None


def _code_hash(user_id, code: str) -> str:
    secret = get_settings().jwt_secret.encode()
    return hmac.new(secret, f"{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


def request_password_reset(
    session: Session, login: str, ip: str, outbox: Outbox, background: BackgroundTasks
) -> None:
    throttle(session, {throttle_key("reset", login): MAX_PER_ACCOUNT_PER_HOUR, throttle_key("reset-ip", ip): MAX_PER_IP_PER_HOUR})
    user = _find_user(session, login)
    if user is None:
        return
    # Only the newest code works.
    session.execute(
        update(PasswordReset)
        .where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
        .values(used_at=utcnow())
    )
    code = f"{secrets.randbelow(1_000_000):06d}"
    minutes = get_settings().reset_code_ttl_minutes
    session.add(
        PasswordReset(
            company_id=user.company_id,
            user_id=user.id,
            code_hash=_code_hash(user.id, code),
            expires_at=utcnow() + dt.timedelta(minutes=minutes),
        )
    )
    background.add_task(
        outbox.email,
        user.email,
        "Your FreightFlow password reset code",
        f"Your code is {code}. It works once and expires in {minutes} minutes.\n\n"
        "If you did not ask for this, ignore this email. Your password has not changed.",
    )


def reset_password(session: Session, login: str, code: str, new_password: str) -> None:
    user = _find_user(session, login)
    if user is None:
        raise _INVALID_CODE
    reset = session.scalar(
        select(PasswordReset)
        .where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
        .order_by(PasswordReset.created_at.desc())
        .limit(1)
    )
    if reset is None or reset.expires_at <= utcnow() or reset.attempts >= MAX_CODE_ATTEMPTS:
        raise _INVALID_CODE
    if not hmac.compare_digest(reset.code_hash, _code_hash(user.id, code)):
        # Count the wrong try in its own transaction: this request's one rolls back on the error.
        with SessionLocal.begin() as side:
            set_tenant(side, user.company_id)
            side.execute(
                update(PasswordReset)
                .where(PasswordReset.id == reset.id)
                .values(attempts=PasswordReset.attempts + 1)
            )
        raise _INVALID_CODE
    user.password_hash = hash_password(new_password)
    reset.used_at = utcnow()
    revoke_all_tokens(session, user.id)
    audit.record(
        session,
        company_id=user.company_id,
        actor_id=user.id,
        action="user.reset_password_by_code",
        entity="app_user",
        entity_id=user.id,
    )


def recover_login_email(session: Session, phone: str, ip: str, outbox: Outbox, background: BackgroundTasks) -> None:
    """Text the login email to the phone on the account. The caller learns nothing; only the phone's owner does."""
    throttle(session, {throttle_key("recover", phone): MAX_PER_ACCOUNT_PER_HOUR, throttle_key("recover-ip", ip): MAX_PER_IP_PER_HOUR})
    user = _find_user(session, phone)
    if user is None or user.phone != phone:
        return
    background.add_task(outbox.sms, phone, f"Your FreightFlow login email is {user.email}")
