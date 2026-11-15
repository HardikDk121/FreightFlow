import datetime as dt

from sqlalchemy import text

from app.chat.interpreter import GREETING, Reply, ToolCall, interpret
from app.clock import today
from tests.conftest import bearer, register
from tests.test_dispatch import _lr, _truck
from tests.test_tenancy import SCOPE, app_engine

SUNDAY = dt.date(2026, 11, 15)


def test_questions_map_to_one_tool():
    cities = frozenset({"surat", "new delhi"})
    cases = {
        "What is pending for Surat?": ToolCall("pending_by_destination", {"destination": "surat"}),
        "which goods are waiting in new delhi": ToolCall("pending_by_destination", {"destination": "new delhi"}),
        "surat ka kitna baki hai": ToolCall("pending_by_destination", {"destination": "surat"}),
        "anything for Surat?": ToolCall("pending_by_destination", {"destination": "surat"}),
        "what is pending for Mumbai": ToolCall("pending_by_destination", {"destination": "mumbai"}),
        "What came on Monday?": ToolCall("arrivals_on_date", {"date": dt.date(2026, 11, 9)}),
        "what arrived today": ToolCall("arrivals_on_date", {"date": SUNDAY}),
        "how many LRs yesterday": ToolCall("arrivals_on_date", {"date": dt.date(2026, 11, 14)}),
        "what was booked on 04-10-2026": ToolCall("arrivals_on_date", {"date": dt.date(2026, 10, 4)}),
        "Which goods have waited more than 3 days?": ToolCall("pending_older_than", {"days": 3}),
        "Where is RJT-422692 and has it gone?": ToolCall("lr_details", {"lr_number": "RJT-422692", "fields": ["status"]}),
        "LR-1": ToolCall("lr_details", {"lr_number": "LR-1", "fields": []}),
        "LR-1 weight": ToolCall("lr_details", {"lr_number": "LR-1", "fields": ["weight"]}),
        "wieght and frieght of lr-7": ToolCall("lr_details", {"lr_number": "LR-7", "fields": ["charges", "weight"]}),
        "what is pending": ToolCall("pending_summary"),
        "which trucks are on the road": ToolCall("trips_on_road"),
        "where is gj 03 cw 0620": ToolCall("truck_status", {"vehicle_number": "GJ03CW0620"}),
        "show last 5 bilty": ToolCall("recent_lrs"),
        "lrs for jalaram enterprise": ToolCall("search_lrs", {"party": "jalaram enterprise"}),
    }
    for question, expected in cases.items():
        assert interpret(question, SUNDAY, cities) == expected, question

    # a follow-up is about the LR already being discussed
    assert interpret("and its value?", SUNDAY, cities, "LR-1") == ToolCall("lr_details", {"lr_number": "LR-1", "fields": ["value"]})
    # without one, the assistant asks which LR, typos and all
    assert isinstance(interpret("weight of confisgment", SUNDAY, cities), Reply)
    assert interpret("hello", SUNDAY, cities) == Reply(GREETING)
    for question in ("Change the destination of RJT-412 to Delhi.", "delete LR-1", "tell me a joke", "what came on someday"):
        assert interpret(question, SUNDAY, cities) is None, question


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
    assert pending["answer"].startswith("40 packages on 2 LRs are pending for SURAT")
    assert pending["suggestions"][0] == f"Details of {old['lr_number']}"

    assert _ask(client, admin, "which goods waited more than 3 days")["lr_numbers"] == [old["lr_number"]]
    assert _ask(client, admin, "what came today")["lr_numbers"] == [new["lr_number"]]
    status = _ask(client, admin, f"where is {old['lr_number'].lower()}")
    assert status["tool"] == "lr_details"
    assert "20 of 50 packages dispatched, 0 delivered, 30 pending" in status["answer"]
    assert "could not find" in _ask(client, admin, "status of ZZ-999")["answer"]
    assert _ask(client, admin, "what is pending for Mumbai")["answer"] == "Nothing is pending for MUMBAI."

    weight = _ask(client, admin, f"{old['lr_number']} weight")
    assert "Weight 100 kg" in weight["answer"] and "Rate" not in weight["answer"]
    follow_up = client.post(
        "/chat", json={"message": "and the charges?", "context_lr_number": old["lr_number"]}, headers=h
    ).json()
    assert "Total Rs. 35.00, ToPay" in follow_up["answer"] and follow_up["lr_numbers"] == [old["lr_number"]]
    everything = _ask(client, admin, old["lr_number"])["answer"]
    for part in ("RANGOLI", "Weight 100 kg", "Goods value Rs. 12,048.00", "E-way bill 622194022693"):
        assert part in everything or part.title() in everything, part

    road = _ask(client, admin, "which trucks are on road")
    assert road["tool"] == "trips_on_road" and "GJ03CW0620 to SURAT: 0 of 1 LRs delivered" in road["answer"]
    assert "is on the road" in _ask(client, admin, "where is GJ03CW0620")["answer"]
    assert _ask(client, admin, "lrs for rangoli")["lr_numbers"] == [new["lr_number"], old["lr_number"]]
    assert "Which LR do you mean" in _ask(client, admin, "weight of consignment")["answer"]


def test_write_requests_are_refused_and_change_nothing(client, admin):
    lr = _lr(client, bearer(admin), packages=5)
    refused = _ask(client, admin, f"Cancel {lr['lr_number']} and change its destination to Delhi")
    assert refused["answer"] == "I can only read information. Please change records in the app."
    assert refused["tool"] is None and refused["lr_numbers"] == []
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
    assert logged == ["pending_by_destination", "lr_details"]


def test_today_is_the_business_date():
    assert abs((today() - dt.datetime.now(dt.UTC).date()).days) <= 1
