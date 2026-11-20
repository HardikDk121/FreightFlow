"""Collection tasks: the app, not a person's memory, decides who must chase which customer and when.

Every refresh (each time a task list or dashboard is opened, and by the daily job) the app looks at
what is due. Each customer owing money that is due or overdue gets one open task per branch,
assigned to the branch's collector with the fewest open tasks. A task closes itself when nothing
due is left. A task nobody has acted on by its date is escalated to the branch manager and owner.
"""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, StringConstraints, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, branches
from app.clock import today
from app.db import get_session
from app.deps import current_user
from app.errors import AppError, conflict, forbidden, not_found
from app.models import CollectionTask, Lr, Role, TaskAttempt, User
from app.permissions import P, has, require
from app.security import utcnow

# A task is escalated when its next action is this many days late.
ESCALATE_AFTER_DAYS = 1

Outcome = Literal["called", "visited", "not_available", "promised", "refused", "paid"]


class AttemptCreate(BaseModel):
    outcome: Outcome
    promised_on: dt.date | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)] | None = None

    @model_validator(mode="after")
    def _promise(self) -> "AttemptCreate":
        if (self.outcome == "promised") != (self.promised_on is not None):
            raise ValueError("A promise needs its date, and only a promise has one.")
        if self.outcome == "refused" and self.note is None:
            raise ValueError("Say why the customer refused.")
        return self


class AssignRequest(BaseModel):
    user_id: uuid.UUID


class AttemptRead(BaseModel):
    user: str
    outcome: str
    promised_on: dt.date | None
    note: str | None
    attempted_at: dt.datetime


class TaskRead(BaseModel):
    id: uuid.UUID
    payer_name: str
    branch_id: uuid.UUID
    assigned_to: uuid.UUID | None
    assigned_name: str | None
    status: str
    amount_due: Decimal
    oldest_due: dt.date
    days_overdue: int
    next_action_on: dt.date
    escalated: bool
    last_attempt_at: dt.datetime | None
    attempts: list[AttemptRead]


def _collectors(session: Session, branch_id: uuid.UUID) -> list[User]:
    """Who collects for this branch: its dedicated collectors; failing those, anyone there who may collect."""
    people = [
        u for u in session.scalars(select(User).where(User.is_active, User.branch_id == branch_id).order_by(User.name))
        if has(u, P.COLLECT) and u.role != Role.ADMIN
    ]
    dedicated = [u for u in people if u.role == Role.COLLECTOR]
    return dedicated or people


def refresh(session: Session, company_id: uuid.UUID) -> None:
    """Bring tasks in line with what is due now. Safe to run any number of times."""
    from app.payments.service import open_accounts

    day = today()
    due: dict[tuple[uuid.UUID, str], tuple[str, Decimal, dt.date]] = {}
    for account in open_accounts(session):
        if account.due_on is None or account.due_on > day:
            continue
        lr = session.get_one(Lr, account.lr_id)
        key = (branches.lr_branch(lr), account.payer.strip().lower())
        name, amount, oldest = due.get(key, (account.payer, Decimal(0), account.due_on))
        due[key] = (name, amount + account.balance, min(oldest, account.due_on))
    open_tasks = {
        (t.branch_id, t.payer_name.strip().lower()): t
        for t in session.scalars(select(CollectionTask).where(CollectionTask.status.in_(("open", "promised"))))
    }
    for key, task in open_tasks.items():
        if key not in due:
            task.status = "done"
            task.closed_at = utcnow()
    load = dict(
        session.execute(
            select(CollectionTask.assigned_to, func.count())
            .where(CollectionTask.status.in_(("open", "promised")))
            .group_by(CollectionTask.assigned_to)
        ).all()
    )
    for (branch_id, _), (name, amount, oldest) in due.items():
        task = open_tasks.get((branch_id, name.strip().lower()))
        if task is not None:
            task.amount_due, task.oldest_due = amount, oldest
            continue
        people = _collectors(session, branch_id)
        assignee = min(people, key=lambda u: load.get(u.id, 0)) if people else None
        if assignee is not None:
            load[assignee.id] = load.get(assignee.id, 0) + 1
        session.add(
            CollectionTask(
                company_id=company_id,
                branch_id=branch_id,
                payer_name=name,
                assigned_to=assignee.id if assignee else None,
                status="open",
                amount_due=amount,
                oldest_due=oldest,
                next_action_on=day,
                created_on=day,
            )
        )
    session.flush()


def _read(session: Session, task: CollectionTask) -> TaskRead:
    attempts = session.scalars(select(TaskAttempt).where(TaskAttempt.task_id == task.id).order_by(TaskAttempt.attempted_at.desc())).all()
    names = dict(session.execute(select(User.id, User.name).where(User.id.in_({a.user_id for a in attempts} | {task.assigned_to}))).all())
    day = today()
    return TaskRead(
        id=task.id,
        payer_name=task.payer_name,
        branch_id=task.branch_id,
        assigned_to=task.assigned_to,
        assigned_name=names.get(task.assigned_to),
        status=task.status,
        amount_due=task.amount_due,
        oldest_due=task.oldest_due,
        days_overdue=max((day - task.oldest_due).days, 0),
        next_action_on=task.next_action_on,
        escalated=task.status in ("open", "promised") and (day - task.next_action_on).days > ESCALATE_AFTER_DAYS,
        last_attempt_at=task.last_attempt_at,
        attempts=[
            AttemptRead(user=names.get(a.user_id, ""), outcome=a.outcome, promised_on=a.promised_on, note=a.note, attempted_at=a.attempted_at)
            for a in attempts
        ],
    )


def record_attempt(session: Session, actor: User, task: CollectionTask, outcome: str, promised_on: dt.date | None, note: str | None) -> None:
    """What happened when the customer was chased. The next action date follows from it."""
    day = today()
    if promised_on is not None and promised_on < day:
        raise AppError(422, "past_promise", "The promised date cannot be in the past.")
    session.add(TaskAttempt(company_id=actor.company_id, task_id=task.id, user_id=actor.id, outcome=outcome, promised_on=promised_on, note=note))
    task.last_attempt_at = utcnow()
    if outcome == "promised":
        task.status, task.next_action_on = "promised", promised_on
    else:
        task.status, task.next_action_on = "open", day + dt.timedelta(days=1)
    session.flush()


def note_visit(session: Session, actor: User, branch_id: uuid.UUID, payer: str, outcome: str, promised_on: dt.date | None, note: str | None) -> None:
    """A visit recorded on a money receipt counts as an attempt on the customer's task, if there is one."""
    task = session.scalar(
        select(CollectionTask).where(
            CollectionTask.branch_id == branch_id,
            func.lower(CollectionTask.payer_name) == payer.strip().lower(),
            CollectionTask.status.in_(("open", "promised")),
        )
    )
    if task is not None:
        mapped = {"paid": "paid", "part_paid": "paid", "come_later": "promised", "refused": "refused"}[outcome]
        record_attempt(session, actor, task, mapped, promised_on if mapped == "promised" else None, note)


router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskRead])
def list_tasks(
    scope: Annotated[Literal["mine", "all"], Query()] = "mine",
    task_status: Annotated[Literal["open", "done", "all"], Query(alias="status")] = "open",
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[TaskRead]:
    """My collection tasks, or (with the task-management permission) everyone's in my branches.
    Escalated and oldest first."""
    if scope == "all" and not has(user, P.TASKS_MANAGE):
        raise forbidden()
    refresh(session, user.company_id)
    query = select(CollectionTask)
    if task_status == "open":
        query = query.where(CollectionTask.status.in_(("open", "promised")))
    elif task_status == "done":
        query = query.where(CollectionTask.status == "done").order_by(CollectionTask.closed_at.desc()).limit(100)
    if scope == "mine":
        query = query.where(CollectionTask.assigned_to == user.id)
    tasks = [_read(session, t) for t in session.scalars(query)]
    return sorted(tasks, key=lambda t: (not t.escalated, t.next_action_on, t.oldest_due))


@router.post("/{task_id}/attempts", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def add_attempt(
    task_id: uuid.UUID, body: AttemptCreate, actor: User = Depends(require(P.COLLECT)), session: Session = Depends(get_session)
) -> TaskRead:
    task = session.get(CollectionTask, task_id, with_for_update=True)
    if task is None:
        raise not_found("Task")
    if task.status not in ("open", "promised"):
        raise conflict("This task is closed.")
    if task.assigned_to != actor.id and not has(actor, P.TASKS_MANAGE):
        raise forbidden()
    record_attempt(session, actor, task, body.outcome, body.promised_on, body.note)
    audit.record(
        session, company_id=actor.company_id, actor_id=actor.id, action="task.attempt", entity="collection_task",
        entity_id=task.id, detail=body.model_dump(mode="json"),
    )
    return _read(session, task)


@router.post("/{task_id}/assign", response_model=TaskRead)
def assign(
    task_id: uuid.UUID, body: AssignRequest, actor: User = Depends(require(P.TASKS_MANAGE)), session: Session = Depends(get_session)
) -> TaskRead:
    task = session.get(CollectionTask, task_id, with_for_update=True)
    if task is None:
        raise not_found("Task")
    person = session.get(User, body.user_id)
    if person is None or not person.is_active or not has(person, P.COLLECT):
        raise conflict("That person cannot collect payments.")
    if person.branch_id not in (None, task.branch_id):
        raise conflict("That person works in another branch.")
    was = task.assigned_to
    task.assigned_to = person.id
    session.flush()
    audit.record(
        session, company_id=actor.company_id, actor_id=actor.id, action="task.assign", entity="collection_task",
        entity_id=task.id, detail={"from": str(was) if was else None, "to": str(person.id)},
    )
    return _read(session, task)
