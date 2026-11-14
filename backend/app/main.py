from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.router import router as auth_router
from app.company.router import router as company_router
from app.db import get_session
from app.errors import AppError, app_error_handler
from app.masterdata.router import routers as masterdata_routers
from app.users.router import router as users_router

app = FastAPI(title="FreightFlow AI", version="0.1.0")
app.add_exception_handler(AppError, app_error_handler)
for router in (auth_router, users_router, company_router, *masterdata_routers):
    app.include_router(router)


@app.get("/health", tags=["ops"])
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}
