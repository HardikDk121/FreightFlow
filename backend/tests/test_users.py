from tests.conftest import add_staff, bearer


def test_only_admins_manage_users(client, admin):
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    assert client.get("/users", headers=bearer(clerk)).status_code == 403
    assert client.post("/users/invites", json={"email": "x@y.example", "role": "clerk"}, headers=bearer(clerk)).status_code == 403
    assert client.patch("/company", json={"name": "Hijacked"}, headers=bearer(clerk)).status_code == 403
    assert len(client.get("/users", headers=bearer(admin)).json()) == 2


def test_role_change_applies_on_the_next_request(client, admin):
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    clerk_id = client.get("/me", headers=bearer(clerk)).json()["id"]
    promoted = client.patch(f"/users/{clerk_id}", json={"role": "admin"}, headers=bearer(admin))
    assert promoted.status_code == 200
    assert client.get("/users", headers=bearer(clerk)).status_code == 200


def test_deactivation_locks_the_user_out_at_once(client, admin):
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    clerk_id = client.get("/me", headers=bearer(clerk)).json()["id"]
    assert client.patch(f"/users/{clerk_id}", json={"is_active": False}, headers=bearer(admin)).status_code == 200
    assert client.get("/me", headers=bearer(clerk)).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": clerk["refresh_token"]}).status_code == 401
    assert client.post("/auth/login", json={"login": "clerk@shree.example", "password": "staff-password"}).status_code == 401


def test_last_active_admin_cannot_be_removed(client, admin):
    admin_id = client.get("/me", headers=bearer(admin)).json()["id"]
    assert client.patch(f"/users/{admin_id}", json={"role": "clerk"}, headers=bearer(admin)).status_code == 409
    assert client.patch(f"/users/{admin_id}", json={"is_active": False}, headers=bearer(admin)).status_code == 409
    second = add_staff(client, admin, "boss@shree.example", "admin")
    assert client.patch(f"/users/{admin_id}", json={"role": "clerk"}, headers=bearer(second)).status_code == 200


def test_admin_resets_a_staff_password(client, admin):
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    clerk_id = client.get("/me", headers=bearer(clerk)).json()["id"]
    reset = client.post(f"/users/{clerk_id}/password", json={"new_password": "reset-by-admin"}, headers=bearer(admin))
    assert reset.status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": clerk["refresh_token"]}).status_code == 401
    assert client.post("/auth/login", json={"login": "clerk@shree.example", "password": "staff-password"}).status_code == 401
    assert client.post("/auth/login", json={"login": "clerk@shree.example", "password": "reset-by-admin"}).status_code == 200


def test_company_update(client, admin):
    ok = client.patch("/company", json={"gstin": "24abcde1234f1z6", "address": "Rajkot"}, headers=bearer(admin))
    assert ok.status_code == 200 and ok.json()["gstin"] == "24ABCDE1234F1Z6"
    assert client.patch("/company", json={"gstin": "123"}, headers=bearer(admin)).status_code == 422
    assert client.patch("/company", json={"name": None}, headers=bearer(admin)).status_code == 422
