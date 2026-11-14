from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def unauthorized(message: str = "Sign in again.") -> AppError:
    return AppError(401, "unauthorized", message)


def forbidden() -> AppError:
    return AppError(403, "forbidden", "Your role does not allow this action.")


def not_found(entity: str) -> AppError:
    return AppError(404, "not_found", f"{entity} not found.")


def conflict(message: str) -> AppError:
    return AppError(409, "conflict", message)


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )
