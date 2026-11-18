import base64
import json
from decimal import Decimal

import cv2
import numpy as np

from app.scan.extractor import extract_fields, parse_einvoice_qr
from tests.conftest import add_staff, bearer

# Invented invoice text, laid out the way OCR returns a typical GST tax invoice.
INVOICE_TEXT = """
E Way Bill No :- 712345678901
Tax Invoice
GSTIN No. 24AAACK1234L1Z5
Details of Receiver (Buyer Detail) INVOICE NO. GST/2627-0042
KAVERI TRADERS
GSTIN NO: 27AABCK9999M1Z3
Details of Consignee (Shipped Detail) Transport Name : SHARMA LOGISTICS
SUNRISE PLY HOUSE : ;
14 MARKET ROAD
NAGPUR-440001 Maharashtra
GSTIN NO.: 27AAECS4321P1Z8 PAN NO.: AAECS4321P
DECORATIVE LAMINATE SHEET
48239019 GLOSS FINISH 1 MM 12 Nos 755.00 9,060.00
Sub Total : 9,060.00
Grand Total : 10,690.80
For, KRISHNA LAMINATES PVT LTD
"""


def _qr_token(data: dict) -> str:
    part = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{part({'alg': 'RS256'})}.{part({'data': json.dumps(data), 'iss': 'NIC'})}.signature"


def test_rules_read_an_invoice():
    scan = extract_fields(INVOICE_TEXT, {}, own_gstin=None)
    assert scan.model_dump() == {
        "consignor_name": "KRISHNA LAMINATES PVT LTD",
        "consignor_gstin": "24AAACK1234L1Z5",
        "consignee_name": "SUNRISE PLY HOUSE",
        "consignee_gstin": "27AAECS4321P1Z8",
        "to_city": "NAGPUR",
        "goods_description": "DECORATIVE LAMINATE SHEET",
        "value": Decimal("10690.80"),
        "eway_bill_no": "712345678901",
        "hsn_code": "48239019",
    }


def test_qr_values_win_and_the_transporters_gstin_is_ignored():
    qr = parse_einvoice_qr(_qr_token({"SellerGstin": "24AAACQ0000R1Z9", "BuyerGstin": "27AABCK9999M1Z3", "TotInvVal": 10691}))
    scan = extract_fields(INVOICE_TEXT + "\nTransporter GSTIN 24CPAPS7855E2ZO", qr, own_gstin="24CPAPS7855E2ZO")
    assert scan.consignor_gstin == "24AAACQ0000R1Z9" and scan.value == Decimal("10691.00")
    assert scan.consignee_gstin == "27AAECS4321P1Z8"
    assert parse_einvoice_qr("") == {} and parse_einvoice_qr("a.b.c") == {} and parse_einvoice_qr("plain text") == {}


def test_unreadable_text_gives_blanks_not_guesses():
    assert all(v is None for v in extract_fields("smudge ~~ 123", {}, None).model_dump().values())


def _photo() -> bytes:
    lines = ["E Way Bill No :- 712345678901", "Tax Invoice", "Details of Consignee", "SUNRISE PLY HOUSE", "NAGPUR-440001", "Grand Total : 10,690.80"]
    image = np.full((90 * len(lines) + 60, 1400, 3), 255, np.uint8)
    for i, line in enumerate(lines):
        cv2.putText(image, line, (40, 90 * (i + 1)), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3, cv2.LINE_AA)
    return cv2.imencode(".png", image)[1].tobytes()


def test_scan_endpoint_reads_a_photo(client, admin):
    response = client.post("/invoices/scan", files={"file": ("invoice.png", _photo(), "image/png")}, headers=bearer(admin))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eway_bill_no"] == "712345678901" and body["value"] == "10690.80"
    assert body["consignee_name"] == "SUNRISE PLY HOUSE" and body["to_city"] == "NAGPUR"


def test_scan_endpoint_rejects_bad_input(client, admin):
    h = bearer(admin)
    assert client.post("/invoices/scan", files={"file": ("x.txt", b"not an image", "text/plain")}, headers=h).status_code == 422
    dispatcher = add_staff(client, admin, "d@shree.example", "dispatcher")
    assert client.post("/invoices/scan", files={"file": ("i.png", _photo(), "image/png")}, headers=bearer(dispatcher)).status_code == 403
