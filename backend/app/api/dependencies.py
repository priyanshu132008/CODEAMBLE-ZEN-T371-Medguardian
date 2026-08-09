"""Shared API dependencies for protected FastAPI routes."""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.config import settings
from app.db.supabase_client import get_supabase_client


_bearer_scheme = HTTPBearer(auto_error=False)

# Dedicated logger so the admin authorization path is grep-able in the
# backend terminal — without these lines a silent 403 from require_admin
# is invisible to anyone not already staring at the traceback. The "Admin
# check failed for email" line is the one the operator needs to see to
# confirm that the session's email matches ADMIN_EMAILS exactly.
_AUTH_LOG = logging.getLogger("medguardian.auth")


class AuthenticatedUser(BaseModel):
    """Safe identity details exposed to protected application routes."""

    user_id: str
    email: str | None = None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _extract_bearer_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    token = credentials.credentials.strip()
    if not token or any(character.isspace() for character in token):
        raise _unauthorized()
    return token


def get_current_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Return the syntactically valid bearer token from the current request."""
    return _extract_bearer_token(credentials)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    """Validate a Supabase access token and return its authenticated user.

    Validation is delegated to Supabase Auth's ``get_user`` endpoint. The
    client-provided token is never treated as a patient identifier, and no
    patient ownership decision is made here.
    """
    token = _extract_bearer_token(credentials)

    try:
        response = get_supabase_client().auth.get_user(token)
    except Exception as exc:  # noqa: BLE001 - auth providers expose varied errors
        _AUTH_LOG.warning(
            "get_user FAILED token_prefix=%s exc_type=%s exc=%r",
            token[:12],
            type(exc).__name__,
            str(exc),
        )
        raise _unauthorized() from exc

    user = getattr(response, "user", None)
    user_id = getattr(user, "id", None)
    if not user_id:
        _AUTH_LOG.warning("get_user returned no user_id token_prefix=%s", token[:12])
        raise _unauthorized()

    email = getattr(user, "email", None)
    return AuthenticatedUser(
        user_id=str(user_id),
        email=str(email) if email is not None else None,
    )


def require_admin(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Authorize access to admin-only routes.

    Admin status is resolved by the SERVER from the validated Supabase user's
    email against the ``ADMIN_EMAILS`` allowlist (see ``app.core.config``). It is
    NEVER derived from a client-supplied role claim, so a patient cannot reach
    an admin endpoint by changing frontend state. Unauthenticated callers are
    rejected by ``get_current_user`` (401); authenticated non-admins get 403.
    """
    # DIAGNOSTIC: [DEBUG] prints so the operator can see exactly where a
    # request was killed. The previous logging-only lines were silent on
    # the terminal unless uvicorn was started with -v; these prints are
    # always visible. Three signals tell us where the wire is broken:
    #   1. "Admin dependency ENTERED"  → request reached require_admin.
    #   2. "Admin check FAILED"        → 403 here; route body never runs.
    #   3. "Admin dependency PASSED"   → route body will run.
    allowlist = sorted(settings.admin_emails)
    print(
        f"[DEBUG] Admin dependency ENTERED. "
        f"user_email={current_user.email!r} user_id={current_user.user_id} "
        f"admin_allowlist={allowlist}"
    )
    is_admin = settings.is_admin_email(current_user.email)
    if not is_admin:
        print(
            f"[DEBUG] Admin check FAILED. User email not in allowlist. "
            f"user_email={current_user.email!r} admin_allowlist={allowlist}"
        )
        _AUTH_LOG.warning(
            "Admin check FAILED for email: %s user_id=%s admin_allowlist=%s",
            current_user.email,
            current_user.user_id,
            allowlist,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    print(
        f"[DEBUG] Admin dependency PASSED. "
        f"user_email={current_user.email!r} user_id={current_user.user_id}"
    )
    _AUTH_LOG.info(
        "Admin check OK email=%s user_id=%s admin_allowlist=%s",
        current_user.email,
        current_user.user_id,
        allowlist,
    )
    return current_user
