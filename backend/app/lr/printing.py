"""Draws the LR as a PDF from lr_template.json: the fixed form (borders, header, labels)
plus the values in their boxes. The template is the only place positions live."""

import io
import json
from decimal import Decimal
from functools import cache
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from app.lr.schemas import LrPrintData
from app.models import Company

_TEMPLATE_PATH = Path(__file__).with_name("lr_template.json")
_MIN_FONT_SIZE = 5.0


@cache
def load_template() -> dict:
    return json.loads(_TEMPLATE_PATH.read_text(encoding="utf-8"))


def _amount(value: Decimal) -> str:
    return f"{value:.2f}"


def _plain_number(value: Decimal) -> str:
    """12048 -> "12048", 12048.5 -> "12048.50"."""
    return f"{value:.0f}" if value == value.to_integral_value() else f"{value:.2f}"


# The three paper copies, named by the colour of their paper, with a band of that colour printed
# beside the label so a copy printed on plain paper can still be told apart.
# Yellow goes to the sender who brings the goods to the godown; white and pink are stapled to the
# LR and travel with the goods to the destination.
COPIES = {
    "yellow": ("YELLOW COPY · CONSIGNOR", (0.96, 0.78, 0.0)),
    "white": ("WHITE COPY · WITH GOODS", None),
    "pink": ("PINK COPY · WITH GOODS", (0.96, 0.56, 0.69)),
}


def header_fields(company: Company) -> dict[str, str]:
    """The company block at the top of the LR, from the company's own settings."""
    address = [line.upper() for line in (company.address or "").splitlines()][:3]
    address += [""] * (3 - len(address))
    return {
        "company_name": company.name.upper(),
        "company_tagline": (company.tagline or "").upper(),
        "company_address_1": address[0],
        "company_address_2": address[1],
        "company_address_3": address[2],
        "company_gstin": f"GSTIN: {company.gstin}" if company.gstin else "",
        "company_contact": f"Contact No: {company.phone}" if company.phone else "",
    }


def format_fields(lr: LrPrintData) -> dict[str, str]:
    """The text that goes in each field box, formatted the way the paper LR shows it."""
    return {
        "lr_number": lr.lr_number,
        "lr_date": lr.lr_date.strftime("%d-%m-%Y"),
        "from_city": lr.from_city.upper(),
        "to_city": lr.to_city.upper(),
        "freight_by": lr.freight_by,
        "consignor_name": lr.consignor_name.upper(),
        "consignor_gstin": lr.consignor_gstin or "",
        "consignee_name": lr.consignee_name.upper(),
        "consignee_gstin": lr.consignee_gstin or "",
        "goods_description": lr.goods_description.upper(),
        "packages": str(lr.packages),
        "weight": _amount(lr.weight) if lr.weight is not None else "",
        "charged_weight": _amount(lr.charged_weight) if lr.charged_weight is not None else "",
        # The unit tells the reader how the freight was worked out.
        "rate": (
            f"{_amount(lr.rate)}/{ {'per_kg': 'KG', 'per_article': 'ART'}[lr.charge_basis] }"
            if lr.charge_basis in ("per_kg", "per_article") and lr.rate > 0
            else (_amount(lr.rate) if lr.rate > 0 else "")
        ),
        "freight": _amount(lr.freight),
        "hamali": _amount(lr.hamali),
        "other_charges": _amount(lr.other_charges),
        "st_charges": _amount(lr.st_charges),
        "total": _amount(lr.freight + lr.hamali + lr.other_charges + lr.st_charges),
        "value": _plain_number(lr.value) if lr.value is not None else "",
        "eway_bill_no": lr.eway_bill_no or "",
    }


def _fit_size(text: str, font: str, size: float, max_width_mm: float | None) -> float:
    """Shrink the font until the text fits its box. Schema length limits keep this above the minimum."""
    if max_width_mm is None:
        return size
    width = stringWidth(text, font, size)
    return size if width <= max_width_mm * mm else max(_MIN_FONT_SIZE, size * max_width_mm * mm / width)


def render_lr_pdf(lr: LrPrintData, company: Company, copies: list[str | None]) -> bytes:
    """One page per entry in `copies` (keys of COPIES), each a full LR. None prints an unlabelled page."""
    template = load_template()
    page_w = template["page"]["width_mm"] * mm
    page_h = template["page"]["height_mm"] * mm
    dx = template["printer_offset_mm"]["x"]
    dy = template["printer_offset_mm"]["y"]

    def px(x_mm: float) -> float:
        return (x_mm + dx) * mm

    def py(y_mm: float) -> float:
        # The template measures down from the top; PDF measures up from the bottom.
        return page_h - (y_mm + dy) * mm

    def draw_text(text: str, spec: dict, size: float) -> None:
        canvas.setFont(spec["font"], size)
        x, y = px(spec["x"]), py(spec["y"])
        align = spec.get("align", "left")
        if align == "center":
            canvas.drawCentredString(x, y, text)
        elif align == "right":
            canvas.drawRightString(x, y, text)
        else:
            canvas.drawString(x, y, text)
        if spec.get("underline") and text:
            width = stringWidth(text, spec["font"], size)
            start = {"center": x - width / 2, "right": x - width}.get(align, x)
            canvas.setLineWidth(0.5)
            canvas.line(start, y - 0.6 * mm, start + width, y - 0.6 * mm)
            canvas.setLineWidth(template["line_width_pt"])

    values = format_fields(lr) | header_fields(company)
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=(page_w, page_h))
    canvas.setTitle(f"LR {lr.lr_number}")
    for copy in copies:
        copy_label, colour = COPIES[copy] if copy else ("", None)
        canvas.setLineWidth(template["line_width_pt"])
        for x, y, w, h in template["rects"]:
            canvas.rect(px(x), py(y + h), w * mm, h * mm)
        for x1, y1, x2, y2 in template["lines"]:
            canvas.line(px(x1), py(y1), px(x2), py(y2))
        for spec in template["texts"]:
            draw_text(spec["text"], spec, spec["size"])
        for spec in template["fields"]:
            text = copy_label if spec["field"] == "copy_label" else values[spec["field"]]
            draw_text(text, spec, _fit_size(text, spec["font"], spec["size"], spec.get("max_width_mm")))
            if spec["field"] == "copy_label" and copy_label:
                # A small swatch before the label: filled in the copy's colour, outlined for white.
                canvas.saveState()
                if colour is not None:
                    canvas.setFillColorRGB(*colour)
                canvas.rect(px(spec["x"] - 5), py(spec["y"]) - 0.4 * mm, 3.6 * mm, 2.6 * mm, stroke=1, fill=1 if colour else 0)
                canvas.restoreState()
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()
