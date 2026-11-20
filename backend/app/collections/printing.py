"""The printed money receipt, laid out like the paper pad, with the company's bank details and a
verification QR added at the foot; and the public page that QR opens."""

import html
import io
from decimal import Decimal

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from app.collections.schemas import ReceiptRead, ReceiptVerification
from app.models import Branch, Company

_INK = colors.HexColor("#1D2B6B")  # the pad's blue
_MUTED = colors.HexColor("#5A6180")


def _rs(amount: Decimal) -> tuple[str, str]:
    """Rupees and paise in separate columns, as on the pad."""
    whole, paise = f"{amount:.2f}".split(".")
    return f"{int(whole):,}", paise


def receipt_pdf(company: Company, branch: Branch, receipt: ReceiptRead, verify_url: str) -> bytes:
    buffer = io.BytesIO()
    width, height = A5
    pdf = Canvas(buffer, pagesize=A5)
    pdf.setTitle(f"Money receipt {receipt.receipt_number}")
    left, right = 10 * mm, width - 10 * mm
    pdf.setStrokeColor(_INK)
    pdf.setFillColor(_INK)

    # Header, as printed on the pad: company, the branch's address and phone, GSTIN.
    y = height - 16 * mm
    pdf.setFont("Helvetica-Bold", 17)
    pdf.drawCentredString(width / 2, y, company.name.upper())
    pdf.setFont("Helvetica", 7.5)
    for line in (branch.address or company.address or "").splitlines()[:2]:
        y -= 3.8 * mm
        pdf.drawCentredString(width / 2, y, line)
    if branch.phone:
        y -= 3.8 * mm
        pdf.drawCentredString(width / 2, y, f"Mo.: {branch.phone}")
    if company.gstin:
        y -= 4 * mm
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawCentredString(width / 2, y, f"GSTIN : {company.gstin}")
    y -= 8 * mm
    pdf.setFont("Helvetica", 9)
    pdf.drawString(left, y, f"Date  {receipt.issued_at:%d-%m-%Y}")
    pdf.drawString(width / 2 + 15 * mm, y, "No.")
    pdf.setFillColor(colors.HexColor("#B3261E"))
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawRightString(right, y, receipt.receipt_number)
    pdf.setFillColor(_INK)
    y -= 7 * mm
    pdf.setFont("Helvetica", 9)
    pdf.drawString(left, y, "M/s.")
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left + 9 * mm, y, receipt.payer_name.upper()[:46])
    pdf.line(left + 8 * mm, y - 1.2 * mm, right, y - 1.2 * mm)

    # The body: consignment details on the left, particulars on the right.
    top = y - 5 * mm
    row_h = 6.5 * mm
    mid, rupee_col = left + 48 * mm, right - 14 * mm
    first = receipt.lines[0]
    one = len(receipt.lines) == 1
    left_rows = [
        ("G.R.No.", first.lr_number if one else ", ".join(l.lr_number for l in receipt.lines)),
        ("Date", first.lr_date.strftime("%d-%m-%Y") if one else ""),
        ("From", first.from_city),
        ("Serial No.", ""),
        ("No. of Pkgs", str(sum(l.packages for l in receipt.lines))),
        ("Weight", f"{sum((l.weight or 0) for l in receipt.lines):,.0f}" if any(l.weight for l in receipt.lines) else ""),
        ("Through", ""),
    ]
    total = lambda field: sum((getattr(l, field) for l in receipt.lines), Decimal(0))  # noqa: E731
    right_rows = [
        ("Particulars", None),
        ("Freight", total("freight")),
        ("", None),
        ("Labour", total("labour")),
        ("DC Charge", total("dc_charge")),
        ("Demurrage", total("demurrage")),
        ("ST Charge", total("st_charge")),
        ("TOTAL", receipt.amount),
    ]
    bottom = top - row_h * len(right_rows)
    pdf.rect(left, bottom, right - left, top - bottom)
    pdf.line(mid, top, mid, bottom)
    pdf.line(rupee_col, top, rupee_col, bottom)
    for i in range(1, len(right_rows)):
        yy = top - row_h * i
        pdf.line(mid, yy, right, yy)
        if i < len(left_rows) + 1:
            pdf.line(left, yy, mid, yy)
    for i, (label, value) in enumerate(left_rows):
        yy = top - row_h * (i + 1) + 2 * mm
        pdf.setFont("Helvetica", 8.5)
        pdf.drawString(left + 1.5 * mm, yy, label)
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.drawString(left + 21 * mm, yy, value[:26])
    for i, (label, amount) in enumerate(right_rows):
        yy = top - row_h * (i + 1) + 2 * mm
        pdf.setFont("Helvetica-Bold" if label in ("Particulars", "TOTAL") else "Helvetica", 8.5)
        pdf.drawString(mid + 1.5 * mm, yy, label)
        if label == "Particulars":
            pdf.drawCentredString((mid + 48 * mm + rupee_col) / 2, yy, "Rs.")
            pdf.drawCentredString((rupee_col + right) / 2, yy, "P.")
        elif amount is not None and (amount > 0 or label == "TOTAL"):
            rupees, paise = _rs(amount)
            pdf.drawRightString(rupee_col - 1.5 * mm, yy, rupees)
            pdf.drawCentredString((rupee_col + right) / 2, yy, paise)
    pdf.setFont("Helvetica", 8.5)
    pdf.drawString(left, bottom - 6 * mm, "Sign. of Consignor")
    pdf.drawRightString(right, bottom - 6 * mm, "Delivery Clerk")

    # Added below the pad's layout: where to pay, and how to check this receipt is genuine.
    qr_size = 28 * mm
    widget = QrCodeWidget(verify_url)
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(qr_size, qr_size, transform=[qr_size / (x1 - x0), 0, 0, qr_size / (y1 - y0), 0, 0])
    drawing.add(widget)
    qr_y = 16 * mm
    renderPDF.draw(drawing, pdf, right - qr_size, qr_y)
    pdf.setFont("Helvetica", 6.5)
    pdf.setFillColor(_MUTED)
    pdf.drawCentredString(right - qr_size / 2, qr_y - 3 * mm, "Scan to check this receipt")
    text_y = qr_y + qr_size - 2 * mm
    pdf.setFillColor(_INK)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(left, text_y, "Pay only into our company account:")
    pdf.setFont("Helvetica", 8)
    for line in (company.bank_details or "Bank details not set. Ask the office.").splitlines():
        text_y -= 4 * mm
        pdf.drawString(left, text_y, line)
    text_y -= 5.5 * mm
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawString(left, text_y, "Never pay into a staff member's personal account or UPI.")
    pdf.setFont("Helvetica", 7)
    pdf.setFillColor(_MUTED)
    text_y -= 3.6 * mm
    pdf.drawString(left, text_y, "You get an SMS or WhatsApp for every payment recorded.")
    if company.phone:
        text_y -= 3.4 * mm
        pdf.drawString(left, text_y, f"If it does not match what you paid, call {company.phone}.")
    pdf.drawString(left, 8 * mm, f"Issued by {receipt.issued_by}. Valid only if the QR shows this receipt.")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def verification_page(found: ReceiptVerification | None) -> str:
    """A plain page for a phone's browser. Escapes everything it shows."""
    if found is None:
        body = "<h1>Receipt not found</h1><p>This QR does not match any receipt. Do not pay against it.</p>"
    else:
        e = html.escape
        status = {"open": "Not yet fully paid", "settled": "Paid in full", "cancelled": "Cancelled: do not pay"}[found.status]
        body = (
            f"<p class=muted>{e(found.company_name)}</p>"
            f"<h1>{e(found.receipt_number)}</h1>"
            f"<p><b>{e(status)}</b></p>"
            f"<p>Payable by {e(found.payer_name)}<br>LR {e(', '.join(found.lr_numbers))}<br>"
            f"Issued {found.issued_on:%d-%m-%Y}</p>"
            f"<p>Amount Rs {found.amount:,.2f}<br>Recorded as paid Rs {found.collected:,.2f}</p>"
        )
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width, initial-scale=1'>"
        "<title>Receipt check</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:24px;color:#14141A;line-height:1.5}"
        ".muted{color:#6B6B76}h1{margin:4px 0}</style>"
        f"<body>{body}</body></html>"
    )
