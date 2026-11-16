import datetime as dt

from app.chat.interpreter import ToolCall, interpret
from app.clock import today
from tests.conftest import add_staff, bearer
from tests.test_dispatch import _lr, _truck
from tests.test_lr import NEW_LR

BIG = {"value": "80000", "distance_km": 900, "eway_bill_no": None}


def _dispatch(client, h, truck, lr, packages):
    return client.post(
        "/trips", json={"truck_id": truck, "destination": "Surat", "driver_name": "Ramesh", "lines": [{"lr_id": lr["id"], "packages": packages}]}, headers=h
    )


def test_evaluate_endpoint_and_state_list(client, admin):
    h = bearer(admin)
    states = client.get("/eway/states", headers=h).json()
    assert len(states) == 36 and {"code": "27", "name": "Maharashtra", "intra_state_threshold": "100000", "note": None} in states
    body = {"value": "80000", "from_state": "24", "to_state": "22", "consignor_registered": False, "consignee_registered": True, "distance_km": 450}
    result = client.post("/eway/evaluate", json=body, headers=h).json()
    assert (result["required"], result["responsible"], result["part_b_required"], result["validity_days"]) == (True, "consignee", True, 3)
    assert client.post("/eway/evaluate", json={**body, "from_state": "99"}, headers=h).status_code == 422


def test_an_lr_that_needs_a_bill_cannot_move_until_it_has_one(client, admin):
    h = bearer(admin)
    truck = _truck(client, h)
    lr = _lr(client, h, packages=5, **BIG)
    assert (lr["ewb_status"], lr["ewb_responsible"]) == ("pending", "consignor")
    assert "Rs 50,000" in lr["ewb_reason"]

    blocked = _dispatch(client, h, truck, lr, 5)
    assert blocked.status_code == 409 and "needs an e-way bill" in blocked.json()["error"]["message"]

    assert client.patch(f"/lrs/{lr['id']}/eway-bill", json={"eway_bill_no": "123"}, headers=h).status_code == 422
    with_bill = client.patch(f"/lrs/{lr['id']}/eway-bill", json={"eway_bill_no": "692194190201"}, headers=h).json()
    assert with_bill["ewb_status"] == "awaiting_part_b" and with_bill["ewb_valid_until"] is None
    # Part A is locked once entered
    assert client.patch(f"/lrs/{lr['id']}/eway-bill", json={"eway_bill_no": "111111111111"}, headers=h).status_code == 409

    assert _dispatch(client, h, truck, lr, 5).status_code == 201
    moving = client.get(f"/lrs/{lr['id']}", headers=h).json()
    assert (moving["ewb_status"], moving["ewb_vehicle_number"]) == ("active", "GJ03CW0620")
    # 900 km is 5 days: valid through the end of the fifth day, counting today
    expires = dt.datetime.fromisoformat(moving["ewb_valid_until"]).astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30)))
    assert expires.date() == today() + dt.timedelta(days=5) and expires.time() == dt.time(0, 0)


def test_booking_rules_for_parties_and_distance(client, admin):
    h = bearer(admin)
    post = lambda **changes: client.post("/lrs", json={**NEW_LR, **changes}, headers=h)
    assert post().json()["ewb_status"] == "not_required"
    assert post(goods_category="household_effects", value="900000").json()["ewb_status"] == "exempt"
    assert post(goods_category="job_work", distance_km=900, eway_bill_no=None).json()["ewb_status"] == "pending"
    assert post(value="80000", distance_km=None).status_code == 422  # needs a bill, so distance is needed
    assert post(value=None).status_code == 422  # cannot decide without a value
    assert post(from_state="99").status_code == 422
    assert post(hsn_code="48239").status_code == 422

    unregistered = {"consignor_gstin": None, "consignee_gstin": None}
    assert post(**unregistered).status_code == 422
    assert post(**unregistered, consignor_pan="ABCDE1234F").status_code == 422
    ok = post(**unregistered, consignor_pan="abcde1234f", consignee_pan="PQRSX9876K", value="80000", distance_km=300, eway_bill_no=None)
    assert ok.status_code == 201 and ok.json()["ewb_responsible"] == "transporter"
    assert post(consignor_pan="ZZZZZ0000Z").status_code == 422  # does not match the GST number
    assert post(consignor_pan="AABCR4141H").status_code == 201


def test_truck_with_expired_papers_cannot_go_out(client, admin):
    h = bearer(admin)
    truck = _truck(client, h)
    lr = _lr(client, h, packages=5)
    yesterday = str(today() - dt.timedelta(days=1))
    client.patch(f"/trucks/{truck}", json={"fitness_expiry": yesterday}, headers=h)
    blocked = _dispatch(client, h, truck, lr, 5)
    assert blocked.status_code == 409 and "fitness certificate expired" in blocked.json()["error"]["message"]
    client.patch(f"/trucks/{truck}", json={"fitness_expiry": str(today())}, headers=h)
    assert _dispatch(client, h, truck, lr, 5).status_code == 201
    assert client.patch(f"/trucks/{truck}", json={"model_year": 1950}, headers=h).status_code == 422


def test_undo_delivery_reopens_the_trip(client, admin):
    h = bearer(admin)
    truck = _truck(client, h)
    lr = _lr(client, h, packages=5)
    trip = _dispatch(client, h, truck, lr, 5).json()
    line = trip["lines"][0]["id"]
    undo = f"/trips/{trip['id']}/lines/{line}/undo-delivery"
    assert client.post(undo, headers=h).status_code == 409  # nothing to undo yet
    assert client.post(f"/trips/{trip['id']}/lines/{line}/deliver", headers=h).json()["status"] == "completed"

    dispatcher = add_staff(client, admin, "d@shree.example", "dispatcher")
    assert client.post(undo, headers=bearer(dispatcher)).status_code == 403
    reopened = client.post(undo, headers=h).json()
    assert reopened["status"] == "dispatched" and reopened["lines"][0]["delivered_at"] is None
    assert client.get("/dashboard", headers=h).json()["trips_on_road"] == 1

    # once the truck is out again, its old completed trip stays closed
    client.post(f"/trips/{trip['id']}/lines/{line}/deliver", headers=h)
    again = _lr(client, h, packages=1)
    assert _dispatch(client, h, truck, again, 1).status_code == 201
    assert client.post(undo, headers=h).status_code == 409


def test_chat_finds_old_goods_and_the_trip_that_carried_them(client, admin):
    question = "The 2 packages of machinery went into which trip, and what were the details?"
    assert interpret(question, today()) == ToolCall("find_goods", {"goods": "machinery", "packages": 2})
    assert interpret("which truck carried the laminate", today()) == ToolCall("find_goods", {"goods": "laminate", "packages": None})

    h = bearer(admin)
    truck = _truck(client, h)
    lr = _lr(client, h, days_ago=60, packages=2, goods_description="Machinery parts")
    _lr(client, h, packages=7, goods_description="Machinery")
    trip = _dispatch(client, h, truck, lr, 2).json()
    client.post(f"/trips/{trip['id']}/lines/{trip['lines'][0]['id']}/deliver", headers=h)

    answer = client.post("/chat", json={"message": question}, headers=h).json()
    assert answer["tool"] == "find_goods" and answer["lr_numbers"] == [lr["lr_number"]]
    for part in ("2 packages of Machinery parts", "truck GJ03CW0620 to SURAT", "driver Ramesh", "delivered", "e-way bill 622194022693"):
        assert part in answer["answer"], part
    details = client.post("/chat", json={"message": f"where is {lr['lr_number']}"}, headers=h).json()["answer"]
    assert "All 2 packages are delivered" in details and "truck GJ03CW0620" in details
    assert "found no LR" in client.post("/chat", json={"message": "which trip carried the bananas"}, headers=h).json()["answer"]
