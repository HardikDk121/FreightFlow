"""A4 table reports: a company header, a title, a table that flows over as many pages as it needs
(repeating its heading row), optional notes, and "Page x of y" on every page."""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=10.5)
_HEAD = ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=8.5, leading=10.5, textColor=colors.white)
_NOTE = ParagraphStyle("note", fontName="Helvetica", fontSize=9, leading=13)
_INK = colors.HexColor("#1D1D1F")
_RULE = colors.HexColor("#C7C7CC")


def _numbered_canvas(company_name: str, title: str, subtitle: str):
    """A canvas that draws the page header and, once the page count is known, the footer."""

    class NumberedCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for number, state in enumerate(self._pages, start=1):
                self.__dict__.update(state)
                self._decorate(number, total)
                super().showPage()
            super().save()

        def _decorate(self, number: int, total: int) -> None:
            width, height = A4
            self.setFillColor(_INK)
            self.setFont("Helvetica-Bold", 13)
            self.drawString(15 * mm, height - 15 * mm, company_name)
            self.setFont("Helvetica-Bold", 11)
            self.drawRightString(width - 15 * mm, height - 15 * mm, title)
            self.setFont("Helvetica", 8.5)
            self.drawRightString(width - 15 * mm, height - 20 * mm, subtitle)
            self.setStrokeColor(_RULE)
            self.line(15 * mm, height - 23 * mm, width - 15 * mm, height - 23 * mm)
            self.setFont("Helvetica", 8)
            self.drawCentredString(width / 2, 10 * mm, f"Page {number} of {total}")

    return NumberedCanvas


def build_table_report(
    *,
    company_name: str,
    title: str,
    subtitle: str,
    columns: list[tuple[str, float]],
    rows: list[list[str]],
    totals: list[str] | None = None,
    notes: list[str] | None = None,
) -> bytes:
    """`columns` are (heading, width in mm) and should add up to 180. `totals`, when given, is a
    final bold row with one cell per column. `notes` are lines printed under the table."""
    body = [[Paragraph(heading, _HEAD) for heading, _ in columns]]
    body += [[Paragraph(cell, _CELL) for cell in row] for row in rows]
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, _RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if totals is not None:
        body.append([Paragraph(f"<b>{cell}</b>", _CELL) for cell in totals])
        style.append(("LINEABOVE", (0, -1), (-1, -1), 1, _INK))
    table = Table(body, colWidths=[width * mm for _, width in columns], repeatRows=1)
    table.setStyle(TableStyle(style))
    story = [table]
    for note in notes or []:
        story += [Spacer(1, 6 * mm), Paragraph(note, _NOTE)]

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=28 * mm, bottomMargin=18 * mm, title=title
    )
    document.build(story, canvasmaker=_numbered_canvas(company_name, title, subtitle))
    return buffer.getvalue()
