import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user, require_roles
from app.errors import conflict
from app.lr import service
from app.lr.printing import render_lr_pdf
from app.lr.schemas import (
    LrCancel,
    LrDefaults,
    LrFields,
    LrPrintData,
    LrRead,
    LrSettingsRead,
    LrSettingsUpdate,
    LrSuggestions,
)
from app.models import Role, User

router = APIRouter(prefix="/lrs", tags=["lr"])
_booker = require_roles(Role.ADMIN, Role.MANAGER, Role.CLERK)
_canceller = require_roles(Role.ADMIN, Role.MANAGER)
_PDF = {200: {"content": {"application/pdf": {}}}}


def _pdf(data: LrPrintData) -> Response:
    return Response(
        content=render_lr_pdf(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="LR-{data.lr_number}.pdf"'},
    )


# Fixed paths come before /{lr_id}.


@router.get("/settings", response_model=LrSettingsRead)
def get_settings(user: User = Depends(current_user), session: Session = Depends(get_session)) -> LrSettingsRead:
    return LrSettingsRead.model_validate(service.get_settings(session, user))


@router.patch("/settings", response_model=LrSettingsRead)
def update_settings(
    body: LrSettingsUpdate,
    actor: User = Depends(require_roles(Role.ADMIN)),
    session: Session = Depends(get_session),
) -> LrSettingsRead:
    return LrSettingsRead.model_validate(service.update_settings(session, actor, body))


@router.get("/defaults", response_model=LrDefaults)
def get_defaults(user: User = Depends(_booker), session: Session = Depends(get_session)) -> LrDefaults:
    return service.defaults(session, user)


@router.get("/suggestions", response_model=LrSuggestions)
def get_suggestions(
    consignor_name: Annotated[str | None, Query(max_length=60)] = None,
    consignor_gstin: Annotated[str | None, Query(max_length=15)] = None,
    _: User = Depends(_booker),
    session: Session = Depends(get_session),
) -> LrSuggestions:
    return service.suggestions(session, consignor_name, consignor_gstin)


@router.post("/print-preview", response_class=Response, responses=_PDF)
def print_preview(body: LrPrintData, _: User = Depends(current_user)) -> Response:
    """The LR as a PDF, drawn from the values given. Nothing is saved."""
    return _pdf(body)


@router.post("", response_model=LrRead, status_code=status.HTTP_201_CREATED)
def create_lr(body: LrFields, actor: User = Depends(_booker), session: Session = Depends(get_session)) -> LrRead:
    """Save the LR with the next number in the series. A saved LR cannot be edited, only cancelled."""
    return LrRead.model_validate(service.create(session, actor, body))


@router.get("", response_model=list[LrRead])
def list_lrs(
    q: Annotated[str | None, Query(max_length=60)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[LrRead]:
    return [LrRead.model_validate(lr) for lr in service.search(session, q=q, limit=limit, offset=offset)]


@router.get("/{lr_id}", response_model=LrRead)
def get_lr(lr_id: uuid.UUID, _: User = Depends(current_user), session: Session = Depends(get_session)) -> LrRead:
    return LrRead.model_validate(service.get(session, lr_id))


@router.get("/{lr_id}/pdf", response_class=Response, responses=_PDF)
def get_lr_pdf(lr_id: uuid.UUID, _: User = Depends(current_user), session: Session = Depends(get_session)) -> Response:
    lr = service.get(session, lr_id)
    if lr.status == "cancelled":
        raise conflict("A cancelled LR cannot be printed.")
    return _pdf(LrPrintData.model_validate(lr))


@router.post("/{lr_id}/cancel", response_model=LrRead)
def cancel_lr(
    lr_id: uuid.UUID,
    body: LrCancel,
    actor: User = Depends(_canceller),
    session: Session = Depends(get_session),
) -> LrRead:
    return LrRead.model_validate(service.cancel(session, actor, lr_id, body.reason))
