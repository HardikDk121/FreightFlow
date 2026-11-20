"""Gate passes and proof of delivery.

A gate pass releases one consignee's goods at the destination, as on the paper pad: their LRs,
the packages, how each was settled, and the local vehicle. It becomes proof of delivery when the
consignee signs for it on the phone, with the time, the place when the phone gives it, and a photo
of the signed paper. Only someone with the delivery-correction permission can undo that, with a
reason, and both stay in the record.
"""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, branches
from app.clock import today
from app.collections import balances, credit
from app.delivery.schemas import GatePassCreate, GatePassLineRead, GatePassRead, ProofOfDelivery
from app.errors import AppError, conflict, not_found
from app.lr import service as lr_service
from app.models import GatePass, GatePassLine, Lr, ReleaseApproval, User
from app.security import utcnow

# A proof sent later than this after delivery is refused: it should have reached the office long before.
MAX_OFFLINE_DELAY = dt.timedelta(days=7)
MAX_PHOTO_BYTES = 1_500_000
_PAYMENT_LABELS = {"paid": "Paid", "credit": "Credit", "approved": "Approved"}


def release_basis(session: Session, lr: Lr) -> str:
    """Why these goods may leave the godown, or an error saying why not."""
    if lr.freight_by != "ToPay":
        return "not_to_pay"
    if balances.balances(session, [lr])[lr.id] <= 0:
        return "paid"
    payer = balances.payer_of(lr)
    terms = credit.terms_for(session, payer)
    if credit.release_rule(terms) == "credit":
        open_lrs = balances.payer_open_lrs(session, payer)
        owing = sum((amount for _, amount in open_lrs), 0)
        late = [o for o, _ in open_lrs if o.id != lr.id and o.lr_date + dt.timedelta(days=terms.credit_days) < today()]
        if owing <= terms.credit_limit and not late:
            return "credit"
    if session.scalar(select(ReleaseApproval.id).where(ReleaseApproval.lr_id == lr.id)) is not None:
        return "approved"
    if terms is not None and terms.payment_terms == "credit":
        raise conflict(
            f"{payer} is over their credit (limit Rs {terms.credit_limit:,.0f}, {terms.credit_days} days). "
            "Collect payment or ask the owner to approve this release."
        )
    if terms is not None and terms.payment_terms in ("advance", "before_delivery"):
        raise conflict(f"{payer} pays before delivery. Collect payment or ask the owner to approve this release.")
    raise conflict(f"LR {lr.lr_number} is to-pay and unpaid. Collect payment or ask the owner to approve the release.")


def _read(session: Session, gp: GatePass) -> GatePassRead:
    rows = session.execute(
        select(GatePassLine, Lr).join(Lr, Lr.id == GatePassLine.lr_id).where(GatePassLine.gate_pass_id == gp.id).order_by(Lr.lr_number)
    ).all()
    names = dict(
        session.execute(select(User.id, User.name).where(User.id.in_({u for u in (gp.issued_by, gp.pod_recorded_by) if u}))).all()
    )
    return GatePassRead(
        id=gp.id,
        gate_pass_number=gp.gate_pass_number,
        consignee_name=gp.consignee_name,
        auto_no=gp.auto_no,
        driver_name=gp.driver_name,
        status=gp.status,
        issued_by=names.get(gp.issued_by, ""),
        issued_at=gp.issued_at,
        lines=[
            GatePassLineRead(
                lr_id=lr.id,
                lr_number=lr.lr_number,
                packages=line.packages,
                basis=line.basis,
                payment=_PAYMENT_LABELS.get(line.basis, lr.freight_by),
            )
            for line, lr in rows
        ],
        delivered_at=gp.delivered_at,
        receiver_name=gp.receiver_name,
        receiver_phone=gp.receiver_phone,
        latitude=gp.latitude,
        longitude=gp.longitude,
        has_photo=gp.photo is not None,
        pod_recorded_by=names.get(gp.pod_recorded_by),
        void_reason=gp.void_reason,
    )


def issue(session: Session, actor: User, data: GatePassCreate) -> GatePassRead:
    lrs = session.scalars(select(Lr).where(Lr.id.in_(data.lr_ids)).order_by(Lr.id).with_for_update()).all()
    if len(lrs) != len(data.lr_ids):
        raise not_found("LR")
    if len({lr.consignee_name.strip().lower() for lr in lrs}) > 1:
        raise conflict("A gate pass is for one consignee. These LRs are for different consignees.")
    bases = {}
    for lr in lrs:
        if lr.status != "confirmed":
            raise conflict(f"LR {lr.lr_number} is cancelled.")
        open_pass = session.scalar(
            select(GatePass.gate_pass_number)
            .join(GatePassLine, GatePassLine.gate_pass_id == GatePass.id)
            .where(GatePassLine.lr_id == lr.id, GatePass.status != "void")
        )
        if open_pass is not None:
            raise conflict(f"LR {lr.lr_number} is already on gate pass {open_pass}.")
        bases[lr.id] = release_basis(session, lr)
    gp = GatePass(
        company_id=actor.company_id,
        branch_id=branches.lr_branch(lrs[0]),
        gate_pass_number=lr_service.take_document_number(session, actor.company_id, "gate_pass"),
        consignee_name=lrs[0].consignee_name,
        auto_no=data.auto_no,
        driver_name=data.driver_name,
        status="issued",
        issued_by=actor.id,
    )
    session.add(gp)
    session.flush()
    session.add_all(
        GatePassLine(company_id=actor.company_id, gate_pass_id=gp.id, lr_id=lr.id, packages=lr.packages, basis=bases[lr.id])
        for lr in lrs
    )
    session.flush()
    session.refresh(gp)
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="gate_pass.issue",
        entity="gate_pass",
        entity_id=gp.id,
        detail={"number": gp.gate_pass_number, "lrs": {lr.lr_number: bases[lr.id] for lr in lrs}},
    )
    return _read(session, gp)


def _gate_pass(session: Session, gate_pass_id: uuid.UUID, *, lock: bool = False) -> GatePass:
    gp = session.get(GatePass, gate_pass_id, with_for_update=lock)
    if gp is None:
        raise not_found("Gate pass")
    return gp


def get(session: Session, gate_pass_id: uuid.UUID) -> GatePassRead:
    return _read(session, _gate_pass(session, gate_pass_id))


def list_passes(session: Session, status: str | None, limit: int, offset: int) -> list[GatePassRead]:
    query = select(GatePass).order_by(GatePass.issued_at.desc()).limit(limit).offset(offset)
    if status is not None:
        query = query.where(GatePass.status == status)
    return [_read(session, gp) for gp in session.scalars(query)]


def _photo_ok(photo: bytes) -> bool:
    return photo[:3] == b"\xff\xd8\xff" or photo[:8] == b"\x89PNG\r\n\x1a\n"


def record_delivery(
    session: Session, actor: User, gate_pass_id: uuid.UUID, data: ProofOfDelivery, photo: bytes | None
) -> GatePassRead:
    gp = _gate_pass(session, gate_pass_id, lock=True)
    if gp.status == "delivered":
        raise conflict(f"Gate pass {gp.gate_pass_number} is already delivered.")
    if gp.status == "void":
        raise conflict(f"Gate pass {gp.gate_pass_number} was cancelled.")
    now = utcnow()
    if data.delivered_at > now + dt.timedelta(minutes=10):
        raise AppError(422, "future_time", "The delivery time is in the future. Check the phone's clock.")
    if data.delivered_at < gp.issued_at - dt.timedelta(minutes=10):
        raise AppError(422, "before_issue", "The delivery time is before the gate pass was issued. Check the phone's clock.")
    if now - data.delivered_at > MAX_OFFLINE_DELAY:
        raise AppError(422, "too_late", "This delivery was recorded over a week ago. Ask the owner to record it.")
    if photo is not None:
        if len(photo) > MAX_PHOTO_BYTES:
            raise AppError(413, "photo_too_large", "The photo is too large. Take it again at a lower size.")
        if not _photo_ok(photo):
            raise AppError(422, "not_a_photo", "The photo must be a JPEG or PNG image.")
    gp.status = "delivered"
    gp.delivered_at = data.delivered_at
    gp.pod_received_at = now
    gp.receiver_name = data.receiver_name
    gp.receiver_phone = data.receiver_phone
    gp.signature = [[list(point) for point in stroke] for stroke in data.signature]
    gp.photo = photo
    gp.latitude, gp.longitude, gp.accuracy_m = data.latitude, data.longitude, data.accuracy_m
    gp.pod_recorded_by = actor.id
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="gate_pass.deliver",
        entity="gate_pass",
        entity_id=gp.id,
        detail={
            "number": gp.gate_pass_number,
            "delivered_at": data.delivered_at.isoformat(),
            "receiver": data.receiver_name,
            "photo": photo is not None,
            "located": data.latitude is not None,
        },
    )
    return _read(session, gp)


def void(session: Session, actor: User, gate_pass_id: uuid.UUID, reason: str) -> GatePassRead:
    """Cancel a gate pass, or undo a delivery recorded by mistake. The proof stays in the record."""
    gp = _gate_pass(session, gate_pass_id, lock=True)
    if gp.status == "void":
        raise conflict("This gate pass is already cancelled.")
    was = gp.status
    gp.status = "void"
    gp.void_reason = reason
    gp.voided_by = actor.id
    gp.voided_at = utcnow()
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="gate_pass.void",
        entity="gate_pass",
        entity_id=gp.id,
        detail={"number": gp.gate_pass_number, "was": was, "reason": reason},
    )
    return _read(session, gp)


def photo(session: Session, gate_pass_id: uuid.UUID) -> bytes:
    gp = _gate_pass(session, gate_pass_id)
    if gp.photo is None:
        raise not_found("Photo")
    return gp.photo


def delivered_on(session: Session, lr_id: uuid.UUID) -> dt.date | None:
    """The day the consignee signed for this LR, if they have."""
    when = session.scalar(
        select(GatePass.delivered_at)
        .join(GatePassLine, GatePassLine.gate_pass_id == GatePass.id)
        .where(GatePassLine.lr_id == lr_id, GatePass.status == "delivered")
    )
    return when.date() if when else None
