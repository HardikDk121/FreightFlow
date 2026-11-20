"""Collection tasks, escalation, reminders, the daily job and the operations dashboard."""

import datetime as dt

from sqlalchemy import text

from app.clock import today
from app.main import app
from app.notify import get_outbox
from tests.conftest import bearer
from tests.test_branches import _staff
from tests.test_dispatch import _lr, _truck
from tests.test_payments import _receipt, _visit


def _branch(client, h):
    return client.post("/branches", json={"name": "Raipur", "cities": ["Raipur"]}, headers=h).json()


def test_tasks_are_created_assigned_escalated_and_closed_by_the_app(client, admin):
    h = bearer(admin)
    raipur = _branch(client, h)
    ramesh = _staff(client, admin, "ramesh@shree.example", "collector", raipur["id"])
    manager = _staff(client, admin, "m@shree.example", "manager", raipur["id"])
    # two customers with money overdue (Paid LRs fall due at booking)
    a = _lr(client, h, to_city="Raipur", st_charges="400", freight_by="Paid", days_ago=5)
    _lr(client, h, to_city="Raipur", st_charges="100", freight_by="Paid", days_ago=1)
    _lr(client, h, to_city="Raipur", st_charges="300", freight_by="Paid", days_ago=2, consignor_name="Monal Laminate", consignor_gstin=None, consignor_pan="AAGCM3530N", consignee_pan="AWCPP8803A", consignee_gstin=None)

    mine = client.get("/tasks", headers=bearer(ramesh)).json()
    assert [(t["payer_name"], t["amount_due"], t["days_overdue"], t["assigned_name"]) for t in mine] == [
        ("Rangoli Laminate", "500.00", 5, "Ramesh"), ("Monal Laminate", "300.00", 2, "Ramesh")]
    assert client.get("/tasks", params={"scope": "all"}, headers=bearer(ramesh)).status_code == 403
    assert len(client.get("/tasks", params={"scope": "all"}, headers=bearer(manager)).json()) == 2
    # opening the list again does not duplicate tasks
    assert len(client.get("/tasks", headers=bearer(ramesh)).json()) == 2

    task = mine[0]
    promised = str(today() + dt.timedelta(days=3))
    attempt = client.post(f"/tasks/{task['id']}/attempts", json={"outcome": "promised", "promised_on": promised}, headers=bearer(ramesh)).json()
    assert (attempt["status"], attempt["next_action_on"], attempt["attempts"][0]["user"]) == ("promised", promised, "Ramesh")
    assert client.post(f"/tasks/{task['id']}/attempts", json={"outcome": "refused"}, headers=bearer(ramesh)).status_code == 422

    # a task nobody acts on is escalated after its date
    from tests.conftest import owner_engine

    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE collection_task SET next_action_on = current_date - 3 WHERE payer_name = 'Monal Laminate'"))
    escalated = [t for t in client.get("/tasks", params={"scope": "all"}, headers=bearer(manager)).json() if t["escalated"]]
    assert [t["payer_name"] for t in escalated] == ["Monal Laminate"]
    board = client.get("/dashboard/operations", headers=bearer(manager)).json()
    assert board["escalated_tasks"] == 1 and board["staff"][0]["escalated_tasks"] == 1

    # paying everything closes the task by itself; a receipt visit counts as an attempt
    clerk = _staff(client, admin, "s@shree.example", "register_clerk", raipur["id"])
    receipt = _receipt(client, clerk, a)
    _visit(client, ramesh, receipt, "paid", method="cash", amount="400")
    left = {t["payer_name"]: t for t in client.get("/tasks", params={"scope": "all"}, headers=bearer(manager)).json()}
    assert left["Rangoli Laminate"]["amount_due"] == "100.00" and left["Rangoli Laminate"]["attempts"][0]["outcome"] == "paid"


def test_reminders_go_once_and_respect_the_customers_terms(client, admin):
    h = bearer(admin)
    outbox = app.dependency_overrides[get_outbox]()
    client.post("/parties", json={"name": "Rangoli Laminate", "phone": "9824011111"}, headers=h)
    _lr(client, h, st_charges="250", freight_by="Paid", days_ago=1)  # first overdue reminder goes the day after
    _lr(client, h, st_charges="70", freight_by="Paid", consignor_name="No Phone Co", consignor_gstin=None, consignor_pan="AAGCM3530N", consignee_pan="AWCPP8803A", consignee_gstin=None, days_ago=1)
    client.patch("/company", json={"bank_details": "ICICI A/c 123456789012\\nIFSC ICIC0001234", "phone": "9327410932"}, headers=h)
    assert client.post("/reminders/run", headers=h).json() == {"recorded": 2}
    assert outbox.texts[-1][0] == "9824011111" and "Rs 250.00" in outbox.texts[-1][1] and "is overdue" in outbox.texts[-1][1]
    assert client.post("/reminders/run", headers=h).json() == {"recorded": 0}  # not again today
    history = client.get("/reminders", params={"payer": "rangoli laminate"}, headers=h).json()
    assert {(r["channel"], r["kind"], r["status"]) for r in history} == {("sms", "overdue", "sent"), ("whatsapp", "overdue", "sent")}
    client.put("/credit-terms", json={"payer_name": "Rangoli Laminate", "payment_terms": "at_delivery", "reminders": False}, headers=h)
    _lr(client, h, st_charges="10", freight_by="Paid", days_ago=1)
    with __import__("tests.conftest", fromlist=["owner_engine"]).owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM reminder"))
    assert client.post("/reminders/run", headers=h).json() == {"recorded": 0}


def test_the_daily_job_runs_every_company(client, admin):
    from app.jobs import daily

    h = bearer(admin)
    _lr(client, h, st_charges="100", freight_by="Paid", days_ago=3)
    result = daily()
    assert result["failed"] == 0 and result["companies"] >= 1
    assert len(client.get("/tasks", params={"scope": "all"}, headers=h).json()) == 1


def test_operations_dashboard_shows_where_deliveries_and_money_stand(client, admin):
    h = bearer(admin)
    raipur = _branch(client, h)
    waiting = _lr(client, h, to_city="Raipur", st_charges="100", freight_by="TBB")
    arrived = _lr(client, h, to_city="Raipur", st_charges="100", freight_by="TBB")
    _lr(client, h, to_city="Surat", st_charges="50", freight_by="TBB")
    trip = client.post("/trips", json={"truck_id": _truck(client, h), "stops": ["Raipur"], "lines": [{"lr_id": arrived["id"], "packages": arrived["packages"]}]}, headers=h).json()
    client.post(f"/trips/{trip['id']}/stops/RAIPUR/deliver", headers=h)
    from tests.conftest import owner_engine

    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE dispatch_line SET delivered_at = now() - interval '4 days'"))
    board = client.get("/dashboard/operations", headers=h).json()
    rows = {r["name"]: r for r in board["branches"]}
    assert (rows["Raipur"]["awaiting_dispatch"], rows["Raipur"]["awaiting_delivery"], rows["Raipur"]["receivable"]) == (1, 1, "200.00")
    assert rows["Head office"]["lrs_this_month"] == 3 and rows["Head office"]["receivable"] == "50.00"
    assert [(d["lr_number"], d["days"]) for d in board["late_delivery_updates"]] == [(arrived["lr_number"], 4)]
    # a Raipur manager sees only Raipur
    manager = _staff(client, admin, "m@shree.example", "manager", raipur["id"])
    scoped = client.get("/dashboard/operations", headers=bearer(manager)).json()
    assert [r["name"] for r in scoped["branches"]] == ["Raipur"] and scoped["receivable"] == "200.00"
    collector = _staff(client, admin, "r@shree.example", "collector", raipur["id"])
    assert client.get("/dashboard/operations", headers=bearer(collector)).status_code == 403
    assert waiting["delivery_branch_id"] == raipur["id"]
