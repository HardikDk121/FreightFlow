import datetime as dt

from sqlalchemy import text

from app.chat.interpreter import ToolCall, interpret
from app.clock import today
from tests.conftest import bearer, register
from tests.test_dispatch import _lr, _truck
from tests.test_tenancy import SCOPE, app_engine

SUNDAY = dt.date(2026, 11, 15)


def test_questions_map_to_one_tool():
    cases = {
        "What is pending for Surat?": ToolCall("pending_by_destination", {"destination": "surat"}),
        "which goods are waiting in new delhi": ToolCall("pending_by_destination", {"destination": "new delhi"}),
        "What came on Monday?": ToolCall("arrivals_on_date", {"date": dt.date(2026, 11, 9)}),
        "what arrived today": ToolCall("arrivals_on_date", {"date": SUNDAY}),
        "what was booked on 04-10-2026": ToolCall("arrivals_on_date", {"date": dt.date(2026, 10, 4)}),
        "Which goods have waited more than 3 days?": ToolCall("pending_older_than", {"days": 3}),
        "Where is RJT-422692 and has it gone?": ToolCall("lr_status", {"lr_number": "RJT-422692"}),
        "what is pending": ToolCall("pending_summary"),
    }
    for question, expected in cases.items():
        assert interpret(question, SUNDAY) == expected, question
    for question in ("Change the destination of RJT-412 to Delhi.", "delete LR-1", "tell me a joke", "what came on someday"):
        assert interpret(question, SUNDAY) is None, question


def _ask(client, tokens, message):
    response = client.post("/chat", json={"message": message}, headers=bearer(tokens))
    assert response.status_code == 200, response.text
    return response.json()


def test_answers_match_the_database(client, admin):
    h = bearer(admin)
    old = _lr(client, h, days_ago=5, packages=50)
    new = _lr(client, h, days_ago=0, packages=10)
    truck = _truck(client, h)
    client.post("/trips", json={"truck_id": truck, "destination": "Surat", "lines": [{"lr_id": old["id"], "packages": 20}]}, headers=h)

    pending = _ask(client, admin, "What is pending for Surat?")
    assert pending["tool"] == "pending_by_destination"
    assert pending["lr_numbers"] == [old["lr_number"], new["lr_number"]]
    assert "30 of 50 packages" in pending["answer"] and "waiting 5 days" in pending["answer"]

    assert _ask(client, admin, "which goods waited more than 3 days")["lr_numbers"] == [old["lr_number"]]
    assert _ask(client, admin, "what came today")["lr_numbers"] == [new["lr_number"]]
    status = _ask(client, admin, f"where is {old['lr_number'].lower()}")
    assert "20 of 50 packages dispatched, 0 delivered, 30 pending" in status["answer"]
    assert "could not find" in _ask(client, admin, "status of ZZ-999")["answer"]
    assert _ask(client, admin, "what is pending for Mumbai")["answer"] == "Nothing is pending for MUMBAI."


def test_write_requests_are_refused_and_change_nothing(client, admin):
    lr = _lr(client, bearer(admin), packages=5)
    refused = _ask(client, admin, f"Cancel {lr['lr_number']} and change its destination to Delhi")
    assert refused == {"answer": "I can only read information. Please change records in the app.", "tool": None, "lr_numbers": []}
    assert client.get(f"/lrs/{lr['id']}", headers=bearer(admin)).json()["status"] == "confirmed"
    assert _ask(client, admin, "hello")["tool"] is None


def test_chat_sees_only_its_own_company_and_is_audited(client, admin):
    lr = _lr(client, bearer(admin), packages=5)
    other = register(client, "Other Transport", "o@o.example")
    assert _ask(client, other, "what is pending for surat")["lr_numbers"] == []
    assert "could not find" in _ask(client, other, f"where is {lr['lr_number']}")["answer"]

    company_id = client.get("/company", headers=bearer(other)).json()["id"]
    with app_engine.connect() as conn:
        conn.execute(text(SCOPE), {"c": company_id})
        logged = conn.execute(text("SELECT detail->>'tool' FROM audit_log WHERE action = 'chat.ask' ORDER BY id")).scalars().all()
    assert logged == ["pending_by_destination", "lr_status"]


def test_today_is_the_business_date():
    assert abs((today() - dt.datetime.now(dt.UTC).date()).days) <= 1
