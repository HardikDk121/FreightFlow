import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.config import get_settings
from tests.conftest import bearer, register

app_engine = create_engine(get_settings().database_url)
SCOPE = "SELECT set_config('app.company_id', :c, true)"


def test_one_company_cannot_see_or_change_another(client):
    a = register(client, "A Transport", "a@a.example")
    b = register(client, "B Transport", "b@b.example")
    party = client.post("/parties", json={"name": "Secret Mills"}, headers=bearer(a)).json()

    assert client.get("/parties", headers=bearer(b)).json() == []
    assert client.get(f"/parties/{party['id']}", headers=bearer(b)).status_code == 404
    assert client.patch(f"/parties/{party['id']}", json={"name": "Stolen"}, headers=bearer(b)).status_code == 404
    assert [u["email"] for u in client.get("/users", headers=bearer(b)).json()] == ["b@b.example"]
    a_user = client.get("/me", headers=bearer(a)).json()["id"]
    assert client.patch(f"/users/{a_user}", json={"is_active": False}, headers=bearer(b)).status_code == 404
    # the same name is free in another company
    assert client.post("/parties", json={"name": "Secret Mills"}, headers=bearer(b)).status_code == 201


def test_database_enforces_isolation_without_the_api(client):
    a = register(client, "A Transport", "a@a.example")
    b = register(client, "B Transport", "b@b.example")
    client.post("/parties", json={"name": "Secret Mills"}, headers=bearer(a))
    a_id = client.get("/company", headers=bearer(a)).json()["id"]
    b_id = client.get("/company", headers=bearer(b)).json()["id"]

    with app_engine.connect() as conn:
        # no company set: every tenant table reads as empty
        for table in ("company", "app_user", "party", "audit_log", "auth_token"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table
        conn.rollback()

        conn.execute(text(SCOPE), {"c": b_id})
        assert conn.execute(text("SELECT count(*) FROM party")).scalar() == 0
        with pytest.raises(DBAPIError, match="row-level security"):
            conn.execute(
                text("INSERT INTO party (id, company_id, name) VALUES (gen_random_uuid(), :c, 'Planted')"),
                {"c": a_id},
            )
        conn.rollback()

        # the setting does not leak into the next transaction on the same connection
        assert conn.execute(text("SELECT count(*) FROM party")).scalar() == 0
        conn.rollback()


def test_app_role_cannot_delete_or_rewrite_history(client, admin):
    company_id = client.get("/company", headers=bearer(admin)).json()["id"]
    statements = (
        "DELETE FROM party",
        "DELETE FROM app_user",
        "DELETE FROM audit_log",
        "UPDATE audit_log SET action = 'forged'",
        "TRUNCATE audit_log",
    )
    with app_engine.connect() as conn:
        for statement in statements:
            conn.execute(text(SCOPE), {"c": company_id})
            with pytest.raises(DBAPIError, match="permission denied"):
                conn.execute(text(statement))
            conn.rollback()


def test_writes_are_audited(client, admin):
    client.post("/parties", json={"name": "Surat Textiles"}, headers=bearer(admin))
    company_id = client.get("/company", headers=bearer(admin)).json()["id"]
    with app_engine.connect() as conn:
        conn.execute(text(SCOPE), {"c": company_id})
        actions = conn.execute(text("SELECT action FROM audit_log ORDER BY id")).scalars().all()
    assert actions == ["company.register", "party.create"]
