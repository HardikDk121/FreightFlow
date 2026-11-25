import datetime as dt
import io
import json
from decimal import Decimal as D

import openpyxl
import pytest

from app.bank import statement
from app.clock import today
from app.main import app
from app.notify import get_outbox
from tests.conftest import add_staff, bearer
from tests.test_collections import _user_id
from tests.test_dispatch import _lr
from tests.test_payments import _receipt, _visit

# The shape of a typical Indian bank download: account details above the table, Indian dates,
# separate withdrawal and deposit columns, references inside the remarks.
PREAMBLE = [
    ["Account Number", "XXXXXXXX1234"],
    ["Statement period", "01/11/2026 to 30/11/2026"],
    [],
]
HEADER = ["S No.", "Value Date", "Transaction Date", "Cheque Number", "Transaction Remarks", "Withdrawal Amount (INR )", "Deposit Amount (INR )", "Balance (INR )"]


def _csv(rows: list[list[str]]) -> bytes:
    out = io.StringIO()
    for row in rows:
        out.write(",".join(f'"{c}"' for c in row) + "\r\n")
    return out.getvalue().encode()


def _row(n, day: dt.date, remarks, deposit="", withdrawal="", cheque="", balance="100000.00"):
    d = day.strftime("%d/%m/%Y")
    return [str(n), d, d, cheque, remarks, withdrawal, deposit, balance]


def test_reads_a_bank_download_and_finds_its_columns():
    day = dt.date(2026, 11, 16)
    rows = [*PREAMBLE, HEADER,
            _row(1, day, "UPI/432112345670/PAYMENT FROM CUST/ok@okaxis", deposit="1,000.00"),
            _row(2, day, "NEFT-SBIN426112233445-MONAL LAMINATE PVT LTD", deposit="12,048.00"),
            _row(3, day, "ATM WDL", withdrawal="500.00"),
            ["", "", "", "", "Opening balance 99000", "", "", ""]]
    parsed = statement.read_rows(_csv(rows), "OpTransactionHistory.csv")
    header_row, mapping = statement.detect(parsed)
    assert header_row == 3
    assert mapping == {"date": 2, "narration": 4, "reference": 3, "credit": 6, "debit": 5, "balance": 7}
    lines, problems = statement.parse(parsed, header_row, mapping)
    assert [(l.txn_date, l.credit, l.debit) for l in lines] == [(day, D("1000.00"), 0), (day, D("12048.00"), 0), (day, 0, D("500.00"))]
    assert lines[0].refs == "432112345670" and lines[1].refs == "SBIN426112233445"
    assert problems == []
    # the same file twice gives the same fingerprints, so re-importing adds nothing
    again, _ = statement.parse(parsed, header_row, mapping)
    assert [l.row_hash for l in again] == [l.row_hash for l in lines]


def test_reads_xlsx_with_one_amount_column_and_a_cr_dr_marker():
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Txn Date", "Description", "Amount", "Cr/Dr", "Balance"])
    sheet.append([dt.datetime(2026, 11, 16), "IMPS/P2A/432199998888/CUST", 2500, "CR", 10000])
    sheet.append([dt.datetime(2026, 11, 16), "CHARGES", 59, "DR", 9941])
    sheet.append([dt.datetime(2026, 11, 17), "IMPS/P2A/432199998888/CUST", 2500, "CR", 12441])
    data = io.BytesIO()
    book.save(data)
    rows = statement.read_rows(data.getvalue(), "statement.xlsx")
    header_row, mapping = statement.detect(rows)
    lines, _ = statement.parse(rows, header_row, mapping)
    assert [(l.credit, l.debit) for l in lines] == [(D(2500), 0), (0, D(59)), (D(2500), 0)]


def test_unreadable_files_say_what_to_do():
    with pytest.raises(statement.StatementError, match="CSV, XLS or XLSX"):
        statement.read_rows(b"%PDF-1.4", "statement.pdf")
    with pytest.raises(statement.StatementError, match="Could not find the table"):
        statement.detect([["just", "some"], ["words", "here"]])


def _import(client, h, rows, name="statement.csv"):
    data = _csv(rows)
    preview = client.post("/bank/statements/preview", files={"file": (name, data, "text/csv")}, headers=h)
    assert preview.status_code == 200, preview.text
    result = client.post(
        "/bank/statements",
        files={"file": (name, data, "text/csv")},
        data={"layout": json.dumps(preview.json()["layout"])},
        headers=h,
    )
    assert result.status_code == 200, result.text
    return preview.json(), result.json()


def test_the_statement_confirms_upi_cheques_and_deposits_and_leaves_the_rest_for_the_owner(client, admin):
    h = bearer(admin)
    outbox = app.dependency_overrides[get_outbox]()
    collector = add_staff(client, admin, "ramesh@shree.example", "collector")
    clerk = add_staff(client, admin, "suresh@shree.example", "register_clerk")
    day = today()

    upi = _receipt(client, clerk, _lr(client, h, st_charges="1000", consignee_name="Upi Buyer"))
    _visit(client, collector, upi, "paid", method="upi", amount="1000", utr="432112345670")
    fake = _receipt(client, clerk, _lr(client, h, st_charges="1000", consignee_name="Fake Upi"))
    _visit(client, collector, fake, "paid", method="upi", amount="1000", utr="999999999999")
    cash = _receipt(client, clerk, _lr(client, h, st_charges="2000", consignee_name="Cash Buyer"))
    _visit(client, collector, cash, "paid", method="cash", amount="2000")
    cheque = _receipt(client, clerk, _lr(client, h, st_charges="3000", consignee_name="Cheque Buyer"))
    _visit(client, collector, cheque, "paid", method="cheque", amount="3000", cheque_number="004512", cheque_bank="SBI")
    held = client.get("/custody/me", headers=bearer(collector)).json()
    cheque_id = next(i["collection_id"] for i in held["items"] if i["kind"] == "cheque")
    client.post("/handovers", json={"from_user_id": _user_id(client, collector), "counted_cash": "2000", "cheque_ids": [cheque_id]}, headers=bearer(clerk))
    deposit = client.post("/deposits", json={"cash_amount": "2000", "cheque_ids": [cheque_id]}, headers=bearer(clerk)).json()
    # a customer who owes Rs 750 pays straight into the bank, unannounced
    transfer_lr = _lr(client, h, st_charges="750", consignee_name="Direct Payer")
    _receipt(client, clerk, transfer_lr, phone="9824000000")

    preview, result = _import(client, h, [*PREAMBLE, HEADER,
        _row(1, day, "UPI/432112345670/FROM UPI BUYER", deposit="1000.00", balance="1000.00"),
        _row(2, day, f"BY CASH {deposit['deposit_number']} RAIPUR", deposit="2000.00", balance="3000.00"),
        _row(3, day, "CLG CHQ 004512 SBI", deposit="3000.00", cheque="004512", balance="6000.00"),
        _row(4, day, "NEFT-HDFC426100001111-DIRECT PAYER", deposit="750.00", balance="6750.00"),
        _row(5, day, "INT.PD", deposit="12.00", balance="6762.00"),
    ])
    assert (preview["remembered"], preview["lines_found"]) == (False, 5)
    assert (result["lines_read"], result["lines_new"], result["matched"], result["unmatched_credits"]) == (5, 5, 3, 2)
    where = lambda receipt: client.get(f"/receipts/{receipt['id']}", headers=h).json()["collections"][0]["custody"]
    assert (where(upi), where(fake), where(cash), where(cheque)) == ("in_bank", "awaiting_bank", "in_bank", "in_bank")
    upi_collection = client.get(f"/receipts/{upi['id']}", headers=h).json()["collections"][0]
    fake_collection = client.get(f"/receipts/{fake['id']}", headers=h).json()["collections"][0]
    assert (upi_collection["status"], fake_collection["status"]) == ("confirmed", "pending")
    assert client.get("/deposits", headers=h).json()[0]["status"] == "banked"

    # importing the same file again adds nothing; the layout is remembered
    preview, again = _import(client, h, [*PREAMBLE, HEADER, _row(1, day, "UPI/432112345670/FROM UPI BUYER", deposit="1000.00", balance="1000.00")])
    assert preview["remembered"] is True and again["lines_new"] == 0

    open_lines = client.get("/bank/lines", params={"status": "unmatched"}, headers=h).json()
    transfer = next(l for l in open_lines if l["credit"] == "750.00")
    interest = next(l for l in open_lines if l["credit"] == "12.00")
    assert client.post(f"/bank/lines/{transfer['id']}/allocate", json={"payer_name": "Nobody"}, headers=h).status_code == 409
    assert client.post(f"/bank/lines/{transfer['id']}/allocate", json={"payer_name": "direct payer"}, headers=bearer(clerk)).status_code == 403
    allocated = client.post(f"/bank/lines/{transfer['id']}/allocate", json={"payer_name": "direct payer"}, headers=h).json()
    assert (allocated["method"], allocated["status"], allocated["custody"]) == ("bank_transfer", "confirmed", "in_bank")
    assert outbox.texts[-1][0] == "9824000000" and "by bank transfer" in outbox.texts[-1][1]
    assert client.get(f"/lrs/{transfer_lr['id']}/account", headers=h).json()["balance"] == "0.00"
    assert all(r["status"] == "settled" for r in client.get("/receipts", headers=h).json() if r["payer_name"] == "Direct Payer")
    assert client.post(f"/bank/lines/{interest['id']}/ignore", json={"note": "Bank interest"}, headers=h).json()["status"] == "ignored"
    assert client.post(f"/bank/lines/{interest['id']}/ignore", json={"note": "again"}, headers=h).status_code == 409

    # every credit is now accounted for; the made-up UTR stays unconfirmed for the owner to see
    overview = client.get("/collections/overview", headers=h).json()
    assert not any(e["kind"] == "credit_unallocated" for e in overview["exceptions"])
    assert (overview["upi_unconfirmed"], overview["banked"]) == ("1000.00", "6750.00")


def test_a_deposit_without_its_number_is_matched_only_when_unambiguous(client, admin):
    h = bearer(admin)
    collector = add_staff(client, admin, "ramesh@shree.example", "collector")
    clerk = add_staff(client, admin, "suresh@shree.example", "register_clerk")
    for name in ("Anil Traders", "Bharat Traders"):
        _visit(client, collector, _receipt(client, clerk, _lr(client, h, st_charges="500", consignee_name=name)), "paid", method="cash", amount="500")
    client.post("/handovers", json={"from_user_id": _user_id(client, collector), "counted_cash": "1000"}, headers=bearer(clerk))
    client.post("/deposits", json={"cash_amount": "1000"}, headers=bearer(clerk))
    _, result = _import(client, h, [*PREAMBLE, HEADER,
        _row(1, today(), "CASH DEPOSIT RAIPUR BR", deposit="1000.00", balance="1000.00"),
        _row(2, today(), "CASH DEPOSIT RAIPUR BR", deposit="1000.00", balance="2000.00"),
    ])
    # two identical credits could each be the deposit: the app does not guess
    assert (result["matched"], result["unmatched_credits"]) == (0, 2)
    line = client.get("/bank/lines", params={"status": "unmatched"}, headers=h).json()[0]
    deposit_id = client.get("/deposits", headers=h).json()[0]["id"]
    matched = client.post(f"/bank/lines/{line['id']}/match", json={"deposit_id": deposit_id}, headers=h).json()
    assert (matched["status"], matched["matched_kind"]) == ("matched", "deposit")
    assert client.get("/deposits", headers=h).json()[0]["status"] == "banked"
    assert client.post(f"/bank/lines/{line['id']}/match", json={"deposit_id": deposit_id}, headers=h).status_code == 409


def test_only_the_owner_imports_statements(client, admin):
    clerk = add_staff(client, admin, "suresh@shree.example", "register_clerk")
    data = _csv([HEADER])
    assert client.post("/bank/statements/preview", files={"file": ("s.csv", data, "text/csv")}, headers=bearer(clerk)).status_code == 403
    bad = client.post("/bank/statements/preview", files={"file": ("s.pdf", b"%PDF", "application/pdf")}, headers=bearer(admin))
    assert bad.status_code == 422 and "CSV, XLS or XLSX" in bad.json()["error"]["message"]
