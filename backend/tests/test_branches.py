"""Branch confidentiality and configurable permissions, enforced by the server and the database."""

import pytest
from sqlalchemy import text

from tests.conftest import bearer
from tests.test_dispatch import _lr, _truck


def _person(email):
    """A valid person's name from a test email: "ramesh@x" -> "Ramesh", "m@x" -> "M Staff"."""
    local = email.split("@")[0].title()
    return local if len(local) >= 2 else f"{local} Staff"


def _staff(client, admin, email, role, branch_id=None):
    invite = client.post("/users/invites", json={"email": email, "role": role, "branch_id": branch_id}, headers=bearer(admin))
    assert invite.status_code == 201, invite.text
    accepted = client.post("/auth/invites/accept", json={"token": invite.json()["token"], "name": _person(email), "password": "staff-password"})
    assert accepted.status_code == 201, accepted.text
    return accepted.json()


@pytest.fixture
def raipur(client, admin):
    branch = client.post("/branches", json={"name": "Raipur", "address": "Parking No. 6, Transport Nagar", "phone": "7049921516", "cities": ["Raipur", "Dhamtari"]}, headers=bearer(admin))
    assert branch.status_code == 201, branch.text
    return branch.json()


def test_branch_staff_see_only_their_branch(client, admin, raipur):
    h = bearer(admin)
    head = next(b for b in client.get("/branches", headers=h).json() if b["is_head_office"])
    to_raipur = _lr(client, h, to_city="Raipur", st_charges="100")
    to_surat = _lr(client, h, to_city="Surat", st_charges="100")
    assert (to_raipur["delivery_branch_id"], to_surat["delivery_branch_id"]) == (raipur["id"], None)
    assert to_raipur["branch_id"] == head["id"]

    raipur_clerk = bearer(_staff(client, admin, "r@shree.example", "register_clerk", raipur["id"]))
    seen = {lr["lr_number"] for lr in client.get("/lrs", headers=raipur_clerk).json()}
    assert seen == {to_raipur["lr_number"]}
    # not even by asking for it directly
    assert client.get(f"/lrs/{to_surat['id']}", headers=raipur_clerk).status_code == 404
    assert client.get(f"/lrs/{to_surat['id']}/account", headers=raipur_clerk).status_code == 404
    # the owner sees both branches
    assert {lr["lr_number"] for lr in client.get("/lrs", headers=h).json()} == {to_raipur["lr_number"], to_surat["lr_number"]}
    # a trip from the head office to Raipur is visible to Raipur, which unloads it
    trip = client.post("/trips", json={"truck_id": _truck(client, h), "stops": ["Raipur"], "lines": [{"lr_id": to_raipur["id"], "packages": to_raipur["packages"]}]}, headers=h).json()
    assert [t["id"] for t in client.get("/trips", headers=raipur_clerk).json()] == [trip["id"]]
    # receipts follow the LR's delivering branch
    receipt = client.post("/receipts", json={"lr_ids": [to_raipur["id"]]}, headers=raipur_clerk)
    assert receipt.status_code == 201
    head_clerk = bearer(_staff(client, admin, "h@shree.example", "register_clerk", head["id"]))
    assert client.get(f"/receipts/{receipt.json()['id']}", headers=head_clerk).status_code == 404


def test_a_city_belongs_to_one_branch(client, admin, raipur):
    clash = client.post("/branches", json={"name": "Dhamtari depot", "cities": ["dhamtari"]}, headers=bearer(admin))
    assert clash.status_code == 409 and "already delivered by Raipur" in clash.json()["error"]["message"]
    head = next(b for b in client.get("/branches", headers=bearer(admin)).json() if b["is_head_office"])
    closed = client.put(f"/branches/{head['id']}", json={"name": "Head office", "is_active": False}, headers=bearer(admin))
    assert closed.status_code == 409


def test_permissions_are_configurable_and_owner_level_ones_stay_with_the_owner(client, admin, raipur):
    h = bearer(admin)
    manager_tokens = _staff(client, admin, "m@shree.example", "manager", raipur["id"])
    manager = bearer(manager_tokens)
    me = client.get("/me", headers=manager).json()
    assert "lr.book" in me["permissions"] and "credit.manage" not in me["permissions"]
    assert client.put("/credit-terms", json={"payer_name": "X", "payment_terms": "at_delivery"}, headers=manager).status_code == 403
    # the owner grants one permission and takes another away
    changed = client.patch(f"/users/{me['id']}", json={"permissions_granted": ["credit.manage"], "permissions_revoked": ["lr.cancel"]}, headers=h).json()
    assert "credit.manage" in changed["permissions"] and "lr.cancel" not in changed["permissions"]
    assert client.put("/credit-terms", json={"payer_name": "X", "payment_terms": "at_delivery"}, headers=manager).status_code == 200
    lr = _lr(client, h, to_city="Raipur")
    assert client.post(f"/lrs/{lr['id']}/cancel", json={"reason": "test"}, headers=manager).status_code == 403
    # someone who manages users but is not the owner cannot hand out owner-level permissions
    client.patch(f"/users/{me['id']}", json={"permissions_granted": ["credit.manage", "users.manage"]}, headers=h)
    clerk = _staff(client, admin, "c@shree.example", "clerk", raipur["id"])
    clerk_id = client.get("/me", headers=bearer(clerk)).json()["id"]
    assert client.patch(f"/users/{clerk_id}", json={"permissions_granted": ["bank.reconcile"]}, headers=manager).status_code == 403
    assert client.patch(f"/users/{clerk_id}", json={"permissions_granted": ["gatepass.issue"]}, headers=manager).status_code == 200
    assert client.patch(f"/users/{clerk_id}", json={"permissions_granted": ["no.such"]}, headers=h).status_code == 422


def test_the_database_enforces_branch_scope(client, admin, raipur):
    """Even a query that forgets to filter cannot cross branches: the database refuses the rows."""
    from tests.test_tenancy import SCOPE, app_engine

    h = bearer(admin)
    _lr(client, h, to_city="Raipur")
    _lr(client, h, to_city="Surat")
    company_id = client.get("/company", headers=h).json()["id"]
    with app_engine.connect() as conn:
        conn.execute(text(SCOPE), {"c": company_id})
        conn.execute(text("SELECT set_config('app.branches', :b, true)"), {"b": raipur["id"]})
        assert conn.execute(text("SELECT count(*) FROM lr")).scalar() == 1
        conn.execute(text("SELECT set_config('app.branches', 'all', true)"))
        assert conn.execute(text("SELECT count(*) FROM lr")).scalar() == 2
        conn.execute(text("SELECT set_config('app.branches', '', true)"))
        assert conn.execute(text("SELECT count(*) FROM lr")).scalar() == 0
        conn.rollback()
