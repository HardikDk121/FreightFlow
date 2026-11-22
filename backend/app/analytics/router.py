import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.analytics import custom, export, periods, runner, service
from app.analytics.facts import CustomerRole, Filters, Stage
from app.analytics.saved import Analysis, SavedFilters, SavedReportIn, SavedReportRead
from app.clock import today
from app.db import get_session
from app.errors import AppError, conflict, forbidden, not_found
from app.models import Company, Lr, SavedReport, User
from app.permissions import P, require

router = APIRouter(prefix="/analytics", tags=["analytics"])
_viewer = require(P.ANALYTICS)



def filters(
    period: periods.Period | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    branch_id: uuid.UUID | None = None,
    customer: Annotated[str | None, Query(max_length=60)] = None,
    customer_role: CustomerRole = "payer",
    origin: Annotated[str | None, Query(max_length=30)] = None,
    destination: Annotated[str | None, Query(max_length=30)] = None,
    freight_by: Literal["Paid", "ToPay", "TBB"] | None = None,
    stage: Stage | None = None,
) -> Filters:
    """Dates win over a named period; with neither, the last 30 days."""
    if date_from is None or date_to is None:
        date_from, date_to = periods.resolve(period or "last_30_days", today())
    try:
        return Filters(
            date_from=date_from, date_to=date_to, branch_id=branch_id, customer=customer or None, customer_role=customer_role,
            origin=origin or None, destination=destination or None, freight_by=freight_by, stage=stage,
        )
    except ValidationError as exc:
        raise AppError(422, "bad_filters", exc.errors()[0]["msg"].removeprefix("Value error, ")) from exc


def _run(session: Session, user: User, name: str, f: Filters, grain: service.Grain = "day"):
    if not runner.allowed(user, name):
        raise forbidden()
    return runner.run(session, name, f, grain)


class Options(BaseModel):
    """Values for the filter pickers, from the LRs of the last year."""

    customers: list[str]
    origins: list[str]
    destinations: list[str]


@router.get("/options", response_model=Options)
def options(_: User = Depends(_viewer), session: Session = Depends(get_session)) -> Options:
    since = today() - dt.timedelta(days=366)

    def distinct(column) -> list[str]:
        return sorted(
            session.scalars(select(func.distinct(func.upper(func.trim(column)))).where(Lr.status == "confirmed", Lr.lr_date >= since))
        )

    payers = sorted({p for p in session.scalars(select(func.distinct(func.trim(Lr.consignee_name))).where(Lr.lr_date >= since))}
                    | {p for p in session.scalars(select(func.distinct(func.trim(Lr.consignor_name))).where(Lr.lr_date >= since))})
    return Options(customers=payers, origins=distinct(Lr.from_city), destinations=distinct(Lr.to_city))


@router.get("/{analysis}")
def run_analysis(
    analysis: Analysis,
    grain: service.Grain = "day",
    f: Filters = Depends(filters),
    user: User = Depends(_viewer),
    session: Session = Depends(get_session),
):
    """One analysis over the filtered LRs. Each answer says how its figures were worked out (`basis`)."""
    return _run(session, user, analysis, f, grain)


@router.post("/custom", response_model=custom.Table)
def run_custom(report: custom.CustomReport, f: Filters = Depends(filters), _: User = Depends(_viewer), session: Session = Depends(get_session)) -> custom.Table:
    try:
        return custom.run(session, f, report)
    except ValueError as exc:
        raise AppError(422, "bad_report", str(exc)) from exc


def _file(session: Session, user: User, name: str, result, fmt: str) -> Response:
    company = session.get_one(Company, user.company_id).name
    tables = export.tables(name, result)
    stamp = today().isoformat()
    if fmt == "xlsx":
        return Response(
            export.to_xlsx(company, tables),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{name}-{stamp}.xlsx"'},
        )
    return Response(export.to_pdf(company, tables[0]), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}-{stamp}.pdf"'})


@router.get("/{analysis}/export")
def export_analysis(
    analysis: Analysis,
    fmt: Annotated[Literal["xlsx", "pdf"], Query(alias="format")] = "xlsx",
    grain: service.Grain = "day",
    f: Filters = Depends(filters),
    user: User = Depends(_viewer),
    session: Session = Depends(get_session),
) -> Response:
    """The analysis as an Excel workbook (every table, every column) or a PDF (the main table)."""
    return _file(session, user, analysis, _run(session, user, analysis, f, grain), fmt)


@router.post("/custom/export")
def export_custom(
    report: custom.CustomReport,
    fmt: Annotated[Literal["xlsx", "pdf"], Query(alias="format")] = "xlsx",
    f: Filters = Depends(filters),
    user: User = Depends(_viewer),
    session: Session = Depends(get_session),
) -> Response:
    try:
        table = custom.run(session, f, report)
    except ValueError as exc:
        raise AppError(422, "bad_report", str(exc)) from exc
    return _file(session, user, "custom", table, fmt)


# ---------------------------------------------------------------- saved and scheduled reports


def _read(r: SavedReport) -> SavedReportRead:
    return SavedReportRead(
        id=r.id, name=r.name, analysis=r.analysis, filters=SavedFilters.model_validate(r.filters),
        custom=custom.CustomReport.model_validate(r.custom) if r.custom else None, schedule=r.schedule,
        recipients=r.recipients, is_active=r.is_active, last_sent_on=r.last_sent_on,
    )


def _check(body: SavedReportIn) -> None:
    if (body.analysis == "custom") != (body.custom is not None):
        raise AppError(422, "bad_report", "A custom report needs its definition, and only a custom report has one.")
    if body.schedule != "none" and not body.recipients:
        raise AppError(422, "no_recipients", "A scheduled report needs at least one email address to go to.")


@router.get("/saved/list", response_model=list[SavedReportRead])
def list_saved(_: User = Depends(_viewer), session: Session = Depends(get_session)) -> list[SavedReportRead]:
    return [_read(r) for r in session.scalars(select(SavedReport).where(SavedReport.is_active).order_by(SavedReport.name))]


@router.post("/saved", response_model=SavedReportRead, status_code=status.HTTP_201_CREATED)
def save_report(body: SavedReportIn, actor: User = Depends(_viewer), session: Session = Depends(get_session)) -> SavedReportRead:
    _check(body)
    if session.scalar(select(SavedReport.id).where(func.lower(SavedReport.name) == body.name.lower())) is not None:
        raise conflict(f"A report called {body.name} already exists.")
    report = SavedReport(
        company_id=actor.company_id, name=body.name, analysis=body.analysis, filters=body.filters.model_dump(mode="json"),
        custom=body.custom.model_dump(mode="json") if body.custom else None, schedule=body.schedule,
        recipients=[str(r) for r in body.recipients], is_active=body.is_active, created_by=actor.id,
    )
    session.add(report)
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="report.save", entity="saved_report", entity_id=report.id,
                 detail={"name": body.name, "schedule": body.schedule})
    return _read(report)


@router.put("/saved/{report_id}", response_model=SavedReportRead)
def update_report(report_id: uuid.UUID, body: SavedReportIn, actor: User = Depends(_viewer), session: Session = Depends(get_session)) -> SavedReportRead:
    _check(body)
    report = session.get(SavedReport, report_id)
    if report is None:
        raise not_found("Report")
    report.name, report.analysis, report.schedule, report.is_active = body.name, body.analysis, body.schedule, body.is_active
    report.filters = body.filters.model_dump(mode="json")
    report.custom = body.custom.model_dump(mode="json") if body.custom else None
    report.recipients = [str(r) for r in body.recipients]
    session.flush()
    audit.record(session, company_id=actor.company_id, actor_id=actor.id, action="report.update", entity="saved_report", entity_id=report.id,
                 detail={"name": body.name, "schedule": body.schedule, "active": body.is_active})
    return _read(report)
