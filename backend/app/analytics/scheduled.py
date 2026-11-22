"""Sending scheduled reports. Each report runs with its author's permissions and branches, so a
branch manager's scheduled report never contains another branch's figures."""

import datetime as dt
import logging

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.analytics import custom, export, runner
from app.analytics.saved import SavedFilters
from app.db import set_branches
from app.models import Company, SavedReport, User
from app.notify import Outbox
from app.permissions import sees_all_branches

log = logging.getLogger("freightflow.reports")


def due(report: SavedReport, day: dt.date) -> bool:
    if not report.is_active or report.schedule == "none" or report.last_sent_on == day:
        return False
    return report.schedule == "daily" or (report.schedule == "weekly" and day.weekday() == 0) or (report.schedule == "monthly" and day.day == 1)


def send_due(session: Session, company_id, outbox: Outbox, day: dt.date) -> int:
    """Send today's scheduled reports. Returns how many were sent."""
    company = session.get_one(Company, company_id)
    sent = 0
    for report in [r for r in session.scalars(select(SavedReport)) if due(r, day)]:
        author = session.get(User, report.created_by)
        if author is None or not author.is_active or not runner.allowed(author, report.analysis):
            log.warning("Scheduled report %s skipped: its author can no longer see it.", report.id)
            continue
        if not sees_all_branches(author):
            set_branches(session, [author.branch_id])
        f = SavedFilters.model_validate(report.filters).resolve(day)
        if report.analysis == "custom":
            result = custom.run(session, f, custom.CustomReport.model_validate(report.custom))
        else:
            result = runner.run(session, report.analysis, f)
        workbook = export.to_xlsx(company.name, export.tables(report.analysis, result))
        name = f"{report.name} {f.date_from:%d-%m-%Y} to {f.date_to:%d-%m-%Y}"
        for to in report.recipients:
            outbox.email(
                to,
                f"{company.name}: {name}",
                f"The scheduled report \"{report.name}\" is attached.\n\n{f.describe()}.",
                attachments=[(f"{name}.xlsx", workbook, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")],
            )
        report.last_sent_on = day
        session.flush()
        if not sees_all_branches(author):
            session.execute(text("SELECT set_config('app.branches', 'all', true)"))
        sent += 1
    session.flush()
    return sent
