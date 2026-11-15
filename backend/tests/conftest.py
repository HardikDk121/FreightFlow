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
from sqlalchemy import create_engine, text

from app.main import app

owner_engine = create_engine(os.environ["FF_MIGRATION_DATABASE_URL"])
TABLES = "dispatch_line, trip, lr, lr_settings, audit_log, truck, item_type, party, user_invite, auth_token, app_user, company"


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


@pytest.fixture
def client():
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
