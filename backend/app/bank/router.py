import json
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from sqlalchemy.orm import Session

from app.bank import service
from app.bank.service import ImportResult, Layout, LineRead, Preview
from app.collections.schemas import CollectionRead
from app.db import get_session
from app.errors import AppError
from app.idempotency import IdempotencyHeader, run_once
from app.models import User
from app.notify import Outbox, get_outbox
from app.permissions import P, require

router = APIRouter(prefix="/bank", tags=["bank"])
_owner = require(P.BANK_RECONCILE)

# Bank downloads for a month are well under this.
_MAX_FILE = 5 * 1024 * 1024


async def _read(file: UploadFile) -> bytes:
    data = await file.read(_MAX_FILE + 1)
    if len(data) > _MAX_FILE:
        raise AppError(413, "too_large", "The statement file is over 5 MB. Download a shorter period.")
    return data


class MatchRequest(BaseModel):
    collection_id: uuid.UUID | None = None
    deposit_id: uuid.UUID | None = None


class AllocateRequest(BaseModel):
    payer_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    # Leave out to settle the payer's oldest LRs first.
    lr_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)


class IgnoreRequest(BaseModel):
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]


@router.post("/statements/preview", response_model=Preview)
async def preview_statement(
    file: UploadFile = File(...), _: User = Depends(_owner), session: Session = Depends(get_session)
) -> Preview:
    """Read the file and show the layout found and the first lines. Saves nothing."""
    return service.preview(session, await _read(file), file.filename or "statement.csv")


@router.post("/statements", response_model=ImportResult)
async def import_statement(
    file: UploadFile = File(...),
    layout: str = Form(..., description="The layout from the preview, as JSON, corrected if needed."),
    actor: User = Depends(_owner),
    session: Session = Depends(get_session),
) -> ImportResult:
    """Save the statement's new lines (lines already imported are skipped) and match what can be matched."""
    try:
        chosen = Layout.model_validate(json.loads(layout))
    except (ValueError, ValidationError) as exc:
        raise AppError(422, "bad_layout", "The column layout could not be read.") from exc
    return service.import_statement(session, actor, await _read(file), file.filename or "statement.csv", chosen)


@router.get("/lines", response_model=list[LineRead])
def list_lines(
    line_status: Annotated[Literal["unmatched", "matched", "ignored"] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    _: User = Depends(_owner),
    session: Session = Depends(get_session),
) -> list[LineRead]:
    return service.list_lines(session, line_status, limit, offset)


@router.post("/lines/{line_id}/match", response_model=LineRead)
def match_line(line_id: uuid.UUID, body: MatchRequest, actor: User = Depends(_owner), session: Session = Depends(get_session)) -> LineRead:
    return service.match(session, actor, line_id, body.collection_id, body.deposit_id)


@router.post("/lines/{line_id}/allocate", response_model=CollectionRead)
def allocate_line(
    line_id: uuid.UUID,
    body: AllocateRequest,
    idempotency_key: IdempotencyHeader = None,
    actor: User = Depends(_owner),
    session: Session = Depends(get_session),
    outbox: Outbox = Depends(get_outbox),
):
    """A customer paid straight into the bank: set it against their LRs."""
    return run_once(
        session,
        actor,
        idempotency_key,
        f"POST /bank/lines/{line_id}/allocate",
        200,
        lambda: service.allocate(session, actor, outbox, line_id, body.payer_name, body.lr_ids),
    )


@router.post("/lines/{line_id}/ignore", response_model=LineRead)
def ignore_line(line_id: uuid.UUID, body: IgnoreRequest, actor: User = Depends(_owner), session: Session = Depends(get_session)) -> LineRead:
    """Not a customer payment, such as interest or the owner's own transfer."""
    return service.ignore(session, actor, line_id, body.note)
