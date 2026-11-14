import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import get_settings
from app.errors import unauthorized

_hasher = PasswordHasher()
_ALGORITHM = "HS256"


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    company_id: uuid.UUID


def encode_access_token(user_id: uuid.UUID, company_id: uuid.UUID) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "cid": str(company_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[_ALGORITHM],
            options={"require": ["sub", "cid", "exp"]},
        )
        return AccessClaims(uuid.UUID(payload["sub"]), uuid.UUID(payload["cid"]))
    except (jwt.PyJWTError, ValueError) as exc:
        raise unauthorized() from exc


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_opaque_token(company_id: uuid.UUID) -> tuple[str, str]:
    """Return (token, sha256 of token). Only the hash is stored.

    The company id is the token's prefix so the server can scope the lookup to that
    company before it knows who is calling. A forged prefix finds no matching hash.
    """
    token = f"{company_id.hex}.{secrets.token_urlsafe(32)}"
    return token, hash_token(token)


def company_id_from_token(token: str) -> uuid.UUID:
    prefix, _, secret = token.partition(".")
    try:
        if not secret:
            raise ValueError("missing secret")
        return uuid.UUID(hex=prefix)
    except ValueError as exc:
        raise unauthorized() from exc
