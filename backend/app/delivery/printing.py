"""The gate pass as printed: the layout of the paper pad, one pass per A6 page."""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A6
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from app.delivery.schemas import GatePassRead
from app.models import Branch, Company

_INK = colors.HexColor("#1D2B6B")  # the pad's blue


def gate_pass_pdf(company: Company, branch: Branch, gp: GatePassRead) -> bytes:
    buffer = io.BytesIO()
    width, height = A6
    pdf = Canvas(buffer, pagesize=A6)
    pdf.setTitle(f"Gate pass {gp.gate_pass_number}")
    left, right = 6 * mm, width - 6 * mm
    pdf.setStrokeColor(_INK)
    pdf.setFillColor(_INK)
    pdf.rect(left, 6 * mm, right - left, height - 12 * mm)
    y = height - 11 * mm
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawCentredString(width / 2, y, "GATE - PASS")
    pdf.line(width / 2 - 11 * mm, y - 1 * mm, width / 2 + 11 * mm, y - 1 * mm)
    y -= 6 * mm
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawCentredString(width / 2, y, company.name.upper())
    pdf.setFont("Helvetica", 6.3)
    for line in (branch.address or "").splitlines()[:2]:
        y -= 3.2 * mm
        pdf.drawCentredString(width / 2, y, line)
    if branch.phone:
        y -= 3.2 * mm
        pdf.drawCentredString(width / 2, y, f"Mo.: {branch.phone}")
    if company.gstin:
        y -= 3.2 * mm
        pdf.setFont("Helvetica-Bold", 6.3)
        pdf.drawCentredString(width / 2, y, f"GSTIN : {company.gstin}")
    y -= 6 * mm
    pdf.setFont("Helvetica", 7.5)
    pdf.drawString(left + 2 * mm, y, f"Date  {gp.issued_at:%d-%m-%Y}")
    pdf.drawString(width / 2 + 4 * mm, y, "No. :")
    pdf.setFillColor(colors.HexColor("#B3261E"))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(right - 3 * mm, y, gp.gate_pass_number)
    pdf.setFillColor(_INK)
    y -= 6 * mm
    pdf.setFont("Helvetica", 7.5)
    pdf.drawString(left + 2 * mm, y, "M/s.")
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(left + 10 * mm, y, gp.consignee_name.upper()[:40])
    pdf.line(left + 9 * mm, y - 1 * mm, right - 2 * mm, y - 1 * mm)

    # The table: CN No. | No. of Packages | Payments
    top = y - 4 * mm
    c1, c2 = left + 40 * mm, left + 63 * mm
    pdf.line(left, top, right, top)
    pdf.setFont("Helvetica", 7)
    pdf.drawCentredString((left + c1) / 2, top - 4.5 * mm, "CN No.")
    pdf.drawCentredString((c1 + c2) / 2, top - 3.2 * mm, "No. of")
    pdf.drawCentredString((c1 + c2) / 2, top - 6 * mm, "Packages")
    pdf.drawCentredString((c2 + right) / 2, top - 4.5 * mm, "Payments")
    header_bottom = top - 8 * mm
    pdf.line(left, header_bottom, right, header_bottom)
    table_bottom = 22 * mm
    pdf.line(c1, top, c1, table_bottom)
    pdf.line(c2, top, c2, table_bottom)
    row = header_bottom - 4.5 * mm
    pdf.setFont("Helvetica", 7.5)
    for line in gp.lines[:12]:
        pdf.drawString(left + 2 * mm, row, line.lr_number)
        pdf.drawCentredString((c1 + c2) / 2, row, str(line.packages))
        pdf.drawCentredString((c2 + right) / 2, row, line.payment)
        row -= 4.5 * mm
    pdf.setFont("Helvetica", 7)
    pdf.drawString(left + 2 * mm, table_bottom + 7 * mm, f"Auto No.: {gp.auto_no or ''}")
    pdf.drawString(left + 2 * mm, table_bottom + 2.5 * mm, f"Driver Name  {gp.driver_name or ''}")
    pdf.line(left, table_bottom, right, table_bottom)
    if gp.receiver_name:
        pdf.setFont("Helvetica", 6)
        pdf.drawString(left + 2 * mm, 10 * mm, f"Received by {gp.receiver_name} on {gp.delivered_at:%d-%m-%Y %H:%M}")
    pdf.setFont("Helvetica", 7)
    pdf.drawRightString(right - 2 * mm, 8 * mm, "Signature")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
