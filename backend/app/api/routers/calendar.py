"""Google Calendar OAuth + connection-management routes.

Routes (prefix ``/api/calendar/google``):

- ``GET  /connect``      — mint a single-use OAuth state bound to the caller's
  Supabase access token, return the Google consent URL as JSON. The frontend
  navigates to it (no token ever sits in the browser beyond our own opaque
  state).
- ``GET  /callback``     — the browser-level Google redirect. No bearer token
  is present (top-level navigation), so the caller is recovered from the
  signed state, the authorization code is exchanged, the Google account email
  is resolved, and the encrypted refresh token is persisted. Redirects only
  to an allowlisted frontend origin.
- ``GET  /status``       — safe connection profile (no token material).
- ``DELETE /disconnect`` — best-effort Google revocation + local delete.

Every authenticated route derives identity from ``get_current_user`` /
``get_current_access_token``; no frontend-supplied user id is ever trusted.
The callback is the only route without a bearer header — by design it uses
the single-use signed state instead.
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.api.dependencies import (
    AuthenticatedUser,
    get_current_access_token,
    get_current_user,
)
from app.core.config import settings
from app.db.supabase_client import get_supabase_service_client
from app.schemas.calendar import CalendarConnectResponse, CalendarStatusResponse
from app.services.calendar_connection_service import CalendarConnectionService
from app.services.google_calendar_service import (
    GoogleCalendarErrorKind,
    GoogleCalendarService,
)
from app.services.oauth_state import OAuthStateService
from app.services.reminder_sync_service import ReminderSyncService

router = APIRouter(prefix="/api/calendar/google", tags=["calendar"])

# Dedicated logger so the OAuth + reconnect lifecycle is easy to grep in the
# backend terminal during a live demo (one line per connect / callback /
# status probe instead of buried in uvicorn access logs).
_CALENDAR_LOG = logging.getLogger("medguardian.calendar")


def _google_unconfigured() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Google Calendar integration is not configured on the backend.",
    )


def _frontend_redirect(*, params: dict[str, str]) -> str:
    """Build a redirect to the first allowlisted frontend origin with params.

    The origin is taken from the backend allowlist (``FRONTEND_REDIRECT_ORIGINS``)
    so the callback can never be used as an open redirect — a value supplied by
    Google or the browser is never trusted here.
    """
    origin = settings.frontend_redirect_origins[0] if settings.frontend_redirect_origins else "http://localhost:3000"
    return f"{origin.rstrip('/')}/patient?{urlencode(params)}"


@router.get("/connect", response_model=CalendarConnectResponse)
def connect_google(
    current_user: AuthenticatedUser = Depends(get_current_user),
    access_token: str = Depends(get_current_access_token),
) -> CalendarConnectResponse:
    """Return the Google consent URL for the authenticated patient."""
    if not settings.is_google_configured():
        raise _google_unconfigured()

    state = OAuthStateService().issue(
        user_id=current_user.user_id,
        access_token=access_token,
    )
    url = GoogleCalendarService().build_consent_url(state=state)
    _CALENDAR_LOG.info(
        "calendar.connect issued user_id=%s state_prefix=%s",
        current_user.user_id,
        state[:8] if isinstance(state, str) else "<n/a>",
    )
    return CalendarConnectResponse(authorization_url=str(url))


@router.get("/callback")
def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """Handle the Google redirect, persist the connection, redirect home."""
    # Google surfaces a user-side denial (or a Google error) via `error`.
    if error:
        return RedirectResponse(_frontend_redirect(params={"google_error": "denied"}))

    if not code or not state:
        return RedirectResponse(_frontend_redirect(params={"google_error": "invalid_callback"}))

    if not settings.is_google_configured():
        return RedirectResponse(_frontend_redirect(params={"google_error": "unconfigured"}))

    # Recover the authenticated identity from the single-use signed state. No
    # bearer token is available on this top-level navigation.
    verified = OAuthStateService().verify(state)
    if verified is None:
        return RedirectResponse(_frontend_redirect(params={"google_error": "state_invalid"}))

    google = GoogleCalendarService()
    exchange = google.exchange_authorization_code(code=code)
    if exchange.error is not None or not exchange.access_token or not exchange.refresh_token:
        # invalid_grant (code reused / expired) maps to a clear, safe message.
        if exchange.error == GoogleCalendarErrorKind.INVALID_GRANT:
            return RedirectResponse(_frontend_redirect(params={"google_error": "invalid_grant"}))
        return RedirectResponse(_frontend_redirect(params={"google_error": "exchange_failed"}))

    userinfo = google.fetch_userinfo(access_token=exchange.access_token)
    google_email = userinfo.email

    # Reconstruct the authenticated user from the state; save the connection
    # through the existing RLS-protected write path using the recovered token.
    current_user = AuthenticatedUser(user_id=verified.user_id, email=None)
    try:
        CalendarConnectionService().save_google_connection(
            current_user=current_user,
            access_token=verified.access_token,
            refresh_token=exchange.refresh_token,
            google_account_email=google_email,
        )
    except Exception as exc:  # noqa: BLE001 - Supabase unavailable / write failed
        _CALENDAR_LOG.error(
            "calendar.callback persist_failed user_id=%s exc_type=%s exc=%r",
            current_user.user_id,
            type(exc).__name__,
            str(exc),
        )
        return RedirectResponse(_frontend_redirect(params={"google_error": "persist_failed"}))

    # Belt-and-suspenders: the state row was already deleted by verify() on a
    # successful exchange (single-use), but a stale oauth_states row from a
    # *previous* failed run could persist up to its 10-minute TTL. Purge any
    # leftover rows for this user so a future reconnect cycle starts from a
    # clean slate — this is the fix that prevents the google:unauthorized loop
    # when the only state in the system is the new connection.
    _purge_oauth_states_for_user(current_user.user_id)

    _CALENDAR_LOG.info(
        "calendar.callback connected user_id=%s google_email=%s",
        current_user.user_id,
        google_email or "<unknown>",
    )
    return RedirectResponse(_frontend_redirect(params={"google": "connected"}))


def _purge_oauth_states_for_user(user_id: str) -> None:
    """Delete any leftover oauth_states rows for this user.

    Best-effort: a Supabase failure here must not block the success redirect,
    because the user's Google connection has already been persisted above.
    Logged but never raised. Uses the service-role client because oauth_states
    has no client-facing RLS policies.
    """
    try:
        response = (
            get_supabase_service_client()
            .table("oauth_states")
            .delete()
            .eq("user_id", user_id)
            .execute()
        )
        _CALENDAR_LOG.info(
            "calendar.callback oauth_states purged user_id=%s rows=%s",
            user_id,
            len(getattr(response, "data", None) or []),
        )
    except Exception as exc:  # noqa: BLE001 - purge is best-effort
        _CALENDAR_LOG.warning(
            "calendar.callback oauth_states purge_failed user_id=%s exc_type=%s exc=%r",
            user_id,
            type(exc).__name__,
            str(exc),
        )
        return


@router.get("/status", response_model=CalendarStatusResponse)
def google_status(
    current_user: AuthenticatedUser = Depends(get_current_user),
    access_token: str = Depends(get_current_access_token),
) -> CalendarStatusResponse:
    """Return safe connection metadata (no token material)."""
    if not settings.is_google_configured():
        # Still report disconnected honestly rather than 503 here — the portal
        # uses status to decide whether to show the Connect button.
        return CalendarStatusResponse(connected=False, profile=None)
    profile = CalendarConnectionService().get_google_connection(
        current_user=current_user,
        access_token=access_token,
    )
    if profile is None:
        return CalendarStatusResponse(connected=False, profile=None)
    return CalendarStatusResponse(connected=True, profile=profile)


@router.delete("/disconnect")
def disconnect_google(
    current_user: AuthenticatedUser = Depends(get_current_user),
    access_token: str = Depends(get_current_access_token),
) -> dict[str, bool]:
    """Best-effort revoke + delete the current user's Google connection."""
    service = CalendarConnectionService()
    # Revoke the refresh token at Google first (best-effort), then delete local
    # material so a network failure during revocation still clears our store.
    refresh_token = service.get_decrypted_refresh_token(
        current_user=current_user,
        access_token=access_token,
    )
    if refresh_token:
        GoogleCalendarService().revoke_token(token=refresh_token)
    deleted = service.delete_google_connection(
        current_user=current_user,
        access_token=access_token,
    )
    # Mark the user's existing reminder rows as disconnected so the portal stops
    # presenting stale "active" reminders for a now-revoked connection.
    ReminderSyncService().mark_reminders_disconnected(
        current_user=current_user,
        access_token=access_token,
    )
    return {"disconnected": deleted}