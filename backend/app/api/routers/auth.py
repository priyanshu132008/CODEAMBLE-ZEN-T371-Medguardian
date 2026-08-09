"""Authentication and authenticated-user identity routes."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import AuthenticatedUser, get_current_user
from app.core.config import settings
from app.db.supabase_client import get_supabase_client
from app.schemas.auth import AuthCredentials, AuthMeResponse, AuthResponse


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_email(user: Any, fallback: str) -> str:
    email = getattr(user, "email", None)
    return str(email) if email else fallback


def _user_name(user: Any, email: str) -> str:
    metadata = getattr(user, "user_metadata", None) or {}
    name = metadata.get("full_name") or metadata.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return email.split("@", 1)[0]


def _auth_response(auth_result: Any, fallback_email: str) -> AuthResponse:
    user = getattr(auth_result, "user", None)
    session = getattr(auth_result, "session", None)
    access_token = getattr(session, "access_token", None) if session else None
    email = _user_email(user, fallback_email)
    user_id = getattr(user, "id", None)

    # Admin status is resolved by the SERVER from the validated Supabase user's
    # email against the ADMIN_EMAILS allowlist — never from the browser-supplied
    # role field (which is accepted for API compatibility but ignored). A user
    # who is not on the allowlist is always "patient", regardless of what the
    # login form's role toggle claimed.
    role = "admin" if settings.is_admin_email(email) else "patient"

    # Do not derive privileges or ABHA from browser input or arbitrary metadata.
    return AuthResponse(
        access_token=str(access_token) if access_token else None,
        token=str(access_token) if access_token else None,
        user_id=str(user_id) if user_id else None,
        email=email,
        name=_user_name(user, email),
        role=role,
        abha_id=None,
        email_confirmation_required=not bool(access_token),
    )


def _provider_message(exc: Exception) -> str:
    return str(getattr(exc, "message", "") or exc).lower()


def _auth_http_exception(exc: Exception, *, operation: str) -> HTTPException:
    """Map provider failures without exposing provider details."""

    message = _provider_message(exc)
    provider_status = getattr(exc, "status", None) or getattr(exc, "status_code", None)

    if operation == "register" and any(
        phrase in message for phrase in ("already registered", "already exists", "user exists")
    ):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    if operation == "login" and (
        provider_status in {400, 401, 422}
        or any(
            phrase in message
            for phrase in ("invalid", "credentials", "password", "email not found")
        )
    ):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if provider_status in {400, 422}:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The registration details were rejected.",
        )

    if provider_status == 429:
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Authentication service is temporarily unavailable. Try again later.",
        )

    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Authentication service request failed.",
    )


def _get_auth_client():
    try:
        return get_supabase_client()
    except Exception as exc:  # noqa: BLE001 - configuration/provider boundary
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is not configured.",
        ) from exc


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(credentials: AuthCredentials) -> AuthResponse:
    """Create a Supabase Auth account using only email and password."""

    try:
        result = _get_auth_client().auth.sign_up(
            {"email": credentials.email, "password": credentials.password}
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - Supabase SDK errors vary by version
        raise _auth_http_exception(exc, operation="register") from exc

    return _auth_response(result, credentials.email)


@router.post("/login", response_model=AuthResponse)
async def login(credentials: AuthCredentials) -> AuthResponse:
    """Authenticate with Supabase Auth and return the real access token."""

    try:
        result = _get_auth_client().auth.sign_in_with_password(
            {"email": credentials.email, "password": credentials.password}
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - Supabase SDK errors vary by version
        raise _auth_http_exception(exc, operation="login") from exc

    response = _auth_response(result, credentials.email)
    if not response.access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Authentication service did not return an access token.",
        )
    return response


@router.get("/me", response_model=AuthMeResponse)
async def get_authenticated_user(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AuthMeResponse:
    """Return the authenticated identity with the SERVER-RESOLVED role.

    The frontend Google OAuth callback sends the Supabase access token here to
    finalize the session: the backend validates the token (via
    ``get_current_user``) and returns the authoritative role — ``admin`` only
    when the validated email is on the ``ADMIN_EMAILS`` allowlist, else
    ``patient``. The frontend therefore never decides admin status; an
    allowlisted email signing in through Google is routed to ``/admin``, a
    non-allowlisted one to ``/patient``, exactly as the email/password flow.
    """
    email = current_user.email
    role = "admin" if settings.is_admin_email(email) else "patient"
    name = email.split("@", 1)[0] if email else "User"
    return AuthMeResponse(
        user_id=current_user.user_id,
        email=email,
        role=role,
        name=name,
    )
