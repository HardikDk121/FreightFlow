"""Idempotency keys: a client that retries a request (a dropped connection, a double tap) sends the
same `Idempotency-Key` header, and gets the first answer instead of a second receipt or payment.

The key is stored in the same transaction as the work, so a request that fails leaves no key behind
and can be retried for real."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Header
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import IdempotencyKey, User

IdempotencyHeader = Annotated[str | None, Header(alias="Idempotency-Key", min_length=8, max_length=100)]


def run_once(
    session: Session,
    user: User,
    key: str | None,
    request: str,
    status_code: int,
    action: Callable[[], BaseModel],
) -> BaseModel | JSONResponse:
    """Run `action` once per key. `request` names what is being done ("POST /receipts") so a key
    cannot be reused for something else."""
    if key is None:
        return action()
    existing = session.get(IdempotencyKey, (user.company_id, key))
    if existing is not None:
        if existing.request != request or existing.user_id != user.id:
            raise AppError(422, "key_reused", "This request key was already used for something else.")
        if existing.response is None:
            raise AppError(409, "in_progress", "The same request is still being processed. Try again in a moment.")
        return JSONResponse(existing.response, status_code=existing.status_code)
    record = IdempotencyKey(company_id=user.company_id, key=key, user_id=user.id, request=request)
    try:
        with session.begin_nested():
            session.add(record)
            session.flush()
    except IntegrityError as exc:
        # Another request with this key got there first and has not finished.
        raise AppError(409, "in_progress", "The same request is still being processed. Try again in a moment.") from exc
    result = action()
    record.status_code = status_code
    record.response = jsonable_encoder(result)
    session.flush()
    return result
