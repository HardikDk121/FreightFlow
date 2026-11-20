from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.router import router as auth_router
from app.approvals import router as approvals_router
from app.bank.router import router as bank_router
from app.branch_router import router as branch_router
from app.chat.router import router as chat_router
from app.collections.router import router as collections_router
from app.company.router import router as company_router
from app.dashboard.operations import router as operations_router
from app.dashboard.router import router as dashboard_router
from app.delivery.router import router as delivery_router
from app.db import get_session
from app.dispatch.additions_router import router as additions_router
from app.dispatch.router import router as dispatch_router
from app.errors import AppError, app_error_handler
from app.eway.router import router as eway_router
from app.lr.router import router as lr_router
from app.masterdata.router import routers as masterdata_routers
from app.payments.router import router as payments_router
from app.rates.router import router as rates_router
from app.scan.router import router as scan_router
from app.reminders import router as reminders_router
from app.tasks import router as tasks_router
from app.users.router import router as users_router

app = FastAPI(title="FreightFlow AI", version="0.1.0")
app.add_exception_handler(AppError, app_error_handler)
for router in (
    auth_router,
    users_router,
    company_router,
    *masterdata_routers,
    lr_router,
    eway_router,
    rates_router,
    payments_router,
    collections_router,
    bank_router,
    approvals_router,
    tasks_router,
    operations_router,
    reminders_router,
    delivery_router,
    branch_router,
    scan_router,
    additions_router,
    dispatch_router,
    chat_router,
    dashboard_router,
):
    app.include_router(router)


@app.get("/health", tags=["ops"])
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}
