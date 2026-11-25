from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.auth import email_codes, recovery, service
from app.auth.schemas import (
    Accepted,
    AcceptInviteRequest,
    EmailCodeRequest,
    EmailCodeSent,
    ForgotPasswordRequest,
    LoginRequest,
    RecoverEmailRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
)
from app.db import get_session
from app.deps import current_user
from app.errors import conflict
from app.models import User
from app.notify import Outbox, get_outbox

router = APIRouter(prefix="/auth", tags=["auth"])
MAX_REGISTRATIONS_PER_IP_PER_HOUR = 5


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request, session: Session = Depends(get_session)) -> TokenPair:
    # One network address may register only a few companies an hour.
    recovery.throttle(session, {recovery.throttle_key("register-ip", _ip(request)): MAX_REGISTRATIONS_PER_IP_PER_HOUR})
    if email_codes.email_taken(session, body.email):
        raise conflict("An account with this email already exists. Sign in, or reset your password.")
    email_codes.check_code(session, body.email, body.email_code)
    return service.register(session, body)


@router.post("/register/code", response_model=EmailCodeSent)
def send_signup_code(
    body: EmailCodeRequest, request: Request, session: Session = Depends(get_session), outbox: Outbox = Depends(get_outbox)
) -> EmailCodeSent:
    """Email a 6-digit code to the address signing up. Answers {"required": false} when verification is off."""
    return EmailCodeSent(**email_codes.send_code(session, outbox, body.email, _ip(request)))


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, request: Request, session: Session = Depends(get_session)) -> TokenPair:
    """After 5 wrong passwords for one account (or 30 from one address) in 15 minutes, sign-in pauses."""
    return service.login(session, body.login, body.password, _ip(request))


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, session: Session = Depends(get_session)) -> TokenPair:
    return service.refresh(session, body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    body: RefreshRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Response:
    service.logout(session, user, body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invites/accept", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def accept_invite(body: AcceptInviteRequest, session: Session = Depends(get_session)) -> TokenPair:
    return service.accept_invite(session, body)


def _ip(request: Request) -> str:
    # Behind the reverse proxy, uvicorn's --proxy-headers sets this to the caller's real address
    # (trusted only from the addresses in FF_FORWARDED_ALLOW_IPS; see the Dockerfile).
    return request.client.host if request.client else "unknown"


@router.post("/password/forgot", response_model=Accepted, status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    background: BackgroundTasks,
    outbox: Outbox = Depends(get_outbox),
    session: Session = Depends(get_session),
) -> Accepted:
    """Email a reset code. The reply is the same whether or not the account exists."""
    recovery.request_password_reset(session, body.login, _ip(request), outbox, background)
    return Accepted(message="If that account exists, a reset code has been sent to its email.")


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(body: ResetPasswordRequest, session: Session = Depends(get_session)) -> Response:
    """Set a new password with the emailed code. Every existing session is signed out."""
    recovery.reset_password(session, body.login, body.code, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/email/recover", response_model=Accepted, status_code=status.HTTP_202_ACCEPTED)
def recover_email(
    body: RecoverEmailRequest,
    request: Request,
    background: BackgroundTasks,
    outbox: Outbox = Depends(get_outbox),
    session: Session = Depends(get_session),
) -> Accepted:
    """Text the login email to this phone number, if an account uses it. The reply is always the same."""
    recovery.recover_login_email(session, body.phone, _ip(request), outbox, background)
    return Accepted(message="If an account uses that phone number, its login email has been sent there by SMS.")
