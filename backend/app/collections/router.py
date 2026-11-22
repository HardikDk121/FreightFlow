import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.clock import today
from app.collections import printing, service
from app.collections.schemas import (
    CollectionRead,
    CreditTermsRead,
    CreditTermsUpsert,
    Custody,
    DepositCreate,
    DepositRead,
    FailRequest,
    HandoverCreate,
    HandoverRead,
    Overview,
    ReceiptCreate,
    ReceiptRead,
    ReceiptVerification,
    ReleaseApprovalCreate,
    ShortageDecision,
    ShortageRead,
    VisitCreate,
)
from app.db import get_session
from app.deps import current_user
from app.errors import AppError
from app.idempotency import IdempotencyHeader, run_once
from app.models import Branch, Company, MoneyReceipt, User
from app.notify import Outbox, get_outbox
from app.permissions import P, require

router = APIRouter(tags=["collections"])

# Who may do what. The owner (admin) may do everything; the separations that matter
# (nobody receives their own handover) are enforced in the service, not by role alone.
_issuer = require(P.RECEIPT_ISSUE)
_collector = require(P.COLLECT)
_receiver = require(P.CASH_RECEIVE)
_owner = require(P.CREDIT_MANAGE)
_cancel = require(P.RECEIPT_CANCEL)
_viewer = require(P.MONEY_OVERVIEW)


@router.post("/receipts", response_model=ReceiptRead, status_code=status.HTTP_201_CREATED)
def issue_receipt(
    body: ReceiptCreate,
    idempotency_key: IdempotencyHeader = None,
    actor: User = Depends(_issuer),
    session: Session = Depends(get_session),
):
    """A numbered money receipt for one payer's LRs, for what they owe now."""
    return run_once(session, actor, idempotency_key, "POST /receipts", 201, lambda: service.issue_receipt(session, actor, body))


@router.get("/receipts", response_model=list[ReceiptRead])
def list_receipts(
    receipt_status: Annotated[Literal["open", "settled", "cancelled"] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[ReceiptRead]:
    return service.list_receipts(session, status=receipt_status, limit=limit, offset=offset)


@router.get("/receipts/verify/{token}", response_model=ReceiptVerification)
def verify_receipt(token: str, session: Session = Depends(get_session)) -> ReceiptVerification:
    """Public: what the company's record says about the receipt whose QR was scanned. No sign-in."""
    if not 16 <= len(token) <= 64:
        raise AppError(404, "not_found", "Money receipt not found.")
    return service.verify(session, token)


@router.get("/r/{token}", response_class=HTMLResponse, include_in_schema=False)
def verify_page(token: str, session: Session = Depends(get_session)) -> HTMLResponse:
    """The page the printed QR opens in a phone's browser."""
    try:
        found = service.verify(session, token) if 16 <= len(token) <= 64 else None
    except AppError:
        found = None
    return HTMLResponse(printing.verification_page(found), status_code=200 if found else 404)


@router.get("/receipts/{receipt_id}/pdf", response_class=Response)
def receipt_pdf(
    receipt_id: uuid.UUID, request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)
) -> Response:
    """The receipt to print and take to the customer, with its verification QR."""
    receipt = service.get_receipt(session, receipt_id)
    url = f"{str(request.base_url).rstrip('/')}/r/{service.verify_token(receipt.id)}"
    branch = session.get_one(Branch, session.get_one(MoneyReceipt, receipt.id).branch_id)
    pdf = printing.receipt_pdf(session.get_one(Company, user.company_id), branch, receipt, url)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{receipt.receipt_number}.pdf"'},
    )


@router.get("/receipts/{receipt_id}", response_model=ReceiptRead)
def get_receipt(receipt_id: uuid.UUID, _: User = Depends(current_user), session: Session = Depends(get_session)) -> ReceiptRead:
    return service.get_receipt(session, receipt_id)


@router.post("/receipts/{receipt_id}/cancel", response_model=ReceiptRead)
def cancel_receipt(
    receipt_id: uuid.UUID, body: FailRequest, actor: User = Depends(_cancel), session: Session = Depends(get_session)
) -> ReceiptRead:
    return service.cancel_receipt(session, actor, receipt_id, body.reason)


@router.post("/receipts/{receipt_id}/visits", response_model=ReceiptRead, status_code=status.HTTP_201_CREATED)
def record_visit(
    receipt_id: uuid.UUID,
    body: VisitCreate,
    idempotency_key: IdempotencyHeader = None,
    actor: User = Depends(_collector),
    session: Session = Depends(get_session),
    outbox: Outbox = Depends(get_outbox),
):
    """What happened at the customer: paid, part paid, come later (with the promised date), or refused.
    Send an Idempotency-Key so a retried request cannot record the same payment twice."""
    return run_once(
        session,
        actor,
        idempotency_key,
        f"POST /receipts/{receipt_id}/visits",
        201,
        lambda: service.record_visit(session, actor, outbox, receipt_id, body),
    )


@router.post("/collections/{collection_id}/fail", response_model=CollectionRead)
def fail_collection(
    collection_id: uuid.UUID, body: FailRequest, actor: User = Depends(_owner), session: Session = Depends(get_session)
) -> CollectionRead:
    """A cheque bounced or a UPI payment was reversed: the amount is owed again."""
    return service.fail_collection(session, actor, collection_id, body.reason)


@router.get("/custody/me", response_model=Custody)
def my_custody(user: User = Depends(current_user), session: Session = Depends(get_session)) -> Custody:
    """The cash and cheques I am holding, oldest first."""
    return service.custody(session, user)


@router.get("/custody", response_model=list[Custody])
def everyone_holding(_: User = Depends(_receiver), session: Session = Depends(get_session)) -> list[Custody]:
    """Everyone holding cash or cheques right now, for the person receiving handovers."""
    return service.holders(session)


@router.get("/custody/{user_id}", response_model=Custody)
def user_custody(user_id: uuid.UUID, _: User = Depends(_receiver), session: Session = Depends(get_session)) -> Custody:
    """What someone is holding, so the person receiving a handover knows what to expect."""
    user = session.get(User, user_id)
    if user is None:
        raise AppError(404, "not_found", "User not found.")
    return service.custody(session, user)


@router.post("/handovers", response_model=HandoverRead, status_code=status.HTTP_201_CREATED)
def receive_handover(
    body: HandoverCreate,
    idempotency_key: IdempotencyHeader = None,
    actor: User = Depends(_receiver),
    session: Session = Depends(get_session),
):
    """Receive everything a collector holds, entering the cash actually counted and the cheques actually seen."""
    return run_once(session, actor, idempotency_key, "POST /handovers", 201, lambda: service.handover(session, actor, body))


@router.get("/handovers", response_model=list[HandoverRead])
def list_handovers(
    limit: Annotated[int, Query(ge=1, le=200)] = 50, _: User = Depends(_viewer), session: Session = Depends(get_session)
) -> list[HandoverRead]:
    return service.list_handovers(session, limit)


@router.post("/handovers/{handover_id}/confirm", response_model=HandoverRead)
def confirm_handover(handover_id: uuid.UUID, actor: User = Depends(current_user), session: Session = Depends(get_session)) -> HandoverRead:
    """The collector agrees with the count."""
    return service.confirm_handover(session, actor, handover_id)


@router.post("/deposits", response_model=DepositRead, status_code=status.HTTP_201_CREATED)
def record_deposit(
    body: DepositCreate,
    idempotency_key: IdempotencyHeader = None,
    actor: User = Depends(_receiver),
    session: Session = Depends(get_session),
):
    """Bank everything held in cash, and the chosen cheques. Write the batch number on the slip."""
    return run_once(session, actor, idempotency_key, "POST /deposits", 201, lambda: service.deposit(session, actor, body))


@router.get("/deposits", response_model=list[DepositRead])
def list_deposits(
    limit: Annotated[int, Query(ge=1, le=200)] = 50, _: User = Depends(_viewer), session: Session = Depends(get_session)
) -> list[DepositRead]:
    return service.list_deposits(session, limit)


@router.get("/credit-terms", response_model=list[CreditTermsRead])
def list_credit(_: User = Depends(current_user), session: Session = Depends(get_session)) -> list[CreditTermsRead]:
    return service.list_credit(session)


@router.put("/credit-terms", response_model=CreditTermsRead)
def set_credit(body: CreditTermsUpsert, actor: User = Depends(_owner), session: Session = Depends(get_session)) -> CreditTermsRead:
    """The owner's standing approval to release a regular customer's to-pay goods before payment."""
    return service.upsert_credit(session, actor, body)


@router.post("/lrs/{lr_id}/release-approval", status_code=status.HTTP_204_NO_CONTENT)
def approve_release(
    lr_id: uuid.UUID, body: ReleaseApprovalCreate, actor: User = Depends(_owner), session: Session = Depends(get_session)
) -> None:
    """A one-off approval to release this LR's goods before it is paid."""
    service.approve_release(session, actor, lr_id, body.reason)


@router.get("/shortages", response_model=list[ShortageRead])
def list_shortages(
    shortage_status: Annotated[Literal["open", "recover_from_salary", "written_off", "found"] | None, Query(alias="status")] = None,
    _: User = Depends(_viewer),
    session: Session = Depends(get_session),
) -> list[ShortageRead]:
    return service.list_shortages(session, shortage_status)


@router.post("/shortages/{shortage_id}/decide", response_model=ShortageRead)
def decide_shortage(
    shortage_id: uuid.UUID, body: ShortageDecision, actor: User = Depends(_owner), session: Session = Depends(get_session)
) -> ShortageRead:
    return service.decide_shortage(session, actor, shortage_id, body)


@router.get("/collections/overview", response_model=Overview)
def overview(
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    _: User = Depends(_viewer),
    session: Session = Depends(get_session),
) -> Overview:
    """The money trail for a period (today by default), what is held where now, and what needs attention."""
    day = today()
    return service.overview(session, date_from or day, date_to or day)


@router.get("/collections/daily-summary")
def daily_summary(_: User = Depends(_viewer), session: Session = Depends(get_session)) -> dict[str, str]:
    """Today's summary as one message, for the owner's evening WhatsApp."""
    return {"text": service.daily_summary(session)}
