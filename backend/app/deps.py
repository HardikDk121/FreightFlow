from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_session, set_tenant
from app.errors import forbidden, unauthorized
from app.models import Role, User
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> User:
    """Authenticate, scope the request's transaction to the caller's company, load the caller.

    The user row is read on every request, so a role change or deactivation takes effect
    immediately instead of when the access token expires.
    """
    if credentials is None:
        raise unauthorized()
    claims = decode_access_token(credentials.credentials)
    set_tenant(session, claims.company_id)
    user = session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    return user


def require_roles(*roles: Role) -> Callable[[User], User]:
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise forbidden()
        return user

    return dependency
