import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user
from app.errors import conflict
from app.idempotency import IdempotencyHeader, run_once
from app.lr import service
from app.lr.printing import COPIES, render_lr_pdf
from app.lr.schemas import (
    EwayBillUpdate,
    LrCancel,
    LrCreate,
    LrDefaults,
    PartySuggestion,
    LrPreview,
    LrPrintData,
    LrRead,
    LrSettingsRead,
    LrSettingsUpdate,
    LrSuggestions,
)
from app.models import Company, User
from app.permissions import P, require
from app.reports.pdf import build_table_report

router = APIRouter(prefix="/lrs", tags=["lr"])
_booker = require(P.LR_BOOK)
_canceller = require(P.LR_CANCEL)
_PDF = {200: {"content": {"application/pdf": {}}}}


def _pdf(content: bytes, name: str) -> Response:
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}.pdf"'},
    )


def _company(session: Session, user: User) -> Company:
    return session.get_one(Company, user.company_id)


# Fixed paths come before /{lr_id}.


@router.get("/settings", response_model=LrSettingsRead)
def get_settings(user: User = Depends(current_user), session: Session = Depends(get_session)) -> LrSettingsRead:
    return LrSettingsRead.model_validate(service.get_settings(session, user))


@router.patch("/settings", response_model=LrSettingsRead)
def update_settings(
    body: LrSettingsUpdate,
    actor: User = Depends(require(P.LR_SETTINGS)),
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
def print_preview(
    body: LrPreview, user: User = Depends(current_user), session: Session = Depends(get_session)
) -> Response:
    """The LR as a one-page PDF, drawn from the values given. Nothing is saved."""
    pdf = render_lr_pdf(LrPrintData.model_validate(body), _company(session, user), [None])
    return _pdf(pdf, f"LR-{body.lr_number}")


@router.get("/parties", response_model=list[PartySuggestion])
def suggest_parties(
    q: Annotated[str, Query(min_length=2, max_length=60)],
    role: Literal["consignor", "consignee"],
    _: User = Depends(_booker),
    session: Session = Depends(get_session),
) -> list[PartySuggestion]:
    """Parties matching what has been typed, for the LR form's autocomplete."""
    return service.suggest_parties(session, q, role)


@router.get("/register.pdf", response_class=Response, responses=_PDF)
def lr_register(
    date_from: dt.date,
    date_to: dt.date,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Response:
    """Every LR booked between two dates, as a printable register."""
    if date_to < date_from or (date_to - date_from).days > 366:
        raise conflict("Choose a range of up to one year, with the end on or after the start.")
    lrs = service.booked_between(session, date_from, date_to)
    live = [lr for lr in lrs if lr.status == "confirmed"]
    pdf = build_table_report(
        company_name=_company(session, user).name.upper(),
        title="LR REGISTER",
        subtitle=f"{date_from.strftime('%d-%m-%Y')} to {date_to.strftime('%d-%m-%Y')}",
        columns=[("LR No", 24), ("Date", 19), ("Consignor", 38), ("Consignee", 38), ("To", 22), ("Pkgs", 12), ("Total", 27)],
        rows=[
            [
                lr.lr_number,
                lr.lr_date.strftime("%d-%m-%Y"),
                lr.consignor_name,
                lr.consignee_name,
                lr.to_city,
                str(lr.packages),
                "CANCELLED" if lr.status == "cancelled" else f"{lr.total:,.2f} {lr.freight_by}",
            ]
            for lr in lrs
        ],
        totals=[f"{len(live)} LRs", "", "", "", "", str(sum(lr.packages for lr in live)), f"{sum(lr.total for lr in live):,.2f}"],
    )
    return _pdf(pdf, f"LR-register-{date_from}-to-{date_to}")


@router.post("", response_model=LrRead, status_code=status.HTTP_201_CREATED)
def create_lr(
    body: LrCreate,
    idempotency_key: IdempotencyHeader = None,
    actor: User = Depends(_booker),
    session: Session = Depends(get_session),
):
    """Save the LR with the next number in the series. A saved LR cannot be edited, only cancelled.
    Send an Idempotency-Key so a retried save cannot book the same consignment twice."""
    return run_once(
        session, actor, idempotency_key, "POST /lrs", 201, lambda: LrRead.model_validate(service.create(session, actor, body))
    )


@router.get("", response_model=list[LrRead])
def list_lrs(
    q: Annotated[str | None, Query(max_length=60)] = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[LrRead]:
    """LRs, newest first. `date_from` and `date_to` filter on the booking date, both inclusive."""
    lrs = service.search(session, q=q, limit=limit, offset=offset, date_from=date_from, date_to=date_to)
    return [LrRead.model_validate(lr) for lr in lrs]


@router.get("/{lr_id}", response_model=LrRead)
def get_lr(lr_id: uuid.UUID, _: User = Depends(current_user), session: Session = Depends(get_session)) -> LrRead:
    return LrRead.model_validate(service.get(session, lr_id))


@router.get("/{lr_id}/pdf", response_class=Response, responses=_PDF)
def get_lr_pdf(
    lr_id: uuid.UUID,
    copy: Literal["all", "yellow", "white", "pink"] = "all",
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Response:
    """The saved LR. `copy=all` gives three pages, yellow, white and pink; otherwise the one copy named."""
    lr = service.get(session, lr_id)
    if lr.status == "cancelled":
        raise conflict("A cancelled LR cannot be printed.")
    copies = list(COPIES) if copy == "all" else [copy]
    pdf = render_lr_pdf(LrPrintData.model_validate(lr), _company(session, user), copies)
    return _pdf(pdf, f"LR-{lr.lr_number}" + ("" if copy == "all" else f"-{copy}"))


@router.post("/{lr_id}/cancel", response_model=LrRead)
def cancel_lr(
    lr_id: uuid.UUID,
    body: LrCancel,
    actor: User = Depends(_canceller),
    session: Session = Depends(get_session),
) -> LrRead:
    return LrRead.model_validate(service.cancel(session, actor, lr_id, body.reason))


@router.patch("/{lr_id}/eway-bill", response_model=LrRead)
def set_eway_bill(
    lr_id: uuid.UUID,
    body: EwayBillUpdate,
    actor: User = Depends(_booker),
    session: Session = Depends(get_session),
) -> LrRead:
    """Add the e-way bill number to a saved LR. The one detail that can be added after printing."""
    return LrRead.model_validate(service.set_eway_bill(session, actor, lr_id, body.eway_bill_no))
