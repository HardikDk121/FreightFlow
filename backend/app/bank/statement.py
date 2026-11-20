"""Reading a bank statement download (CSV, XLS or XLSX) into lines. Pure functions: no database.

Banks put a few lines of account details above the table and name columns differently, so the
header row and the columns are found by name. Whatever is found is shown to the owner before
anything is saved, and can be corrected; the corrected layout is remembered for next time.
"""

import csv
import datetime as dt
import hashlib
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# Column names as banks print them, most specific first. Matching is on lower-case words.
_NAMES = {
    "date": ("transaction date", "txn date", "tran date", "txn posted date", "posted date", "posting date", "date", "value date"),
    "narration": ("transaction remarks", "remarks", "narration", "description", "particulars", "details"),
    "reference": ("transaction id", "tran id", "utr", "ref no", "reference", "chq / ref", "chq/ref", "cheque number", "cheque no"),
    "credit": ("deposit amount", "deposit amt", "deposits", "credit amount", "credit amt", "credit", "cr amount"),
    "debit": ("withdrawal amount", "withdrawal amt", "withdrawals", "debit amount", "debit amt", "debit", "dr amount"),
    "amount": ("transaction amount", "txn amount", "amount"),
    "drcr": ("cr/dr", "dr/cr", "cr / dr", "dr / cr", "type"),
    "balance": ("available balance", "closing balance", "balance"),
}

_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%Y-%m-%d", "%d.%m.%Y")

# UPI and IMPS carry a 12-digit RRN; NEFT and RTGS a UTR of 16 or 22 characters starting with a bank code.
_REF_PATTERNS = (
    re.compile(r"(?<![0-9A-Z])[0-9]{12}(?![0-9A-Z])"),
    re.compile(r"(?<![0-9A-Z])[A-Z]{4}[A-Z0-9]{12}(?:[A-Z0-9]{6})?(?![0-9A-Z])"),
)


class StatementError(Exception):
    """The file cannot be read as a statement; the message says what to do."""


@dataclass(frozen=True)
class Line:
    txn_date: dt.date
    narration: str
    reference: str | None
    credit: Decimal
    debit: Decimal
    balance: Decimal | None
    refs: str
    row_hash: str


def read_rows(data: bytes, file_name: str) -> list[list[str]]:
    """Every row of the first sheet, as text cells."""
    name = file_name.lower()
    if name.endswith(".xlsx"):
        import openpyxl

        try:
            sheet = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
        except Exception as exc:
            raise StatementError("This XLSX file could not be opened.") from exc
        return [[_cell(v) for v in row] for row in sheet.iter_rows(values_only=True)]
    if name.endswith(".xls"):
        import xlrd

        try:
            book = xlrd.open_workbook(file_contents=data)
        except Exception as exc:
            raise StatementError("This XLS file could not be opened. Download it again, or as CSV.") from exc
        sheet = book.sheet_by_index(0)
        rows = []
        for r in range(sheet.nrows):
            cells = []
            for c in range(sheet.ncols):
                cell = sheet.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    cells.append(xlrd.xldate_as_datetime(cell.value, book.datemode).strftime("%d/%m/%Y"))
                else:
                    cells.append(_cell(cell.value))
            rows.append(cells)
        return rows
    if name.endswith(".csv") or name.endswith(".txt"):
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise StatementError("This CSV file has an unknown text encoding.")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), dialect)]
    raise StatementError("Upload the statement as CSV, XLS or XLSX.")


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime | dt.date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _norm(header: str) -> str:
    return re.sub(r"[^a-z/ ]", "", header.lower().replace("\n", " ")).strip()


def detect(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """The header row and which column holds each field. Looks in the first 40 rows for the row that
    names a date and either credit/debit columns or an amount column."""
    best: tuple[int, int, dict[str, int]] | None = None
    for index, row in enumerate(rows[:40]):
        headers = [_norm(h) for h in row]
        mapping: dict[str, int] = {}
        for field, names in _NAMES.items():
            for name in names:
                column = next((i for i, h in enumerate(headers) if h == name or h.startswith(name + " ")), None)
                if column is not None and column not in mapping.values():
                    mapping[field] = column
                    break
        usable = "date" in mapping and "narration" in mapping and ("credit" in mapping or ("amount" in mapping and "drcr" in mapping))
        if usable and (best is None or len(mapping) > best[1]):
            best = (index, len(mapping), mapping)
    if best is None:
        raise StatementError(
            "Could not find the table in this file. Choose the columns for date, narration and credit yourself."
        )
    mapping = best[2]
    if "credit" in mapping:
        mapping.pop("amount", None)
        mapping.pop("drcr", None)
    return best[0], mapping


def _date(text: str) -> dt.date | None:
    text = text.strip().split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2} ", text.strip()) else text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _money(text: str) -> Decimal | None:
    cleaned = text.replace(",", "").replace("₹", "").replace("INR", "").strip()
    cleaned = re.sub(r"\s*(CR|DR|Cr|Dr)\.?$", "", cleaned)
    if cleaned in ("", "-"):
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    try:
        value = Decimal(cleaned.strip("()"))
    except InvalidOperation:
        return None
    return -value if negative else value


def references(*texts: str | None) -> str:
    """Reference numbers in the text, space-separated, for matching UPI UTRs and NEFT/RTGS UTRs."""
    found: list[str] = []
    for text in texts:
        if not text:
            continue
        upper = text.upper()
        for pattern in _REF_PATTERNS:
            for match in pattern.findall(upper):
                if match not in found:
                    found.append(match)
    return " ".join(found)


def parse(rows: list[list[str]], header_row: int, mapping: dict[str, int]) -> tuple[list[Line], list[str]]:
    """The statement lines, and a note for each row that looked like a transaction but could not be read."""
    for field in ("date", "narration"):
        if field not in mapping:
            raise StatementError(f"Choose the column for {field}.")
    if "credit" not in mapping and not ("amount" in mapping and "drcr" in mapping):
        raise StatementError("Choose the credit column, or the amount and the Cr/Dr columns.")

    def cell(row: list[str], field: str) -> str:
        column = mapping.get(field)
        return row[column] if column is not None and column < len(row) else ""

    lines: list[Line] = []
    problems: list[str] = []
    seen: dict[str, int] = {}
    for number, row in enumerate(rows[header_row + 1 :], start=header_row + 2):
        if not any(c.strip() for c in row):
            continue
        day = _date(cell(row, "date"))
        if day is None:
            # Footer rows ("Opening balance", totals) have no date; anything with an amount is reported.
            if any(_money(cell(row, f)) for f in ("credit", "debit", "amount")):
                problems.append(f"Row {number}: no readable date, skipped.")
            continue
        if "credit" in mapping:
            credit = _money(cell(row, "credit")) or Decimal(0)
            debit = _money(cell(row, "debit")) or Decimal(0)
        else:
            amount = _money(cell(row, "amount")) or Decimal(0)
            is_credit = cell(row, "drcr").strip().upper().startswith("C")
            credit, debit = (amount, Decimal(0)) if is_credit else (Decimal(0), amount)
        if credit < 0 or debit < 0:
            problems.append(f"Row {number}: a negative amount, skipped.")
            continue
        if credit == 0 and debit == 0:
            continue
        narration = cell(row, "narration")
        reference = cell(row, "reference") or None
        balance = _money(cell(row, "balance"))
        key = "|".join((day.isoformat(), narration, reference or "", str(credit), str(debit), str(balance)))
        # Two identical lines on one day (same payer, same amount, no balance column) are both kept.
        seen[key] = seen.get(key, 0) + 1
        row_hash = hashlib.sha256(f"{key}#{seen[key]}".encode()).hexdigest()
        lines.append(
            Line(
                txn_date=day,
                narration=narration,
                reference=reference,
                credit=credit,
                debit=debit,
                balance=balance,
                refs=references(narration, reference),
                row_hash=row_hash,
            )
        )
    if not lines:
        raise StatementError("No transactions were found under the header row. Check the columns chosen.")
    return lines, problems
