import os

os.environ.setdefault("FF_DATABASE_URL", "postgresql+psycopg://freightflow_app:app@localhost/freightflow_test")
os.environ.setdefault(
    "FF_MIGRATION_DATABASE_URL", "postgresql+psycopg://freightflow_owner:owner@localhost/freightflow_test"
)
os.environ.setdefault("FF_JWT_SECRET", "test-secret-test-secret-test-secret-0000")

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text

from app.main import app
from app.notify import Outbox, get_outbox

owner_engine = create_engine(os.environ["FF_MIGRATION_DATABASE_URL"])
# The tests drop and rebuild the whole schema. Refuse to run against anything but a test database,
# so a mistyped environment can never wipe real data.
if not owner_engine.url.database.endswith("_test") or not make_url(os.environ["FF_DATABASE_URL"]).database.endswith("_test"):
    raise SystemExit(f"Refusing to run tests: database {owner_engine.url.database!r} is not a *_test database.")
TABLES = "trip_hire, rfq_quote, rfq_invite, rfq, vendor_payment, trip_deduction, trip_expense, contract_rate, contract, transit_time, vendor, saved_report, approval_request, reminder, task_attempt, collection_task, gate_pass_line, lr_charge, branch, idempotency_key, customer_notice, gate_pass, release_approval, credit_terms, shortage, collection_allocation, collection, bank_statement_line, bank_import, statement_format, bank_deposit, cash_handover, collection_visit, money_receipt_line, money_receipt, rate_rule, route, station, auth_throttle, password_reset, dispatch_line, challan, trip, lr, lr_settings, audit_log, truck, item_type, party, user_invite, auth_token, app_user, company"


@pytest.fixture(scope="session", autouse=True)
def schema():
    with owner_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
def clean():
    yield
    with owner_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY"))


class RecordingOutbox(Outbox):
    """Keeps messages instead of sending them."""

    def __init__(self):
        self.emails: list[tuple[str, str, str]] = []
        self.texts: list[tuple[str, str]] = []
        self.whatsapps: list[tuple[str, str]] = []
        self.attachments: list[tuple[str, bytes, str]] = []

    def email(self, to, subject, body, attachments=None):
        self.emails.append((to, subject, body))
        self.attachments.extend(attachments or [])

    def sms(self, to, body):
        self.texts.append((to, body))
        return True

    def whatsapp(self, to, body):
        self.whatsapps.append((to, body))
        return True


@pytest.fixture
def outbox():
    recording = RecordingOutbox()
    app.dependency_overrides[get_outbox] = lambda: recording
    yield recording
    app.dependency_overrides.clear()


@pytest.fixture
def client(outbox):
    return TestClient(app)


def bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def register(client, company="Shree Transport", email="admin@shree.example", phone=None) -> dict:
    body = {"company_name": company, "name": "Asha", "email": email, "password": "correct-horse"}
    if phone:
        body["phone"] = phone
    response = client.post("/auth/register", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def add_staff(client, admin_tokens, email, role) -> dict:
    invite = client.post("/users/invites", json={"email": email, "role": role}, headers=bearer(admin_tokens))
    assert invite.status_code == 201, invite.text
    accepted = client.post(
        "/auth/invites/accept",
        json={"token": invite.json()["token"], "name": "Ravi", "password": "staff-password"},
    )
    assert accepted.status_code == 201, accepted.text
    return accepted.json()


@pytest.fixture
def admin(client):
    return register(client)
