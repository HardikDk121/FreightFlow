"""What each person may do. A role gives a default set; the owner can add or take away single
permissions per person. Every endpoint checks a permission on the server, so hiding a button in
the app is never what protects an action.

The owner (role admin) holds every permission, always, and sees every branch."""

from collections.abc import Callable
from enum import StrEnum

from fastapi import Depends

from app.errors import forbidden
from app.models import Role, User


class P(StrEnum):
    LR_BOOK = "lr.book"
    LR_CANCEL = "lr.cancel"
    LR_SETTINGS = "lr.settings"
    MASTERDATA_EDIT = "masterdata.edit"
    DISPATCH = "dispatch.manage"
    TRIP_UNDO_DELIVERY = "dispatch.undo_delivery"
    GATE_PASS = "gatepass.issue"
    DELIVERY_CONFIRM = "delivery.confirm"
    DELIVERY_CORRECT = "delivery.correct"
    RECEIPT_ISSUE = "receipt.issue"
    RECEIPT_CANCEL = "receipt.cancel"
    COLLECT = "collect"
    CASH_ANY_AMOUNT = "collect.any_amount"
    CASH_RECEIVE = "cash.receive"
    MONEY_RECEIVABLES = "money.receivables"
    MONEY_OVERVIEW = "money.overview"
    BANK_RECONCILE = "bank.reconcile"
    CREDIT_MANAGE = "credit.manage"
    CREDIT_OVERRIDE = "credit.override"
    TASKS_MANAGE = "tasks.manage"
    APPROVALS_REQUEST = "approvals.request"
    APPROVALS_DECIDE = "approvals.decide"
    DASHBOARD_OWNER = "dashboard.owner"
    USERS_MANAGE = "users.manage"
    COMPANY_SETTINGS = "company.settings"
    BRANCHES_MANAGE = "branches.manage"
    ALL_BRANCHES = "branches.all"


ROLE_DEFAULTS: dict[Role, frozenset[P]] = {
    Role.ADMIN: frozenset(P),
    Role.MANAGER: frozenset(
        {
            P.LR_BOOK, P.LR_CANCEL, P.MASTERDATA_EDIT, P.DISPATCH, P.TRIP_UNDO_DELIVERY, P.GATE_PASS,
            P.DELIVERY_CONFIRM, P.RECEIPT_ISSUE, P.RECEIPT_CANCEL, P.COLLECT, P.MONEY_RECEIVABLES,
            P.MONEY_OVERVIEW, P.TASKS_MANAGE, P.APPROVALS_REQUEST,
        }
    ),
    Role.ACCOUNTANT: frozenset(
        {
            P.RECEIPT_ISSUE, P.RECEIPT_CANCEL, P.CASH_RECEIVE, P.MONEY_RECEIVABLES, P.MONEY_OVERVIEW,
            P.BANK_RECONCILE, P.TASKS_MANAGE, P.APPROVALS_REQUEST,
        }
    ),
    Role.REGISTER_CLERK: frozenset(
        {P.RECEIPT_ISSUE, P.CASH_RECEIVE, P.MONEY_RECEIVABLES, P.GATE_PASS, P.DELIVERY_CONFIRM, P.APPROVALS_REQUEST}
    ),
    Role.DISPATCHER: frozenset({P.DISPATCH, P.GATE_PASS, P.DELIVERY_CONFIRM}),
    Role.CLERK: frozenset({P.LR_BOOK}),
    Role.COLLECTOR: frozenset({P.COLLECT, P.DELIVERY_CONFIRM}),
}

# Permissions only the owner should normally hold. They can still be granted, deliberately.
SENSITIVE = frozenset(
    {
        P.CREDIT_MANAGE, P.CREDIT_OVERRIDE, P.DELIVERY_CORRECT, P.APPROVALS_DECIDE, P.USERS_MANAGE,
        P.BRANCHES_MANAGE, P.ALL_BRANCHES, P.BANK_RECONCILE, P.CASH_ANY_AMOUNT, P.DASHBOARD_OWNER,
    }
)


def effective(user: User) -> frozenset[P]:
    if user.role == Role.ADMIN:
        return frozenset(P)
    granted = {P(code) for code in user.permissions_granted if code in P._value2member_map_}
    revoked = {P(code) for code in user.permissions_revoked if code in P._value2member_map_}
    return (ROLE_DEFAULTS[user.role] | granted) - revoked


def has(user: User, permission: P) -> bool:
    return permission in effective(user)


def sees_all_branches(user: User) -> bool:
    return user.branch_id is None or has(user, P.ALL_BRANCHES)


def require(permission: P) -> Callable[[User], User]:
    """FastAPI dependency: the caller must hold this permission."""
    from app.deps import current_user

    def dependency(user: User = Depends(current_user)) -> User:
        if not has(user, permission):
            raise forbidden()
        return user

    return dependency
