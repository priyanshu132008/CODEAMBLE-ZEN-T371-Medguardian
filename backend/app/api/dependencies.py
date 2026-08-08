"""Shared API dependencies for protected FastAPI routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.db.supabase_client import get_supabase_client


_bearer_scheme = HTTPBearer(auto_error=False)


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


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    """Validate a Supabase access token and return its authenticated user.

    Validation is delegated to Supabase Auth's ``get_user`` endpoint. The
    client-provided token is never treated as a patient identifier, and no
    patient ownership decision is made here.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    token = credentials.credentials.strip()
    if not token or any(character.isspace() for character in token):
        raise _unauthorized()

    try:
        response = get_supabase_client().auth.get_user(token)
    except Exception as exc:  # noqa: BLE001 - auth providers expose varied errors
        raise _unauthorized() from exc

    user = getattr(response, "user", None)
    user_id = getattr(user, "id", None)
    if not user_id:
        raise _unauthorized()

    email = getattr(user, "email", None)
    return AuthenticatedUser(
        user_id=str(user_id),
        email=str(email) if email is not None else None,
    )
