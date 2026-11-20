"""The operations dashboard. One computation for every role: row-level security limits each person
to their own branches, so the owner sees the whole business by branch and a branch manager sees
the same view for their branch alone. Collectors use their task list instead."""

import datetime as dt
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import tasks
from app.clock import start_of, today
from app.collections import service as collections
from app.db import get_session
from app.deps import current_user
from app.errors import forbidden
from app.models import (
    ApprovalRequest,
    Branch,
    Collection,
    CollectionTask,
    DispatchLine,
    GatePass,
    GatePassLine,
    Lr,
    Shortage,
    User,
)
from app.payments.service import open_accounts
from app.permissions import P, has, sees_all_branches

# An LR unloaded at its destination this many days ago with no signed gate pass is flagged.
DELIVERY_UPDATE_DAYS = 2


class BranchRow(BaseModel):
    branch_id: uuid.UUID
    name: str
    lrs_this_month: int
    awaiting_dispatch: int
    in_transit: int
    awaiting_delivery: int
    delivered_this_month: int
    receivable: Decimal
    overdue: Decimal
    cash_held: Decimal


class StaffRow(BaseModel):
    user_id: uuid.UUID
    name: str
    role: str
    open_tasks: int
    escalated_tasks: int
    collected_this_month: Decimal
    deliveries_this_month: int
    cash_held: Decimal


class LateDelivery(BaseModel):
    lr_number: str
    consignee: str
    arrived_on: dt.date
    days: int


class Operations(BaseModel):
    branches: list[BranchRow]
    lrs_this_month: int
    delivered_this_month: int
    delivered_unpaid: int
    partly_paid: int
    overdue_lrs: int
    receivable: Decimal
    overdue: Decimal
    collected_this_month: Decimal
    pending_approvals: int
    open_shortages: Decimal
    escalated_tasks: int
    # LRs unloaded at their destination with no signed gate pass: the "not delivered yet?" question.
    late_delivery_updates: list[LateDelivery]
    staff: list[StaffRow]
    alerts: list[str]


def build(session: Session, user: User) -> Operations:
    tasks.refresh(session, user.company_id)
    day = today()
    month = day.replace(day=1)
    month_start = start_of(month)
    accounts = open_accounts(session)
    by_lr = {a.lr_id: a for a in accounts}
    sent = dict(session.execute(select(DispatchLine.lr_id, func.sum(DispatchLine.packages)).group_by(DispatchLine.lr_id)).all())
    unloaded = dict(
        session.execute(
            select(DispatchLine.lr_id, func.max(DispatchLine.delivered_at))
            .where(DispatchLine.delivered_at.is_not(None))
            .group_by(DispatchLine.lr_id)
        ).all()
    )
    unloaded_all = {
        lr_id for lr_id, n in session.execute(
            select(DispatchLine.lr_id, func.count()).where(DispatchLine.delivered_at.is_(None)).group_by(DispatchLine.lr_id)
        ).all() if n
    }
    signed = dict(
        session.execute(
            select(GatePassLine.lr_id, GatePass.delivered_at)
            .join(GatePass, GatePass.id == GatePassLine.gate_pass_id)
            .where(GatePass.status == "delivered")
        ).all()
    )
    rows: dict[uuid.UUID, BranchRow] = {
        b.id: BranchRow(branch_id=b.id, name=b.name, lrs_this_month=0, awaiting_dispatch=0, in_transit=0, awaiting_delivery=0,
                        delivered_this_month=0, receivable=Decimal(0), overdue=Decimal(0), cash_held=Decimal(0))
        for b in session.scalars(select(Branch).where(Branch.is_active))
        if sees_all_branches(user) or b.id == user.branch_id
    }
    late: list[LateDelivery] = []
    recent = session.scalars(select(Lr).where(Lr.status == "confirmed", Lr.lr_date >= day - dt.timedelta(days=120)))
    for lr in recent:
        row = rows.get(lr.delivery_branch_id or lr.branch_id)
        if lr.lr_date >= month and lr.branch_id in rows:
            rows[lr.branch_id].lrs_this_month += 1
        if row is None:
            continue
        if lr.id in signed:
            if signed[lr.id] >= month_start:
                row.delivered_this_month += 1
        elif sent.get(lr.id, 0) < lr.packages:
            row.awaiting_dispatch += 1
        elif lr.id in unloaded_all:
            row.in_transit += 1
        else:
            row.awaiting_delivery += 1
            arrived = unloaded.get(lr.id)
            if arrived is not None and (day - arrived.date()).days >= DELIVERY_UPDATE_DAYS:
                late.append(LateDelivery(lr_number=lr.lr_number, consignee=lr.consignee_name, arrived_on=arrived.date(), days=(day - arrived.date()).days))
    for a in accounts:
        lr = session.get_one(Lr, a.lr_id)
        row = rows.get(lr.delivery_branch_id or lr.branch_id)
        if row is not None:
            row.receivable += a.balance
            if a.overdue:
                row.overdue += a.balance
    holders = {c.user_id: c for c in collections.holders(session)}
    people = session.scalars(select(User).where(User.is_active).order_by(User.name)).all()
    for person in people:
        held = holders.get(person.id)
        branch = person.branch_id
        if held is not None and branch in rows:
            rows[branch].cash_held += held.cash
    open_tasks = session.scalars(select(CollectionTask).where(CollectionTask.status.in_(("open", "promised")))).all()
    escalated = [t for t in open_tasks if (day - t.next_action_on).days > tasks.ESCALATE_AFTER_DAYS]
    collected_by = dict(
        session.execute(
            select(Collection.collected_by, func.sum(Collection.amount))
            .where(Collection.collected_at >= month_start, Collection.status != "failed")
            .group_by(Collection.collected_by)
        ).all()
    )
    pods_by = dict(
        session.execute(
            select(GatePass.pod_recorded_by, func.count())
            .where(GatePass.status == "delivered", GatePass.delivered_at >= month_start)
            .group_by(GatePass.pod_recorded_by)
        ).all()
    )
    staff = [
        StaffRow(
            user_id=p.id,
            name=p.name,
            role=p.role.value,
            open_tasks=sum(1 for t in open_tasks if t.assigned_to == p.id),
            escalated_tasks=sum(1 for t in escalated if t.assigned_to == p.id),
            collected_this_month=collected_by.get(p.id, Decimal(0)),
            deliveries_this_month=pods_by.get(p.id, 0),
            cash_held=holders[p.id].cash if p.id in holders else Decimal(0),
        )
        for p in people
        if p.id in collected_by or p.id in pods_by or p.id in holders or any(t.assigned_to == p.id for t in open_tasks)
    ]
    delivered_unpaid = sum(1 for lr_id in signed if lr_id in by_lr)
    alerts = [e.message for e in collections.overview(session, day, day).exceptions]
    unassigned = [t for t in open_tasks if t.assigned_to is None]
    if unassigned:
        alerts.insert(0, f"{len(unassigned)} collection task(s) have nobody to do them: add a collector to the branch.")
    late.sort(key=lambda x: -x.days)
    return Operations(
        branches=[r for r in rows.values() if r.lrs_this_month or r.receivable or r.awaiting_delivery or r.in_transit or r.awaiting_dispatch or r.cash_held]
        or list(rows.values()),
        lrs_this_month=sum(r.lrs_this_month for r in rows.values()),
        delivered_this_month=sum(r.delivered_this_month for r in rows.values()),
        delivered_unpaid=delivered_unpaid,
        partly_paid=sum(1 for a in accounts if a.paid > 0),
        overdue_lrs=sum(1 for a in accounts if a.overdue),
        receivable=sum((a.balance for a in accounts), Decimal(0)),
        overdue=sum((a.balance for a in accounts if a.overdue), Decimal(0)),
        collected_this_month=sum(collected_by.values(), Decimal(0)),
        pending_approvals=session.scalar(select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.status == "pending")),
        open_shortages=session.scalar(select(func.coalesce(func.sum(Shortage.amount), 0)).where(Shortage.status == "open")),
        escalated_tasks=len(escalated),
        late_delivery_updates=late[:20],
        staff=staff,
        alerts=alerts,
    )


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/operations", response_model=Operations)
def operations(user: User = Depends(current_user), session: Session = Depends(get_session)) -> Operations:
    """The owner's whole-business view, or a branch manager's branch view: the same figures, limited
    by the database to the branches the person may see."""
    if not (has(user, P.DASHBOARD_OWNER) or has(user, P.TASKS_MANAGE) or has(user, P.MONEY_OVERVIEW)):
        raise forbidden()
    return build(session, user)
