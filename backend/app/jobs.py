"""The daily job: create and close collection tasks, send payment reminders and scheduled reports, for every company.

Run it once a morning, for example from cron on the server:
    docker compose run --rm api python -m app.jobs daily
Each company runs in its own transaction, so one failing does not stop the others."""

import logging
import sys

from sqlalchemy import text

from app import reminders, tasks
from app.analytics import scheduled
from app.clock import today
from app.db import SessionLocal, set_tenant
from app.notify import Outbox, get_outbox

log = logging.getLogger("freightflow.jobs")


def daily(outbox: Outbox | None = None) -> dict[str, int]:
    outbox = outbox or get_outbox()
    with SessionLocal() as session:
        companies = [row[0] for row in session.execute(text("SELECT * FROM all_company_ids()"))]
    sent = failed = reports = 0
    for company_id in companies:
        try:
            with SessionLocal() as session, session.begin():
                set_tenant(session, company_id)
                tasks.refresh(session, company_id)
                sent += reminders.run(session, outbox, company_id)
                reports += scheduled.send_due(session, company_id, outbox, today())
        except Exception:
            failed += 1
            log.exception("Daily job failed for company %s", company_id)
    return {"companies": len(companies), "reminders": sent, "reports": reports, "failed": failed}


if __name__ == "__main__":
    if sys.argv[1:] != ["daily"]:
        sys.exit("usage: python -m app.jobs daily")
    logging.basicConfig(level=logging.INFO)
    result = daily()
    log.info("Daily job: %s", result)
    sys.exit(1 if result["failed"] else 0)
