import io

from pypdf import PdfReader

from tests.conftest import bearer

SAMPLE = {
    "lr_number": "RJT-422692",
    "lr_date": "2026-10-04",
    "from_city": "Rajkot",
    "to_city": "Raipur",
    "freight_by": "ToPay",
    "consignor_name": "Rangoli Laminate",
    "consignor_gstin": "24AABCR4141H1ZQ",
    "consignee_name": "Jalaram Enterprise",
    "consignee_gstin": "22AWCPP8803A1Z0",
    "goods_description": "Lamniate",
    "packages": 2,
    "weight": "100",
    "st_charges": "35",
    "value": "12048",
    "eway_bill_no": "622194022693",
}


def _text(pdf: bytes) -> str:
    return PdfReader(io.BytesIO(pdf)).pages[0].extract_text()


def test_preview_prints_the_form_and_the_values(client, admin):
    response = client.post("/lrs/print-preview", json=SAMPLE, headers=bearer(admin))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    reader = PdfReader(io.BytesIO(response.content))
    assert len(reader.pages) == 1
    width, height = reader.pages[0].mediabox.width, reader.pages[0].mediabox.height
    assert (round(float(width) * 25.4 / 72), round(float(height) * 25.4 / 72)) == (210, 148)
    text = _text(response.content)
    for fixed in ("SHARMA LOGISTICS", "CONSINMENT NOTE", "Consignor", "HAMALI", "ST. CH."):
        assert fixed in text
    for value in ("RJT-422692", "04-10-2026", "RAJKOT", "RANGOLI LAMINATE", "22AWCPP8803A1Z0", "100.00", "12048", "622194022693"):
        assert value in text


def test_total_is_the_sum_of_the_charges(client, admin):
    body = {**SAMPLE, "freight": "1200.5", "hamali": "50", "other_charges": "10", "st_charges": "35"}
    text = _text(client.post("/lrs/print-preview", json=body, headers=bearer(admin)).content)
    assert "1295.50" in text


def test_optional_values_are_left_blank(client, admin):
    body = {k: v for k, v in SAMPLE.items() if k not in ("consignee_gstin", "weight", "value", "eway_bill_no")}
    response = client.post("/lrs/print-preview", json=body, headers=bearer(admin))
    assert response.status_code == 200
    assert "622194022693" not in _text(response.content)


def test_long_names_still_print(client, admin):
    body = {**SAMPLE, "consignor_name": "W" * 60}
    assert client.post("/lrs/print-preview", json=body, headers=bearer(admin)).status_code == 200


def test_bad_values_are_rejected(client, admin):
    for bad in (
        {"consignor_gstin": "123"},
        {"freight_by": "Cash"},
        {"packages": 0},
        {"freight": "-1"},
        {"eway_bill_no": "12345"},
        {"consignor_name": "W" * 61},
    ):
        assert client.post("/lrs/print-preview", json={**SAMPLE, **bad}, headers=bearer(admin)).status_code == 422, bad


def test_preview_needs_sign_in(client):
    assert client.post("/lrs/print-preview", json=SAMPLE).status_code == 401
