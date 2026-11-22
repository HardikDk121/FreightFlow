import json
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user
from app.delivery import printing, service
from app.delivery.schemas import GatePassCreate, GatePassRead, ProofOfDelivery, VoidRequest
from app.errors import AppError
from app.idempotency import IdempotencyHeader, run_once
from app.models import Branch, Company, GatePass, User
from app.permissions import P, require

router = APIRouter(prefix="/gate-passes", tags=["delivery"])
_issuer = require(P.GATE_PASS)


@router.post("", response_model=GatePassRead, status_code=status.HTTP_201_CREATED)
def issue_gate_pass(
    body: GatePassCreate,
    idempotency_key: IdempotencyHeader = None,
    actor: User = Depends(_issuer),
    session: Session = Depends(get_session),
):
    """Release one consignee's goods. Each to-pay LR must be paid, within the customer's credit, or approved."""
    return run_once(session, actor, idempotency_key, "POST /gate-passes", 201, lambda: service.issue(session, actor, body))


@router.get("", response_model=list[GatePassRead])
def list_gate_passes(
    pass_status: Annotated[Literal["issued", "delivered", "void"] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[GatePassRead]:
    return service.list_passes(session, pass_status, limit, offset)


@router.get("/{gate_pass_id}", response_model=GatePassRead)
def get_gate_pass(gate_pass_id: uuid.UUID, _: User = Depends(current_user), session: Session = Depends(get_session)) -> GatePassRead:
    return service.get(session, gate_pass_id)


@router.post("/{gate_pass_id}/delivery", response_model=GatePassRead)
async def record_delivery(
    gate_pass_id: uuid.UUID,
    proof: str = Form(..., description="The proof of delivery as JSON (ProofOfDelivery)."),
    photo: UploadFile | None = File(None, description="Photo of the signed paper gate pass."),
    idempotency_key: IdempotencyHeader = None,
    actor: User = Depends(require(P.DELIVERY_CONFIRM)),
    session: Session = Depends(get_session),
):
    """The consignee signed: this is the proof of delivery. Due dates count from it."""
    try:
        data = ProofOfDelivery.model_validate(json.loads(proof))
    except (ValueError, ValidationError) as exc:
        raise AppError(422, "bad_proof", str(exc).splitlines()[0] if str(exc) else "The proof could not be read.") from exc
    image = await photo.read(service.MAX_PHOTO_BYTES + 1) if photo is not None else None
    return run_once(
        session,
        actor,
        idempotency_key,
        f"POST /gate-passes/{gate_pass_id}/delivery",
        200,
        lambda: service.record_delivery(session, actor, gate_pass_id, data, image),
    )


@router.post("/{gate_pass_id}/void", response_model=GatePassRead)
def void_gate_pass(
    gate_pass_id: uuid.UUID,
    body: VoidRequest,
    actor: User = Depends(require(P.DELIVERY_CORRECT)),
    session: Session = Depends(get_session),
) -> GatePassRead:
    """Cancel a gate pass or undo a delivery recorded in error. Needs the delivery-correction permission."""
    return service.void(session, actor, gate_pass_id, body.reason)


@router.get("/{gate_pass_id}/photo")
def gate_pass_photo(gate_pass_id: uuid.UUID, _: User = Depends(current_user), session: Session = Depends(get_session)) -> Response:
    data = service.photo(session, gate_pass_id)
    return Response(data, media_type="image/png" if data[:4] == b"\x89PNG" else "image/jpeg")


@router.get("/{gate_pass_id}/pdf")
def gate_pass_pdf(gate_pass_id: uuid.UUID, user: User = Depends(current_user), session: Session = Depends(get_session)) -> Response:
    read = service.get(session, gate_pass_id)
    branch = session.get_one(Branch, session.get_one(GatePass, gate_pass_id).branch_id)
    pdf = printing.gate_pass_pdf(session.get_one(Company, user.company_id), branch, read)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="GP-{read.gate_pass_number}.pdf"'})
