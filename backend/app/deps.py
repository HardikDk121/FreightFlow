from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_session, set_branches, set_tenant
from app.errors import unauthorized
from app.models import User
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
    # Narrow the transaction to the user's branch. Row-level security enforces it on every table
    # that holds branch data, so no query can reach another branch's records.
    from app.permissions import sees_all_branches

    if not sees_all_branches(user):
        set_branches(session, [user.branch_id])
    return user
