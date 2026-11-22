"""Every analysis as tables, and tables as Excel or PDF. Excel carries all columns; the PDF carries
the main ones on an A4 page and says so."""

import datetime as dt
import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font
from pydantic import BaseModel

from app.analytics.custom import Table
from app.reports.pdf import build_table_report

# The first columns of each table go on the PDF; the rest are in Excel.
PDF_COLUMNS = 7


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return str(value)
    return value


def tables(name: str, result: BaseModel) -> list[Table]:
    """The analysis as one or more tables, with its basis."""
    basis = getattr(result, "basis", "")

    def from_rows(title: str, rows: list[BaseModel]) -> Table:
        if not rows:
            return Table(title=title, basis=basis, columns=["Nothing in this period"], rows=[])
        fields = list(type(rows[0]).model_fields)
        return Table(
            title=title,
            basis=basis,
            columns=[f.replace("_", " ").capitalize() for f in fields],
            rows=[[_plain(getattr(r, f)) for f in fields] for r in rows],
        )

    if name == "overview":
        return [Table(title="Overview", basis=basis, columns=["Measure", "This period", "Period before", "Change %"],
                      rows=[[k.label, k.value, k.previous, k.change_pct] for k in result.kpis])]
    if name == "trend":
        return [from_rows("Trend", result.points)]
    if name == "customers":
        return [from_rows("Customers", result.rows)]
    if name == "lanes":
        return [from_rows("Lanes", result.rows)]
    if name == "rates":
        return [from_rows("Rates by lane", result.lanes), from_rows("Unusual rates", result.outliers), from_rows("Rate history", result.history)]
    if name == "execution":
        stages = Table(title="Stages", basis=basis, columns=["Stage", "LRs"], rows=[[k.replace("_", " "), v] for k, v in result.stages.items()])
        return [stages, from_rows("Durations", result.durations), from_rows("Pending", result.pending), from_rows("Slower than usual", result.delayed)]
    if name == "fleet":
        return [from_rows("Trucks", result.rows)]
    if name == "finance":
        return [from_rows("Months", [*result.months, result.totals])]
    if name == "branches":
        return [from_rows("Branches", result.rows)]
    if name == "insights":
        return [Table(title="Insights", basis=basis, columns=["Severity", "Insight", "Detail"],
                      rows=[[i.severity, i.title, i.detail] for i in result])]
    if name == "custom":
        return [result]
    if name == "trip_profit":
        return [from_rows("Trips", result.trips), from_rows("By destination", result.by_destination)]
    if name == "vendors":
        return [from_rows("Truck owners", result.rows)]
    if name == "rfqs":
        fields = [k for k in type(result).model_fields if k != "basis"]
        return [Table(title="Quotes", basis=basis, columns=["Measure", "Value"], rows=[[k.replace("_", " ").capitalize(), _plain(getattr(result, k))] for k in fields])]
    if name == "contracts":
        rows = [r.model_copy(update={"off_rate": []}) for r in result.rows]
        off = [o for r in result.rows for o in r.off_rate]
        return [from_rows("Contracts", rows), from_rows("Off-rate LRs", off)]
    raise ValueError(name)


def to_xlsx(company: str, tables_: list[Table]) -> bytes:
    book = Workbook()
    book.remove(book.active)
    for table in tables_:
        sheet = book.create_sheet(table.title[:31])
        sheet.append([f"{company}: {table.title}"])
        sheet["A1"].font = Font(bold=True, size=13)
        sheet.append([table.basis])
        sheet.append([])
        sheet.append(table.columns)
        for cell in sheet[4]:
            cell.font = Font(bold=True)
        for row in table.rows:
            sheet.append([_plain(v) for v in row])
        for i, column in enumerate(table.columns, start=1):
            sheet.column_dimensions[sheet.cell(row=4, column=i).column_letter].width = max(12, min(40, len(column) + 4))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def to_pdf(company: str, table: Table) -> bytes:
    columns = table.columns[:PDF_COLUMNS]
    width = 180 / len(columns)
    notes = [table.basis]
    if len(table.columns) > PDF_COLUMNS:
        notes.append(f"Showing {PDF_COLUMNS} of {len(table.columns)} columns; the Excel export has them all.")
    return build_table_report(
        company_name=company,
        title=table.title,
        subtitle="",
        columns=[(c, width) for c in columns],
        rows=[[_fmt(v) for v in r[:PDF_COLUMNS]] for r in table.rows] or [["Nothing in this period", *[""] * (len(columns) - 1)]],
        notes=notes,
    )
