"""Reads LR fields from a photo of a tax invoice.

Two sources, in order of trust:
1. The GST e-invoice QR code, when the photo is sharp enough to decode it: exact GSTINs and total.
2. OCR text and layout rules, for names, city, goods and anything the QR did not give.

`extract_fields` works on text alone, so the rules are testable without images.
"""

import base64
import binascii
import json
import re
from decimal import Decimal, InvalidOperation

import cv2
import numpy as np
import pytesseract

from app.scan.schemas import InvoiceScan

_GSTIN = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
_EWAY = re.compile(r"E[\s-]*Way\s*Bill\s*No\.?[\s:\-–.]*([0-9]{12})\b", re.IGNORECASE)
_GRAND_TOTAL = re.compile(r"Grand\s*Total[\s:.\-]*(?:Rs\.?|INR|₹)?\s*([0-9][0-9,]*\.[0-9]{2})", re.IGNORECASE)
_CITY_PIN = re.compile(r"\b([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)?)\s*[-–]\s*[0-9]{6}\b")
_SIGNED_FOR = re.compile(r"\bFor,?\s+([A-Z][A-Z0-9 &.'\-]{3,})")
_HSN_ROW = re.compile(r"\b[0-9]{8}\b")
_NAME = re.compile(r"[A-Z][A-Z0-9 &.'\-]*[A-Z0-9.]")
_BUYER_SECTION = re.compile(r"receiver|buyer|billed|bill to|consignee|shipped|ship to", re.IGNORECASE)
_CONSIGNEE_SECTION = re.compile(r"consignee|shipped|ship to", re.IGNORECASE)


class UnreadableImage(Exception):
    pass


def scan_invoice(image_bytes: bytes, own_gstin: str | None) -> InvoiceScan:
    image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise UnreadableImage
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Phone photos are small for OCR; doubling the size makes thin print readable.
    enlarged = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    text = pytesseract.image_to_string(enlarged, config="--psm 6")
    qr_text, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
    return extract_fields(text, parse_einvoice_qr(qr_text), own_gstin)


def parse_einvoice_qr(qr_text: str) -> dict:
    """The data inside a GST e-invoice QR code: a signed token whose middle part is JSON.
    Returns {} for anything else, including no QR at all."""
    parts = qr_text.split(".")
    if len(parts) != 3:
        return {}
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        data = payload["data"]
        return json.loads(data) if isinstance(data, str) else data
    except (binascii.Error, ValueError, KeyError, TypeError):
        return {}


def _clean_name(line: str, limit: int) -> str | None:
    match = _NAME.search(line.upper())
    if match is None or len(match.group()) < 3:
        return None
    return match.group().strip(" .-")[:limit].strip() or None


def _amount(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        return Decimal(str(text).replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _qr_gstin(qr: dict, key: str) -> str | None:
    value = qr.get(key)
    return value if isinstance(value, str) and _GSTIN.fullmatch(value) else None


def extract_fields(text: str, qr: dict, own_gstin: str | None) -> InvoiceScan:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first_buyer = next((i for i, line in enumerate(lines) if _BUYER_SECTION.search(line)), len(lines))
    consignee_at = next((i for i, line in enumerate(lines) if _CONSIGNEE_SECTION.search(line)), None)
    consignee_block = lines[consignee_at + 1 :] if consignee_at is not None else []

    def gstins(block: list[str]) -> list[str]:
        found = [g for line in block for g in _GSTIN.findall(line.upper())]
        return [g for g in found if g != own_gstin]

    # The supplier's GSTIN is printed above the buyer's details; the consignee's below its heading.
    seller = _qr_gstin(qr, "SellerGstin") or next(iter(gstins(lines[:first_buyer])), None)
    buyer_side = [g for g in gstins(consignee_block or lines[first_buyer:]) if g != seller]
    consignee_gstin = next(iter(buyer_side), None) or _qr_gstin(qr, "BuyerGstin")

    signed = next((m.group(1) for line in lines if (m := _SIGNED_FOR.search(line))), None)
    city = next((m.group(1) for line in consignee_block if (m := _CITY_PIN.search(line))), None)
    eway = _EWAY.search(text)
    total = _GRAND_TOTAL.search(text)

    # Goods: the line above the first row carrying an HSN code, or the words in that row.
    description = None
    hsn_at = next((i for i, line in enumerate(lines) if _HSN_ROW.search(line)), None)
    if hsn_at is not None:
        above = lines[hsn_at - 1] if hsn_at > 0 else ""
        if above and not re.search(r"[0-9]", above):
            description = _clean_name(above, 50)
        if description is None:
            words = re.sub(r"[^A-Za-z ]", " ", lines[hsn_at])
            description = _clean_name(" ".join(words.split()), 50)

    return InvoiceScan(
        consignor_name=_clean_name(signed, 60) if signed else None,
        consignor_gstin=seller,
        consignee_name=_clean_name(consignee_block[0], 60) if consignee_block else None,
        consignee_gstin=consignee_gstin,
        to_city=city.upper()[:30] if city else None,
        goods_description=description,
        value=_amount(qr.get("TotInvVal")) or _amount(total.group(1) if total else None),
        eway_bill_no=eway.group(1) if eway else None,
    )
