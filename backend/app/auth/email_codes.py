"""Proving a new sign-up owns its email address: a six-digit code, valid ten minutes, five tries,
one new code a minute at most."""

import datetime as dt
import hashlib
import hmac
import secrets

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.auth.recovery import throttle, throttle_key
from app.config import get_settings
from app.db import SessionLocal, after_commit
from app.errors import AppError, conflict
from app.models import EmailCode
from app.notify import Outbox
from app.security import utcnow

CODE_LIFETIME = dt.timedelta(minutes=10)
RESEND_AFTER = dt.timedelta(seconds=60)
MAX_ATTEMPTS = 5


def _hash(value: str) -> str:
    return hmac.new(get_settings().jwt_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _email_hash(email: str) -> str:
    return _hash("email:" + email.strip().lower())


def email_taken(session: Session, email: str) -> bool:
    return session.execute(text("SELECT 1 FROM auth_user_by_login(:login)"), {"login": email.strip()}).first() is not None


def send_code(session: Session, outbox: Outbox, email: str, ip: str) -> dict:
    """Email a code, unless the address already has an account or a code was sent under a minute ago."""
    if not get_settings().verify_signup_email:
        return {"required": False}
    if email_taken(session, email):
        raise conflict("An account with this email already exists. Sign in, or reset your password.")
    throttle(session, {throttle_key("signup-code", email): 5, throttle_key("signup-code-ip", ip): 20})
    last = session.scalar(select(EmailCode).where(EmailCode.email_hash == _email_hash(email)).order_by(EmailCode.created_at.desc()).limit(1))
    now = utcnow()
    if last is not None and now - last.created_at < RESEND_AFTER:
        wait = int((RESEND_AFTER - (now - last.created_at)).total_seconds()) + 1
        raise AppError(429, "resend_wait", f"A code was just sent. You can ask for another in {wait} seconds.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(EmailCode(email_hash=_email_hash(email), code_hash=_hash(f"{email.strip().lower()}:{code}"), expires_at=now + CODE_LIFETIME))
    session.flush()
    # Sent once the code is saved, so a code that failed to save is never emailed.
    after_commit(session, lambda: outbox.email(
        email, "Your FreightFlow sign-up code", f"Your code is {code}. It works for 10 minutes. If you did not sign up, ignore this email."))
    return {"required": True, "expires_in": int(CODE_LIFETIME.total_seconds()), "resend_after": int(RESEND_AFTER.total_seconds())}


def check_code(session: Session, email: str, code: str | None) -> None:
    """Accept the latest code for this address once. Wrong tries are counted even though the request fails."""
    if not get_settings().verify_signup_email:
        return
    if not code:
        raise AppError(422, "code_required", "Enter the 6-digit code we emailed you.")
    latest = session.scalar(select(EmailCode).where(EmailCode.email_hash == _email_hash(email)).order_by(EmailCode.created_at.desc()).limit(1))
    if latest is None or latest.used_at is not None or latest.expires_at < utcnow():
        raise AppError(422, "code_expired", "That code has expired. Ask for a new one.")
    if latest.attempts >= MAX_ATTEMPTS:
        raise AppError(429, "code_locked", "Too many wrong codes. Ask for a new one.")
    if not hmac.compare_digest(latest.code_hash, _hash(f"{email.strip().lower()}:{code}")):
        # Its own transaction, so the count survives this request's rollback.
        with SessionLocal.begin() as side:
            side.execute(update(EmailCode).where(EmailCode.id == latest.id).values(attempts=EmailCode.attempts + 1))
        left = MAX_ATTEMPTS - latest.attempts - 1
        raise AppError(422, "code_wrong", f"That code is not right. {left} {'try' if left == 1 else 'tries'} left." if left else "That code is not right. Ask for a new one.")
    latest.used_at = utcnow()
