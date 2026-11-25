from tests.conftest import add_staff, bearer, register


def test_register_login_and_profile(client):
    register(client, phone="+919876543210")
    for login in ("admin@shree.example", "ADMIN@Shree.Example", "+919876543210"):
        response = client.post("/auth/login", json={"login": login, "password": "correct-horse"})
        assert response.status_code == 200, login
    me = client.get("/me", headers=bearer(response.json())).json()
    assert me["role"] == "admin" and me["email"] == "admin@shree.example"
    assert client.get("/company", headers=bearer(response.json())).json()["name"] == "Shree Transport"


def test_bad_credentials_give_the_same_error(client, admin):
    wrong = client.post("/auth/login", json={"login": "admin@shree.example", "password": "nope"})
    unknown = client.post("/auth/login", json={"login": "ghost@x.example", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_duplicate_email_is_rejected_across_companies(client, admin):
    again = client.post(
        "/auth/register",
        json={"company_name": "Other", "name": "Bina", "email": "Admin@shree.example", "password": "correct-horse"},
    )
    assert again.status_code == 409
    # the failed registration left no company behind
    login = client.post("/auth/login", json={"login": "admin@shree.example", "password": "correct-horse"})
    assert client.get("/company", headers=bearer(login.json())).json()["name"] == "Shree Transport"


def test_requests_without_a_valid_token_are_rejected(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_refresh_rotates_and_reuse_ends_every_session(client, admin):
    second = client.post("/auth/refresh", json={"refresh_token": admin["refresh_token"]})
    assert second.status_code == 200
    assert second.json()["refresh_token"] != admin["refresh_token"]
    # the rotated token is presented again: rejected, and the newer token dies with it
    assert client.post("/auth/refresh", json={"refresh_token": admin["refresh_token"]}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": second.json()["refresh_token"]}).status_code == 401


def test_refresh_rejects_garbage(client):
    for token in ("", "abc", "not-a-uuid.secret", "0" * 32 + ".secret"):
        assert client.post("/auth/refresh", json={"refresh_token": token}).status_code == 401


def test_logout_revokes_the_refresh_token(client, admin):
    out = client.post("/auth/logout", json={"refresh_token": admin["refresh_token"]}, headers=bearer(admin))
    assert out.status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": admin["refresh_token"]}).status_code == 401


def test_change_password_issues_new_tokens_and_kills_old_ones(client, admin):
    wrong = client.post(
        "/me/password", json={"current_password": "x", "new_password": "new-password-1"}, headers=bearer(admin)
    )
    assert wrong.status_code == 400
    changed = client.post(
        "/me/password",
        json={"current_password": "correct-horse", "new_password": "new-password-1"},
        headers=bearer(admin),
    )
    assert changed.status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": admin["refresh_token"]}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": changed.json()["refresh_token"]}).status_code == 200
    assert client.post("/auth/login", json={"login": "admin@shree.example", "password": "correct-horse"}).status_code == 401
    assert client.post("/auth/login", json={"login": "admin@shree.example", "password": "new-password-1"}).status_code == 200


def test_profile_update(client, admin):
    updated = client.patch("/me", json={"name": "Asha P", "language": "gu", "phone": "98765 43210"}, headers=bearer(admin))
    assert updated.status_code == 200
    assert updated.json()["language"] == "gu" and updated.json()["phone"] == "9876543210"
    assert client.patch("/me", json={"name": None}, headers=bearer(admin)).status_code == 422
    assert client.patch("/me", json={"language": "fr"}, headers=bearer(admin)).status_code == 422


def test_invite_can_be_used_once(client, admin):
    invite = client.post(
        "/users/invites", json={"email": "clerk@shree.example", "role": "clerk"}, headers=bearer(admin)
    ).json()
    body = {"token": invite["token"], "name": "Ravi", "password": "staff-password"}
    first = client.post("/auth/invites/accept", json=body)
    assert first.status_code == 201
    assert client.get("/me", headers=bearer(first.json())).json()["role"] == "clerk"
    assert client.post("/auth/invites/accept", json=body).status_code == 400
    assert client.post("/auth/invites/accept", json={**body, "token": "junk"}).status_code == 400


def test_invite_for_existing_member_is_rejected(client, admin):
    add_staff(client, admin, "clerk@shree.example", "clerk")
    again = client.post("/users/invites", json={"email": "clerk@shree.example", "role": "clerk"}, headers=bearer(admin))
    assert again.status_code == 409
