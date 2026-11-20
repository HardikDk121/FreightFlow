"""The bank statement as the independent record of what reached the company."""

import datetime as dt
import re
import uuid
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import audit
from app.bank import statement
from app.collections import service as collections
from app.collections.schemas import CollectionRead
from app.errors import AppError, conflict, not_found
from app.models import BankDeposit, BankImport, BankStatementLine, CashHandover, Collection, StatementFormat, User
from app.notify import Outbox
from app.security import utcnow

# A cash deposit appears on the statement within this many days of being made.
DEPOSIT_WINDOW_DAYS = 3


class Layout(BaseModel):
    header_row: int
    headers: list[str]
    mapping: dict[str, int]


class SampleLine(BaseModel):
    txn_date: dt.date
    narration: str
    reference: str | None
    credit: Decimal
    debit: Decimal
    refs: str


class Preview(BaseModel):
    layout: Layout
    lines_found: int
    sample: list[SampleLine]
    problems: list[str]
    # True when the layout came from the last import rather than being guessed.
    remembered: bool


class ImportResult(BaseModel):
    lines_read: int
    lines_new: int
    matched: int
    unmatched_credits: int
    problems: list[str]


class LineRead(BaseModel):
    id: uuid.UUID
    txn_date: dt.date
    narration: str
    reference: str | None
    credit: Decimal
    debit: Decimal
    status: str
    matched_kind: str | None
    note: str | None


def _bad(exc: statement.StatementError) -> AppError:
    return AppError(422, "bad_statement", str(exc))


def _layout(session: Session, rows: list[list[str]]) -> tuple[Layout, bool]:
    # Row-level security limits this to the current company's one row.
    saved = session.scalar(select(StatementFormat))
    if saved is not None:
        layout = Layout.model_validate(saved.columns)
        if layout.header_row < len(rows) and rows[layout.header_row][: len(layout.headers)] == layout.headers:
            return layout, True
    try:
        header_row, mapping = statement.detect(rows)
    except statement.StatementError as exc:
        raise _bad(exc) from exc
    return Layout(header_row=header_row, headers=rows[header_row], mapping=mapping), False


def preview(session: Session, data: bytes, file_name: str) -> Preview:
    try:
        rows = statement.read_rows(data, file_name)
    except statement.StatementError as exc:
        raise _bad(exc) from exc
    layout, remembered = _layout(session, rows)
    try:
        lines, problems = statement.parse(rows, layout.header_row, layout.mapping)
    except statement.StatementError as exc:
        raise _bad(exc) from exc
    return Preview(
        layout=layout,
        lines_found=len(lines),
        sample=[SampleLine(**{k: getattr(line, k) for k in SampleLine.model_fields}) for line in lines[:15]],
        problems=problems,
        remembered=remembered,
    )


def import_statement(session: Session, actor: User, data: bytes, file_name: str, layout: Layout) -> ImportResult:
    """Save the statement's new lines, remember its layout, and match what can be matched."""
    try:
        rows = statement.read_rows(data, file_name)
        lines, problems = statement.parse(rows, layout.header_row, layout.mapping)
    except statement.StatementError as exc:
        raise _bad(exc) from exc
    record = BankImport(company_id=actor.company_id, file_name=file_name, lines_read=len(lines), lines_new=0, imported_by=actor.id)
    session.add(record)
    session.flush()
    new = 0
    for line in lines:
        inserted = session.execute(
            insert(BankStatementLine)
            .values(
                id=uuid.uuid4(),
                company_id=actor.company_id,
                import_id=record.id,
                txn_date=line.txn_date,
                narration=line.narration,
                reference=line.reference,
                refs=line.refs,
                credit=line.credit,
                debit=line.debit,
                balance=line.balance,
                row_hash=line.row_hash,
            )
            .on_conflict_do_nothing(index_elements=["company_id", "row_hash"])
            .returning(BankStatementLine.id)
        )
        new += len(inserted.all())
    record.lines_new = new
    session.execute(
        insert(StatementFormat)
        .values(company_id=actor.company_id, columns=layout.model_dump())
        .on_conflict_do_update(index_elements=["company_id"], set_={"columns": layout.model_dump(), "updated_at": utcnow()})
    )
    session.flush()
    matched = auto_match(session)
    unmatched = len(session.scalars(select(BankStatementLine.id).where(BankStatementLine.status == "unmatched", BankStatementLine.credit > 0)).all())
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="bank.import",
        entity="bank_import",
        entity_id=record.id,
        detail={"file": file_name, "read": len(lines), "new": new, "matched": matched},
    )
    return ImportResult(lines_read=len(lines), lines_new=new, matched=matched, unmatched_credits=unmatched, problems=problems)


def _text(line: BankStatementLine) -> str:
    return f"{line.narration} {line.reference or ''}".upper()


def _confirm(collection: Collection, line: BankStatementLine) -> None:
    collection.status = "confirmed"
    collection.confirmed_at = utcnow()
    collection.bank_line_id = line.id
    line.status = "matched"
    line.matched_kind = "collection"


def _bank_deposit(session: Session, deposit: BankDeposit, line: BankStatementLine) -> None:
    """The deposit's cash reached the bank: every cash collection in it is confirmed."""
    deposit.status = "banked"
    deposit.bank_line_id = line.id
    line.status = "matched"
    line.matched_kind = "deposit"
    handover_ids = select(CashHandover.id).where(CashHandover.deposit_id == deposit.id)
    for collection in session.scalars(
        select(Collection).where(
            Collection.method == "cash",
            Collection.status == "pending",
            (Collection.deposit_id == deposit.id) | Collection.handover_id.in_(handover_ids),
        )
    ):
        collection.status = "confirmed"
        collection.confirmed_at = utcnow()


def _mentions_deposit(text: str, number: str) -> bool:
    digits = number.split("-", 1)[1]
    return re.search(rf"DEP[\s\-/]?0*{digits}(?![0-9])", text) is not None


def auto_match(session: Session) -> int:
    """Match unmatched credits to what the app is waiting for:
      UPI collections      by the 12-digit UTR the collector entered, and the amount
      deposited cheques    by cheque number and amount
      cash deposits        by the batch number written on the slip and the amount; failing that,
                           by amount alone if exactly one deposit and one credit fit within a few days
    Returns how many lines were matched."""
    lines = list(
        session.scalars(
            select(BankStatementLine)
            .where(BankStatementLine.status == "unmatched", BankStatementLine.credit > 0)
            .order_by(BankStatementLine.txn_date)
        )
    )
    upi = {c.utr: c for c in session.scalars(select(Collection).where(Collection.method == "upi", Collection.status == "pending"))}
    cheques = list(
        session.scalars(
            select(Collection).where(Collection.method == "cheque", Collection.status == "pending", Collection.deposit_id.is_not(None))
        )
    )
    deposits = list(session.scalars(select(BankDeposit).where(BankDeposit.status == "in_transit")))
    matched = 0
    for line in lines:
        text = _text(line)
        hit = next((c for utr, c in upi.items() if utr in text and c.amount == line.credit), None)
        if hit is not None:
            _confirm(hit, line)
            upi.pop(hit.utr)
            matched += 1
            continue
        hit = next((c for c in cheques if c.cheque_number in text and c.amount == line.credit), None)
        if hit is not None:
            _confirm(hit, line)
            cheques.remove(hit)
            matched += 1
            continue
        deposit = next((d for d in deposits if d.cash_amount == line.credit and _mentions_deposit(text, d.deposit_number)), None)
        if deposit is not None:
            _bank_deposit(session, deposit, line)
            deposits.remove(deposit)
            matched += 1
    # Banks often drop what was written on the slip. Match by amount and date only when it is unambiguous.
    remaining = [line for line in lines if line.status == "unmatched"]
    for deposit in list(deposits):
        day = deposit.deposited_at.date()
        window = [
            line for line in remaining
            if line.credit == deposit.cash_amount and day <= line.txn_date <= day + dt.timedelta(days=DEPOSIT_WINDOW_DAYS)
        ]
        rivals = [
            d for d in deposits
            if d.cash_amount == deposit.cash_amount and abs((d.deposited_at.date() - day).days) <= DEPOSIT_WINDOW_DAYS
        ]
        if len(window) == 1 and len(rivals) == 1:
            _bank_deposit(session, deposit, window[0])
            remaining.remove(window[0])
            deposits.remove(deposit)
            matched += 1
    session.flush()
    return matched


def list_lines(session: Session, status: str | None, limit: int, offset: int) -> list[LineRead]:
    query = select(BankStatementLine).order_by(BankStatementLine.txn_date.desc(), BankStatementLine.id).limit(limit).offset(offset)
    if status is not None:
        query = query.where(BankStatementLine.status == status)
    return [_line_read(line) for line in session.scalars(query)]


def _open_line(session: Session, line_id: uuid.UUID) -> BankStatementLine:
    line = session.get(BankStatementLine, line_id, with_for_update=True)
    if line is None:
        raise not_found("Statement line")
    if line.status != "unmatched":
        raise conflict("This statement line has already been dealt with.")
    if line.credit <= 0:
        raise conflict("Only money coming in can be matched.")
    return line


def match(session: Session, actor: User, line_id: uuid.UUID, collection_id: uuid.UUID | None, deposit_id: uuid.UUID | None) -> LineRead:
    """The owner confirms a match the app could not make itself, such as a UTR typed wrongly."""
    line = _open_line(session, line_id)
    if (collection_id is None) == (deposit_id is None):
        raise AppError(422, "one_target", "Match the line to one collection or one deposit.")
    if collection_id is not None:
        target = session.get(Collection, collection_id, with_for_update=True)
        if target is None:
            raise not_found("Collection")
        if target.status != "pending" or target.method not in ("upi", "cheque"):
            raise conflict("Only a UPI payment or a deposited cheque waiting for the bank can be matched.")
        if target.amount != line.credit:
            raise conflict(f"The amounts differ: Rs {target.amount:,.2f} recorded, Rs {line.credit:,.2f} in the bank.")
        _confirm(target, line)
    else:
        deposit = session.get(BankDeposit, deposit_id, with_for_update=True)
        if deposit is None:
            raise not_found("Deposit")
        if deposit.status != "in_transit":
            raise conflict("This deposit is already matched.")
        if deposit.cash_amount != line.credit:
            raise conflict(f"The amounts differ: Rs {deposit.cash_amount:,.2f} deposited, Rs {line.credit:,.2f} in the bank.")
        _bank_deposit(session, deposit, line)
    line.decided_by = actor.id
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="bank.match",
        entity="bank_statement_line",
        entity_id=line.id,
        detail={"collection_id": str(collection_id) if collection_id else None, "deposit_id": str(deposit_id) if deposit_id else None},
    )
    return _line_read(line)


def allocate(
    session: Session, actor: User, outbox: Outbox, line_id: uuid.UUID, payer: str, lr_ids: list[uuid.UUID] | None
) -> CollectionRead:
    line = _open_line(session, line_id)
    collection = collections.allocate_transfer(session, actor, outbox, line, payer, lr_ids)
    line.status = "matched"
    line.matched_kind = "allocation"
    line.decided_by = actor.id
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="bank.allocate",
        entity="bank_statement_line",
        entity_id=line.id,
        detail={"payer": payer, "amount": str(line.credit)},
    )
    return collection


def ignore(session: Session, actor: User, line_id: uuid.UUID, note: str) -> LineRead:
    """Not a customer payment (interest, the owner's own transfer). The reason is kept."""
    line = _open_line(session, line_id)
    line.status = "ignored"
    line.note = note
    line.decided_by = actor.id
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="bank.ignore",
        entity="bank_statement_line",
        entity_id=line.id,
        detail={"note": note, "amount": str(line.credit)},
    )
    return _line_read(line)


def _line_read(line: BankStatementLine) -> LineRead:
    return LineRead(
        id=line.id,
        txn_date=line.txn_date,
        narration=line.narration,
        reference=line.reference,
        credit=line.credit,
        debit=line.debit,
        status=line.status,
        matched_kind=line.matched_kind,
        note=line.note,
    )
