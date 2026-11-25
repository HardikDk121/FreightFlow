"""Attacks a reviewer will try by hand: guessing passwords, forging tokens, raising one's own role,
reading another company's records by id, and sending text or bodies the server should refuse."""

import datetime as dt
import json

import jwt

from tests.conftest import add_staff, bearer, register
from tests.test_dispatch import _lr, _truck
from tests.test_payments import _receipt


def test_sign_in_pauses_after_repeated_wrong_passwords(client, admin):
    wrong = {"login": "admin@shree.example", "password": "not-the-password"}
    for _ in range(5):
        assert client.post("/auth/login", json=wrong).status_code == 401
    # Now even the right password waits: a guesser learns nothing from this response.
    paused = client.post("/auth/login", json={"login": "admin@shree.example", "password": "correct-horse"})
    assert paused.status_code == 429 and paused.json()["error"]["code"] == "too_many_attempts"
    # Another account from the same address is unaffected until the address limit.
    register(client, "Other Co", "other@example.com")
    assert client.post("/auth/login", json={"login": "other@example.com", "password": "correct-horse"}).status_code == 200
    # Wrong logins for unknown accounts count too, so the limit cannot be probed for who exists.
    for _ in range(5):
        client.post("/auth/login", json={"login": "ghost@example.com", "password": "x" * 8})
    assert client.post("/auth/login", json={"login": "ghost@example.com", "password": "x" * 8}).status_code == 429


def test_one_address_cannot_register_endless_companies(client):
    for i in range(5):
        register(client, f"Company {i}", f"owner{i}@example.com")
    sixth = client.post("/auth/register", json={"company_name": "Six", "name": "Six", "email": "six@example.com", "password": "correct-horse"})
    assert sixth.status_code == 429


def test_forged_expired_and_tampered_tokens_are_refused(client, admin):
    from app.security import decode_access_token

    claims = decode_access_token(admin["access_token"])
    now = dt.datetime.now(dt.UTC)
    forged_secret = jwt.encode({"sub": str(claims.user_id), "cid": str(claims.company_id), "iat": now, "exp": now + dt.timedelta(hours=1)}, "x" * 40, algorithm="HS256")
    unsigned = jwt.encode({"sub": str(claims.user_id), "cid": str(claims.company_id), "iat": now, "exp": now + dt.timedelta(hours=1)}, None, algorithm="none")
    from app.config import get_settings

    expired = jwt.encode({"sub": str(claims.user_id), "cid": str(claims.company_id), "iat": now - dt.timedelta(hours=2), "exp": now - dt.timedelta(hours=1)},
                         get_settings().jwt_secret, algorithm="HS256")
    for token in (forged_secret, unsigned, expired, admin["access_token"][:-4] + "AAAA", admin["refresh_token"]):
        assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    # A used refresh token, presented again, signs every session out.
    new = client.post("/auth/refresh", json={"refresh_token": admin["refresh_token"]}).json()
    assert client.post("/auth/refresh", json={"refresh_token": admin["refresh_token"]}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401


def test_nobody_can_raise_their_own_role_or_permissions(client, admin):
    clerk = add_staff(client, admin, "c@shree.example", "clerk")
    h = bearer(clerk)
    me = client.patch("/me", json={"name": "Ravi", "role": "admin", "permissions_granted": ["users.manage"], "company_id": "x"}, headers=h).json()
    assert me["role"] == "clerk" and "users.manage" not in me["permissions"]
    assert client.patch(f"/users/{me['id']}", json={"role": "admin"}, headers=h).status_code == 403
    assert client.post("/users/invites", json={"email": "evil@example.com", "role": "admin"}, headers=h).status_code == 403
    assert client.post("/branches", json={"name": "Evil"}, headers=h).status_code == 403
    assert client.post("/lrs/settings", json={}, headers=h).status_code in (403, 405)


def test_another_companys_records_cannot_be_read_or_changed_by_id(client, admin):
    """Every record of company A, asked for by company B's owner, is simply not found."""
    a = bearer(admin)
    lr = _lr(client, a, st_charges="100")
    trip = client.post("/trips", json={"truck_id": _truck(client, a), "stops": [lr["to_city"]], "lines": [{"lr_id": lr["id"], "packages": lr["packages"]}]}, headers=a).json()
    receipt = _receipt(client, admin, lr)
    vendor = client.post("/vendors", json={"name": "Owner A"}, headers=a).json()
    party = client.post("/parties", json={"name": "Party A"}, headers=a).json()
    gate = client.post("/gate-passes", json={"lr_ids": [_lr(client, a, freight_by="TBB")["id"]]}, headers=a).json()
    b = bearer(register(client, "Rival Co", "rival@example.com"))
    reads = [f"/lrs/{lr['id']}", f"/lrs/{lr['id']}/account", f"/lrs/{lr['id']}/pdf", f"/trips/{trip['id']}", f"/trips/{trip['id']}/money",
             f"/receipts/{receipt['id']}", f"/receipts/{receipt['id']}/pdf", f"/gate-passes/{gate['id']}", f"/gate-passes/{gate['id']}/pdf"]
    for url in reads:
        assert client.get(url, headers=b).status_code == 404, url
    writes = [
        ("POST", f"/lrs/{lr['id']}/cancel", {"reason": "sabotage"}),
        ("PUT", f"/trips/{trip['id']}/hire", {"vendor_id": vendor["id"], "hire_amount": "1"}),
        ("POST", f"/receipts/{receipt['id']}/cancel", {"reason": "sabotage"}),
        ("POST", f"/gate-passes/{gate['id']}/void", {"reason": "sabotage"}),
        ("PUT", f"/vendors/{vendor['id']}", {"name": "Hijacked"}),
        ("PATCH", f"/parties/{party['id']}", {"name": "Hijacked"}),
        ("POST", "/receipts", {"lr_ids": [lr["id"]]}),
    ]
    for method, url, body in writes:
        assert client.request(method, url, json=body, headers=b).status_code == 404, url
    # Lists show nothing of company A.
    for url in ("/lrs", "/trips", "/vendors", "/parties", "/gate-passes", "/receivables"):
        assert lr["lr_number"] not in client.get(url, headers=b).text and "Owner A" not in client.get(url, headers=b).text, url
    # And company A's records are untouched.
    assert client.get(f"/lrs/{lr['id']}", headers=a).json()["status"] == "confirmed"


def test_hostile_text_is_refused_in_names_and_stored_as_text_elsewhere(client, admin):
    h = bearer(admin)
    script = "<script>alert('x')</script>"
    # Names are names: markup and SQL punctuation are refused with a plain message.
    party = client.post("/parties", json={"name": script}, headers=h)
    assert party.status_code == 422 and "<" not in party.json()["error"]["message"]
    assert client.post("/parties", json={"name": "Robert'); DROP TABLE lr;--"}, headers=h).status_code == 422
    # Free text (goods description) keeps whatever was typed, exactly, as text.
    lr = _lr(client, h, goods_description="Robert'); DROP TABLE lr;--")
    assert client.get(f"/lrs/{lr['id']}", headers=h).json()["goods_description"] == "Robert'); DROP TABLE lr;--"
    # The one HTML page (the receipt check) escapes whatever it shows.
    import datetime as dt
    from decimal import Decimal

    from app.collections.printing import verification_page
    from app.collections.schemas import ReceiptVerification

    page = verification_page(ReceiptVerification(
        company_name=script, receipt_number="MR-1", payer_name=script, lr_numbers=["LR-1"], amount=Decimal(1),
        collected=Decimal(0), status="open", issued_on=dt.date(2026, 11, 25)))
    assert script not in page and "&lt;script&gt;" in page


def test_bad_bodies_get_clear_answers_not_crashes(client, admin):
    h = bearer(admin)
    nul = client.post("/parties", content=json.dumps({"name": "bad\u0000name"}), headers={**h, "Content-Type": "application/json"})
    assert nul.status_code == 422 and nul.json()["error"]["code"] == "bad_character"
    huge = client.post("/parties", content=b'{"name": "' + b"a" * 1_100_000 + b'"}', headers={**h, "Content-Type": "application/json"})
    assert huge.status_code == 413
    broken = client.post("/parties", content="{name: oops", headers={**h, "Content-Type": "application/json"})
    assert broken.status_code == 422 and "error" in broken.json()
    missing = client.post("/trucks", json={"vehicle_number": "GJ03AB1234"}, headers=h).json()
    assert missing["error"]["code"] == "invalid" and "payload_kg" in missing["error"]["fields"]
    assert client.get("/lrs", params={"offset": "99999999999999999999"}, headers=h).status_code == 422
    duplicate_branch = [client.post("/branches", json={"name": "Raipur"}, headers=h).status_code for _ in range(2)]
    assert duplicate_branch == [201, 409]


def test_every_response_carries_security_headers(client, admin):
    r = client.get("/me", headers=bearer(admin))
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    # The API does not invite other websites to call it from a browser.
    assert "access-control-allow-origin" not in client.options("/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}).headers
