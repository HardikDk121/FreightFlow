"""Two tabs, two phones, one record: simultaneous requests must not duplicate numbers or overpay."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import add_staff, bearer
from tests.test_lr import NEW_LR
from tests.test_payments import _receipt


def _parallel(n, call):
    def run(i):
        with TestClient(app, raise_server_exceptions=False) as c:
            return call(c, i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(run, range(n)))


def test_simultaneous_bookings_get_distinct_numbers_with_no_gaps(client, admin):
    h = bearer(admin)
    results = _parallel(8, lambda c, i: c.post("/lrs", json=NEW_LR, headers=h))
    assert all(r.status_code == 201 for r in results), [r.text for r in results if r.status_code != 201]
    numbers = sorted(int(r.json()["lr_number"].split("-")[1]) for r in results)
    assert numbers == list(range(1, 9))


def test_the_same_save_sent_twice_at_once_books_one_lr(client, admin):
    h = {**bearer(admin), "Idempotency-Key": "double-tap-0001"}
    results = _parallel(2, lambda c, i: c.post("/lrs", json=NEW_LR, headers=h))
    codes = sorted(r.status_code for r in results)
    # One books; the other is told to wait (409) or gets the same LR back (201).
    assert codes in ([201, 201], [201, 409])
    assert len(client.get("/lrs", headers=bearer(admin)).json()) == 1


def test_two_collectors_cannot_both_be_paid_for_the_same_balance(client, admin):
    h = bearer(admin)
    lr = client.post("/lrs", json={**NEW_LR, "st_charges": "1000"}, headers=h).json()
    receipt = _receipt(client, admin, lr)
    collectors = [bearer(add_staff(client, admin, f"c{i}@shree.example", "collector")) for i in range(2)]
    body = {"outcome": "paid", "payment": {"method": "cash", "amount": "1000"}}
    results = _parallel(2, lambda c, i: c.post(f"/receipts/{receipt['id']}/visits", json=body, headers=collectors[i]))
    assert sorted(r.status_code for r in results) == [201, 409], [r.text for r in results]
    account = client.get(f"/lrs/{lr['id']}/account", headers=h).json()
    assert (account["paid"], account["balance"]) == ("1000.00", "0.00")
