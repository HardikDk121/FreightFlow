"""How each customer pays, when their money falls due, and whether they can be booked or released.

A customer with no terms set pays at delivery: that is the default for anyone the owner has not
decided to trust with credit.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import today
from app.errors import AppError
from app.models import CreditTerms, Lr, LrSettings, User
from app.permissions import P, has

# A to-be-billed LR for a customer with no terms is due this many days after booking.
DEFAULT_BILLING_DAYS = 30


def terms_for(session: Session, payer: str) -> CreditTerms | None:
    """The payer's active terms, or None (pays at delivery)."""
    return session.scalar(
        select(CreditTerms).where(func.lower(CreditTerms.payer_name) == payer.strip().lower(), CreditTerms.is_active)
    )


def due_on(lr: Lr, delivered_on: dt.date | None, terms: CreditTerms | None, credit_from: str) -> dt.date | None:
    """The day the LR's money is due, or None while it is not yet due (to be paid on a delivery that
    has not happened)."""
    if lr.freight_by == "Paid":
        return lr.lr_date
    if terms is None:
        if lr.freight_by == "ToPay":
            return delivered_on
        return lr.lr_date + dt.timedelta(days=DEFAULT_BILLING_DAYS)
    if terms.payment_terms in ("advance", "before_delivery"):
        return lr.lr_date
    if terms.payment_terms == "at_delivery":
        return delivered_on
    start = delivered_on if credit_from == "delivery" else lr.lr_date
    return start + dt.timedelta(days=terms.credit_days) if start is not None else None


def settings_of(session: Session, company_id) -> LrSettings:
    from app.lr.service import _settings  # the settings row is created on first use

    return _settings(session, company_id)


def booking_check(
    session: Session, actor: User, payer: str, freight_by: str, total: Decimal, override_reason: str | None
) -> str | None:
    """Refuse to book for a customer who has not paid what they already owe, unless the owner says why.
    Returns the override reason to save on the LR, if one was needed."""
    from app.payments.service import open_accounts  # what each LR owes, with its due date

    settings = settings_of(session, actor.company_id)
    if settings.credit_controls_from is None:
        return None
    terms = terms_for(session, payer)
    accounts = [a for a in open_accounts(session, payer) if a.lr_date >= settings.credit_controls_from]
    owing = sum((a.balance for a in accounts), Decimal(0))
    hold_after = today() - dt.timedelta(days=settings.overdue_hold_days)
    late = [a for a in accounts if a.due_on is not None and a.due_on < hold_after]
    problems: list[str] = []
    if late:
        oldest = min(a.due_on for a in late)
        problems.append(
            f"{payer} has Rs {sum((a.balance for a in late), Decimal(0)):,.2f} overdue since {oldest:%d-%m-%Y}"
        )
    if terms is not None and terms.payment_terms == "credit" and owing + total > terms.credit_limit:
        problems.append(
            f"{payer} would owe Rs {owing + total:,.2f}, over their credit limit of Rs {terms.credit_limit:,.2f}"
        )
    if terms is not None and terms.payment_terms == "advance" and freight_by != "Paid" and total > 0:
        problems.append(f"{payer} pays in advance, so book this LR as Paid and collect before dispatch")
    if not problems:
        return None
    if override_reason is None or not has(actor, P.CREDIT_OVERRIDE):
        raise AppError(
            409,
            "credit_hold",
            "; ".join(problems) + ". Only the owner can book it anyway, with a reason.",
        )
    return override_reason


def release_rule(terms: CreditTerms | None) -> str:
    """What must be true before a to-pay LR's goods leave: paid, or within credit."""
    if terms is None or terms.payment_terms in ("advance", "before_delivery", "at_delivery"):
        return "paid"
    return "credit"
