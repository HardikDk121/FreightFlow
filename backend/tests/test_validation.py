"""The QA review's cases (25 November 2026), one test per screen: each bad value is refused with a
plain message naming the field, and each good value is accepted and normalised."""

import datetime as dt

import pytest

from app.clock import today
from app.config import get_settings
from app.main import app
from app.notify import get_outbox
from tests.conftest import bearer
from tests.test_dispatch import TRUCK, _lr
from tests.test_lr import NEW_LR
from tests.test_payments import _receipt


def _error(response) -> tuple[int, str, dict]:
    body = response.json()["error"]
    return response.status_code, body["message"], body.get("fields", {})


def _no_internals(message: str) -> None:
    for leak in ("pattern", "^[", "regex", "String should", "pydantic", "type=", "input_value"):
        assert leak not in message, message


SIGN_UP = {"company_name": "Transport99", "name": "Asha Patel", "email": "asha@transport99.example", "password": "three blue trucks", "phone": "9825011111"}


@pytest.mark.parametrize("field,value,message", [
    ("company_name", "1", "Must be at least 2 characters and cannot contain only numbers"),
    ("company_name", "12345", "cannot contain only numbers"),
    ("company_name", "   ", "Must be at least 2 characters"),
    ("name", "1334", "Use letters"),
    ("name", "   ", "Enter the full name"),
    ("phone", "1234567890", "starting with 6, 7, 8 or 9"),
    ("phone", "98250", "10-digit"),
    ("password", "short pass", "at least 12 characters"),
    ("password", "123456789012", "only numbers"),
    ("password", "password2026!", "most common passwords"),
    ("password", "            ", "only spaces"),
    ("email", "not-an-email", "Enter a valid email address"),
])
def test_sign_up_refuses_each_bad_value_plainly(client, field, value, message):
    status, text, fields = _error(client.post("/auth/register", json={**SIGN_UP, field: value}))
    assert status == 422 and message in fields[field], fields
    _no_internals(text)


@pytest.mark.parametrize("company", ["AB", "Transport99", "ABC Logistics 2", "A1", "Sharma & Sons (Rajkot)"])
def test_sign_up_accepts_real_company_names(client, company):
    response = client.post("/auth/register", json={**SIGN_UP, "company_name": f"  {company}  "})
    assert response.status_code == 201, response.text
    assert client.get("/company", headers=bearer(response.json())).json()["name"] == company


def test_phone_numbers_are_normalised_and_sign_in_works_however_typed(client):
    response = client.post("/auth/register", json={**SIGN_UP, "phone": "+91 98250-11111"})
    assert response.status_code == 201
    assert client.get("/me", headers=bearer(response.json())).json()["phone"] == "9825011111"
    for typed in ("9825011111", "+919825011111", "098250 11111"):
        assert client.post("/auth/login", json={"login": typed, "password": SIGN_UP["password"]}).status_code == 200, typed
    # a number from another country keeps its code
    other = client.post("/auth/register", json={**SIGN_UP, "email": "dubai@transport99.example", "phone": "+971 50 123 4567"})
    assert client.get("/me", headers=bearer(other.json())).json()["phone"] == "+971501234567"


def test_an_email_already_registered_is_named_clearly(client, admin):
    status, text, _ = _error(client.post("/auth/register", json={**SIGN_UP, "email": "ADMIN@shree.example"}))
    assert status == 409 and text.startswith("An account with this email already exists")


def test_sign_up_email_code_when_verification_is_on(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_verification", "required")
    outbox = app.dependency_overrides[get_outbox]()
    sent = client.post("/auth/register/code", json={"email": SIGN_UP["email"]}).json()
    assert (sent["required"], sent["expires_in"], sent["resend_after"]) == (True, 600, 60)
    code = outbox.emails[-1][2].split("Your code is ")[1][:6]
    # a second code within the minute is refused, with the wait
    again = client.post("/auth/register/code", json={"email": SIGN_UP["email"]})
    assert again.status_code == 429 and "seconds" in again.json()["error"]["message"]
    # without a code, or with a wrong one, no account is made
    assert _error(client.post("/auth/register", json=SIGN_UP))[1] == "Enter the 6-digit code we emailed you."
    wrong = "000000" if code != "000000" else "111111"
    assert "4 tries left" in _error(client.post("/auth/register", json={**SIGN_UP, "email_code": wrong}))[1]
    made = client.post("/auth/register", json={**SIGN_UP, "email_code": code})
    assert made.status_code == 201
    # the code works once, and the address now has an account
    assert client.post("/auth/register/code", json={"email": SIGN_UP["email"]}).status_code == 409


def test_five_wrong_sign_up_codes_lock_the_code(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_verification", "required")
    outbox = app.dependency_overrides[get_outbox]()
    client.post("/auth/register/code", json={"email": SIGN_UP["email"]})
    code = outbox.emails[-1][2].split("Your code is ")[1][:6]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        client.post("/auth/register", json={**SIGN_UP, "email_code": wrong})
    locked = client.post("/auth/register", json={**SIGN_UP, "email_code": code})
    assert locked.status_code == 429 and "Ask for a new one" in locked.json()["error"]["message"]


def test_company_settings_name_rule_matches_sign_up(client, admin):
    h = bearer(admin)
    for bad in ("1", "A", "12345", " 1 ", ""):
        assert client.patch("/company", json={"name": bad}, headers=h).status_code == 422, bad
    assert client.patch("/company", json={"name": "ABC Logistics 2"}, headers=h).json()["name"] == "ABC Logistics 2"
    assert client.patch("/company", json={"address": "11"}, headers=h).status_code == 422


@pytest.mark.parametrize("changes,field", [
    ({"value": "-0000"}, "value"),
    ({"value": "0"}, "value"),
    ({"from_city": "@RAJKOT"}, "from_city"),
    ({"to_city": "##AHEMDABAD"}, "to_city"),
    ({"to_city": "12345"}, "to_city"),
    ({"packages": 0}, "packages"),
    ({"packages": 2.5}, "packages"),
    ({"weight": "-5"}, "weight"),
    ({"hsn_code": "12AB"}, "hsn_code"),
    ({"eway_bill_no": "12345"}, "eway_bill_no"),
    ({"enrolment_id": "SHORT"}, "enrolment_id"),
    ({"consignor_name": "1"}, "consignor_name"),
])
def test_lr_refuses_bad_values_plainly(client, admin, changes, field):
    status, text, fields = _error(client.post("/lrs", json={**NEW_LR, **changes}, headers=bearer(admin)))
    assert status == 422 and field in fields, fields
    _no_internals(text)


def test_lr_normalises_cities_and_decimals(client, admin):
    lr = client.post("/lrs", json={**NEW_LR, "from_city": "  rajkot ", "to_city": "new  delhi", "value": ".5"}, headers=bearer(admin)).json()
    assert (lr["from_city"], lr["to_city"], lr["value"]) == ("RAJKOT", "NEW DELHI", "0.50")
    same = client.post("/lrs", json={**NEW_LR, "from_city": "Raipur", "to_city": "RAIPUR"}, headers=bearer(admin))
    assert same.status_code == 422


def test_item_type_rules_and_stacking_is_kept(client, admin):
    h = bearer(admin)
    body = {"name": "Laminate bundle", "length_cm": 10, "width_cm": 10, "height_cm": 10, "unit_weight_kg": ".5", "stackable": False}
    for bad in ({"name": "11"}, {"name": "   "}, {"name": "!!"}, {"length_cm": 0}, {"width_cm": -5}, {"unit_weight_kg": 0}, {"height_cm": "ten"}):
        status, text, _ = _error(client.post("/item-types", json={**body, **bad}, headers=h))
        assert status == 422, bad
        _no_internals(text)
    item = client.post("/item-types", json=body, headers=h).json()
    assert (item["unit_weight_kg"], item["stackable"]) == (0.5, False)
    assert client.get(f"/item-types/{item['id']}", headers=h).json()["stackable"] is False


def test_party_rules(client, admin):
    h = bearer(admin)
    good = {"name": "Noble Marketing", "gstin": "22AAOFN1693A1ZI", "phone": "9825011111"}
    for bad, field in ((({"name": "1"}), "name"), ({"address": "1"}, "address"), ({"phone": "1234567890"}, "phone"),
                       ({"gstin": "22AAOFN1693A1ZA"}, "gstin"), ({"gstin": "99AAOFN1693A1Z"}, "gstin"), ({"latitude": 22.3}, "request"),
                       ({"latitude": 95, "longitude": 70}, "latitude")):
        status, text, fields = _error(client.post("/parties", json={**good, **bad}, headers=h))
        assert status == 422 and (field in fields or field == "request"), (bad, fields)
        _no_internals(text)
    party = client.post("/parties", json={**good, "gstin": "22aaofn1693a1zi", "latitude": 21.25, "longitude": 81.63}, headers=h).json()
    assert party["gstin"] == "22AAOFN1693A1ZI"
    assert client.patch(f"/parties/{party['id']}", json={"latitude": 21.3}, headers=h).status_code == 422


def test_truck_owner_rules_and_no_regex_in_messages(client, admin):
    h = bearer(admin)
    status, text, fields = _error(client.post("/vendors", json={"name": "Eagle", "kind": "broker", "pan": "SHRIDB"}, headers=h))
    assert status == 422 and fields["pan"] == "Enter a valid 10-character PAN, like ABCDE1234F."
    _no_internals(text)
    assert client.post("/vendors", json={"name": "Eagle", "phone": "1234567890"}, headers=h).status_code == 422
    assert client.post("/vendors", json={"name": "Eagle", "bank_details": "jduwf"}, headers=h).status_code == 422
    ok = client.post("/vendors", json={"name": "Eagle", "pan": "abcpe1234k", "bank_details": "Eagle Transport, A/c 123456789012, IFSC ICIC0001234"}, headers=h)
    assert ok.status_code == 201 and ok.json()["pan"] == "ABCPE1234K"


def test_truck_rules(client, admin):
    h = bearer(admin)
    for bad in ({"vehicle_number": "1234"}, {"model_year": 1800}, {"model_year": today().year + 5}, {"inner_length_cm": 0},
                {"payload_kg": -1}, {"insurance_expiry": "2026-02-30"}):
        status, text, _ = _error(client.post("/trucks", json={**TRUCK, **bad}, headers=h))
        assert status == 422, bad
        _no_internals(text)
    truck = client.post("/trucks", json={**TRUCK, "vehicle_number": "mh 01 ge 0920"}, headers=h).json()
    assert truck["vehicle_number"] == "MH01GE0920"
    assert client.post("/trucks", json={**TRUCK, "vehicle_number": "MH01-GE-0920"}, headers=h).status_code == 409


def test_branch_rules(client, admin):
    h = bearer(admin)
    for bad in ({"name": "11"}, {"name": "Raipur", "address": "11"}, {"name": "Raipur", "cities": ["1", "2"]},
                {"name": "Raipur", "cities": ["RAIPUR", ""]}, {"name": "Raipur", "phone": "1234567890"}):
        assert client.post("/branches", json=bad, headers=h).status_code == 422, bad
    assert client.post("/branches", json={"name": "Raipur", "cities": ["Raipur", "raipur"]}, headers=h).status_code == 409
    assert client.post("/branches", json={"name": "Raipur", "cities": ["Raipur", "Dhamtari"]}, headers=h).status_code == 201
    clash = client.post("/branches", json={"name": "Durg", "cities": ["dhamtari"]}, headers=h)
    assert clash.status_code == 409 and "already delivered by Raipur" in clash.json()["error"]["message"]


def test_visit_status_and_amount_must_agree(client, admin):
    h = bearer(admin)
    receipt = _receipt(client, admin, _lr(client, h, st_charges="4700"))
    url = f"/receipts/{receipt['id']}/visits"
    cases = [
        {"outcome": "part_paid", "payment": {"method": "cash", "amount": "-470"}},
        {"outcome": "part_paid", "payment": {"method": "cash", "amount": "10000"}},
        {"outcome": "paid", "payment": {"method": "cash", "amount": "100"}},
        {"outcome": "come_later", "promised_on": str(today() + dt.timedelta(days=2)), "payment": {"method": "cash", "amount": "100"}},
        {"outcome": "refused", "note": "No money", "payment": {"method": "cash", "amount": "100"}},
    ]
    for body in cases:
        status, text, _ = _error(client.post(url, json=body, headers=h))
        assert status in (409, 422), body
        _no_internals(text)


def test_customer_messages_go_only_after_the_payment_is_saved(client, admin, monkeypatch):
    from fastapi.testclient import TestClient

    from app import audit

    h = bearer(admin)
    outbox = app.dependency_overrides[get_outbox]()
    receipt = _receipt(client, admin, _lr(client, h, st_charges="500"))
    before = len(outbox.texts)
    real = audit.record

    def fail_on_visit(session, **kwargs):
        if kwargs.get("action") == "receipt.visit":
            raise RuntimeError("database went away")
        return real(session, **kwargs)

    monkeypatch.setattr(audit, "record", fail_on_visit)
    failed = TestClient(app, raise_server_exceptions=False).post(
        f"/receipts/{receipt['id']}/visits", json={"outcome": "paid", "payment": {"method": "cash", "amount": "500"}}, headers=h)
    assert failed.status_code == 500 and len(outbox.texts) == before  # nothing saved, nothing sent
    monkeypatch.setattr(audit, "record", real)
    saved = client.post(f"/receipts/{receipt['id']}/visits", json={"outcome": "paid", "payment": {"method": "cash", "amount": "500"}}, headers=h)
    assert saved.status_code == 201 and len(outbox.texts) == before + 1
    notices = client.get(f"/receipts/{receipt['id']}", headers=h).json()
    assert notices["id"] == receipt["id"]


def test_contract_rules(client, admin):
    h = bearer(admin)
    body = {"party_name": "Joe Traders", "starts_on": "2026-11-25", "ends_on": "2027-05-25", "rates": [{"destination": "Raipur", "basis": "per_kg", "rate": "5"}]}
    for bad in ({"ends_on": "2026-11-01"}, {"rates": [{"destination": "50", "basis": "per_kg", "rate": "50"}]},
                {"rates": [{"destination": "Raipur", "basis": "per_kg", "rate": "0"}]},
                {"rates": [{"destination": "Raipur", "basis": "per_kg", "rate": "5"}, {"destination": "raipur", "basis": "per_kg", "rate": "6"}]},
                {"party_name": "1"}):
        status, text, _ = _error(client.post("/contracts", json={**body, **bad}, headers=h))
        assert status == 422, bad
        _no_internals(text)
    assert client.post("/contracts", json=body, headers=h).status_code == 201
