"""Protection applied to every request before it reaches an endpoint, and to every error after.

- Text with NUL characters is refused: PostgreSQL cannot store them, and they are never legitimate
  in this app's fields. (File uploads are not checked: a photo may contain any byte.)
- Request bodies are capped in size, so one request cannot exhaust memory.
- Errors are always JSON in one shape, name the field at fault, and never include internals.
  Unexpected errors are logged with a reference the person can quote, and they see only the reference.
- Browsers get security headers.
"""

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError, IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("freightflow.errors")

# JSON bodies: far above any real form. Uploads (invoice photos, bank statements, delivery photos) are
# checked again by the endpoint that reads them.
MAX_JSON_BYTES = 1_000_000
MAX_UPLOAD_BYTES = 25_000_000

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    # The API serves JSON and PDFs; the receipt check page has no scripts.
    (b"content-security-policy", b"default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"),
]


def _error(status: int, code: str, message: str, fields: dict[str, str] | None = None) -> JSONResponse:
    body: dict = {"error": {"code": code, "message": message}}
    if fields:
        body["error"]["fields"] = fields
    return JSONResponse(status_code=status, content=body)


class RequestGuard:
    """ASGI middleware: size limit and NUL check on the way in, security headers on the way out."""

    def __init__(self, app: ASGIApp, https: bool) -> None:
        self.app = app
        self.https = https

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        content_type = headers.get(b"content-type", b"").decode("latin-1").lower()
        is_json = "json" in content_type or (content_type == "" and scope["method"] in ("POST", "PUT", "PATCH"))
        limit = MAX_JSON_BYTES if is_json else MAX_UPLOAD_BYTES
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _error(413, "too_large", "The request is too large.")(scope, receive, send)
            return
        raw_target = scope.get("raw_path", b"") + b"?" + scope.get("query_string", b"")
        if b"%00" in raw_target or b"\x00" in raw_target:
            await _error(422, "bad_character", "The address contains a character that is not allowed.")(scope, receive, send)
            return

        body = b""
        if is_json and scope["method"] in ("POST", "PUT", "PATCH", "DELETE"):
            more = True
            while more:
                message = await receive()
                body += message.get("body", b"")
                more = message.get("more_body", False)
                if len(body) > limit:
                    await _error(413, "too_large", "The request is too large.")(scope, receive, send)
                    return
            if b"\\u0000" in body or b"\x00" in body:
                await _error(422, "bad_character", "Text contains an invisible NUL character. Retype the value.")(scope, receive, send)
                return
            sent = False

            async def replay() -> Message:
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            inner_receive = replay
        else:
            inner_receive = receive

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                extra = list(SECURITY_HEADERS)
                if self.https:
                    extra.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        await self.app(scope, inner_receive, with_headers)


def _field(loc: tuple | list) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts) or "request"


async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """422 in the app's error shape, with each field's problem, plus FastAPI's `detail` list for older clients."""
    fields: dict[str, str] = {}
    for item in exc.errors():
        fields.setdefault(_field(item.get("loc", ())), str(item.get("msg", "Invalid value")).removeprefix("Value error, "))
    first_field, first_message = next(iter(fields.items()), ("request", "Invalid request."))
    message = first_message if first_field == "request" else f"{first_field}: {first_message}"
    detail = [{"loc": list(i.get("loc", ())), "msg": str(i.get("msg", "")), "type": i.get("type", "")} for i in exc.errors()]
    body = {"error": {"code": "invalid", "message": message, "fields": fields}, "detail": detail}
    return JSONResponse(status_code=422, content=body)


async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    messages = {404: "Not found.", 405: "That action is not allowed here.", 401: "Sign in again."}
    return _error(exc.status_code, "http_error", messages.get(exc.status_code, str(exc.detail)))


async def integrity_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """A database rule caught what the endpoint did not check first: a duplicate, or a reference to
    something missing. Not the person's fault in a way they can fix by retyping, but not a crash either."""
    log.warning("Integrity error on %s %s: %s", request.method, request.url.path, exc.orig.__class__.__name__)
    return _error(409, "conflict", "That conflicts with an existing record (for example, the same name or number twice).")


async def data_handler(request: Request, exc: DataError) -> JSONResponse:
    log.warning("Data error on %s %s: %s", request.method, request.url.path, exc.orig.__class__.__name__)
    return _error(422, "invalid", "A value is outside what can be stored. Check the numbers and dates entered.")


async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
    reference = uuid.uuid4().hex[:10]
    log.exception("Unhandled error %s on %s %s", reference, request.method, request.url.path)
    return _error(500, "server_error", f"Something went wrong on our side. Reference {reference}.")


def install(app: FastAPI, https: bool) -> None:
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_handler)
    app.add_exception_handler(IntegrityError, integrity_handler)
    app.add_exception_handler(DataError, data_handler)
    app.add_exception_handler(Exception, unexpected_handler)
    app.add_middleware(RequestGuard, https=https)
