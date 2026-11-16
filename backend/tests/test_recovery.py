import re

from tests.conftest import bearer, register

LOGIN = "admin@shree.example"


def _code(outbox) -> str:
    return re.search(r"\b(\d{6})\b", outbox.emails[-1][2]).group(1)


def _forgot(client, login=LOGIN):
    return client.post("/auth/password/forgot", json={"login": login})


def test_reset_password_with_emailed_code(client, outbox, admin):
    assert _forgot(client).status_code == 202
    assert outbox.emails[0][0] == LOGIN
    reset = {"login": LOGIN, "code": _code(outbox), "new_password": "brand-new-pass"}
    assert client.post("/auth/password/reset", json=reset).status_code == 204
    # the old password and every old session are dead; the code cannot be used twice
    assert client.post("/auth/login", json={"login": LOGIN, "password": "correct-horse"}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": admin["refresh_token"]}).status_code == 401
    assert client.post("/auth/login", json={"login": LOGIN, "password": "brand-new-pass"}).status_code == 200
    assert client.post("/auth/password/reset", json={**reset, "new_password": "another-pass-1"}).status_code == 400


def test_unknown_accounts_get_the_same_answer_and_no_email(client, outbox, admin):
    known, unknown = _forgot(client), _forgot(client, "ghost@nowhere.example")
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())
    assert [to for to, _, _ in outbox.emails] == [LOGIN]
    wrong_account = client.post(
        "/auth/password/reset", json={"login": "ghost@nowhere.example", "code": "123456", "new_password": "whatever-1"}
    )
    wrong_code = client.post("/auth/password/reset", json={"login": LOGIN, "code": "000000", "new_password": "whatever-1"})
    assert wrong_account.status_code == wrong_code.status_code == 400
    assert wrong_account.json() == wrong_code.json()


def test_five_wrong_codes_lock_the_code(client, outbox, admin):
    _forgot(client)
    right = _code(outbox)
    wrong = "000000" if right != "000000" else "111111"
    for _ in range(5):
        assert client.post("/auth/password/reset", json={"login": LOGIN, "code": wrong, "new_password": "whatever-1"}).status_code == 400
    locked = client.post("/auth/password/reset", json={"login": LOGIN, "code": right, "new_password": "whatever-1"})
    assert locked.status_code == 400
    assert client.post("/auth/login", json={"login": LOGIN, "password": "correct-horse"}).status_code == 200


def test_only_the_newest_code_works(client, outbox, admin):
    _forgot(client)
    first = _code(outbox)
    _forgot(client)
    second = _code(outbox)
    if first != second:
        assert client.post("/auth/password/reset", json={"login": LOGIN, "code": first, "new_password": "whatever-1"}).status_code == 400
    assert client.post("/auth/password/reset", json={"login": LOGIN, "code": second, "new_password": "whatever-1"}).status_code == 204


def test_requests_are_rate_limited_per_account_even_when_it_does_not_exist(client, outbox, admin):
    for login in (LOGIN, "ghost@nowhere.example"):
        assert [_forgot(client, login).status_code for _ in range(4)] == [202, 202, 202, 429]
    assert len(outbox.emails) == 3


def test_login_email_recovery_goes_only_to_the_phone(client, outbox):
    register(client, phone="9876543210")
    known = client.post("/auth/email/recover", json={"phone": "98765 43210"})
    unknown = client.post("/auth/email/recover", json={"phone": "9000000000"})
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json()) == (202, known.json())
    assert LOGIN not in known.text
    assert outbox.texts == [("9876543210", f"Your FreightFlow login email is {LOGIN}")]
    assert client.post("/auth/email/recover", json={"phone": "abc"}).status_code == 422
    assert [client.post("/auth/email/recover", json={"phone": "9876543210"}).status_code for _ in range(3)] == [202, 202, 429]


def test_deactivated_users_cannot_reset(client, outbox, admin):
    from tests.conftest import add_staff

    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    clerk_id = client.get("/me", headers=bearer(clerk)).json()["id"]
    client.patch(f"/users/{clerk_id}", json={"is_active": False}, headers=bearer(admin))
    assert _forgot(client, "clerk@shree.example").status_code == 202
    assert outbox.emails == []
