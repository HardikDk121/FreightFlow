"""Requests that need the owner: staff ask, with a reason; the owner (or someone given the
permission) approves or rejects. Both sides are recorded."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit, branches
from app.collections import service as collections
from app.db import get_session
from app.deps import current_user
from app.errors import conflict, not_found
from app.models import ApprovalRequest, Lr, User
from app.permissions import P, require
from app.security import utcnow

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]


class RequestBody(BaseModel):
    reason: Reason


class Decision(BaseModel):
    approve: bool
    note: Reason | None = None


class ApprovalRead(BaseModel):
    id: uuid.UUID
    kind: str
    lr_id: uuid.UUID
    lr_number: str
    payer: str
    amount_owed: str
    reason: str
    requested_by: str
    requested_at: dt.datetime
    status: str
    decided_by: str | None
    decision_note: str | None


def _read(session: Session, r: ApprovalRequest) -> ApprovalRead:
    from app.collections import balances

    lr = session.get_one(Lr, r.lr_id)
    names = dict(session.execute(select(User.id, User.name).where(User.id.in_({u for u in (r.requested_by, r.decided_by) if u}))).all())
    return ApprovalRead(
        id=r.id,
        kind=r.kind,
        lr_id=lr.id,
        lr_number=lr.lr_number,
        payer=balances.payer_of(lr),
        amount_owed=f"{balances.balances(session, [lr])[lr.id]:.2f}",
        reason=r.reason,
        requested_by=names.get(r.requested_by, ""),
        requested_at=r.requested_at,
        status=r.status,
        decided_by=names.get(r.decided_by),
        decision_note=r.decision_note,
    )


router = APIRouter(tags=["approvals"])


@router.post("/lrs/{lr_id}/release-request", response_model=ApprovalRead, status_code=status.HTTP_201_CREATED)
def request_release(
    lr_id: uuid.UUID, body: RequestBody, actor: User = Depends(require(P.APPROVALS_REQUEST)), session: Session = Depends(get_session)
) -> ApprovalRead:
    """Ask the owner to let an unpaid to-pay LR's goods go."""
    lr = session.get(Lr, lr_id)
    if lr is None:
        raise not_found("LR")
    request = ApprovalRequest(
        company_id=actor.company_id,
        branch_id=branches.lr_branch(lr),
        kind="release",
        lr_id=lr.id,
        reason=body.reason,
        requested_by=actor.id,
    )
    try:
        with session.begin_nested():
            session.add(request)
            session.flush()
    except IntegrityError as exc:
        raise conflict(f"A release request for LR {lr.lr_number} is already waiting.") from exc
    audit.record(
        session, company_id=actor.company_id, actor_id=actor.id, action="approval.request", entity="approval_request",
        entity_id=request.id, detail={"kind": "release", "lr_number": lr.lr_number, "reason": body.reason},
    )
    return _read(session, request)


@router.get("/approvals", response_model=list[ApprovalRead])
def list_approvals(
    approval_status: Annotated[Literal["pending", "approved", "rejected"] | None, Query(alias="status")] = "pending",
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[ApprovalRead]:
    """Requests in the branches this person can see; the owner sees all."""
    query = select(ApprovalRequest).order_by(ApprovalRequest.requested_at.desc()).limit(200)
    if approval_status is not None:
        query = query.where(ApprovalRequest.status == approval_status)
    return [_read(session, r) for r in session.scalars(query)]


@router.post("/approvals/{request_id}/decide", response_model=ApprovalRead)
def decide(
    request_id: uuid.UUID, body: Decision, actor: User = Depends(require(P.APPROVALS_DECIDE)), session: Session = Depends(get_session)
) -> ApprovalRead:
    request = session.get(ApprovalRequest, request_id, with_for_update=True)
    if request is None:
        raise not_found("Request")
    if request.status != "pending":
        raise conflict("This request has already been decided.")
    if request.requested_by == actor.id:
        raise conflict("Someone else must decide your own request.")
    request.status = "approved" if body.approve else "rejected"
    request.decided_by = actor.id
    request.decided_at = utcnow()
    request.decision_note = body.note
    session.flush()
    if body.approve:
        collections.approve_release(session, actor, request.lr_id, request.reason)
    audit.record(
        session, company_id=actor.company_id, actor_id=actor.id, action="approval.decide", entity="approval_request",
        entity_id=request.id, detail={"approve": body.approve, "note": body.note},
    )
    return _read(session, request)
