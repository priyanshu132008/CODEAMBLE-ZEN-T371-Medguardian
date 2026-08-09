"""Google Calendar REST client (httpx, no Google SDK).

Talks to Google's OAuth2 + Calendar REST endpoints directly over httpx (already
a project dependency) so no new package is added. Every method returns a
discriminated result object whose ``error`` field is a safe
:class:`GoogleCalendarErrorKind`; raw tokens are never logged or surfaced in
error messages, and userinfo is reduced to the single ``email`` we need.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Any

import httpx

from app.core.config import settings

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# Calendar events scope — read/write the user's calendar events.
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
# openid + email so we can record which Google account was connected.
EMAIL_SCOPE = "openid email"

_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=10.0)


class GoogleCalendarErrorKind(str, Enum):
    """Safe, non-token-leaking categories for Google API failures."""

    INVALID_GRANT = "invalid_grant"
    UNAUTHORIZED = "unauthorized"
    RATE_LIMITED = "rate_limited"
    NETWORK = "network"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


def _classify_status(status_code: int, body: Any) -> GoogleCalendarErrorKind:
    """Map a Google HTTP error to a safe error kind without leaking the body."""
    error_field = ""
    if isinstance(body, dict):
        error_obj = body.get("error")
        error_field = error_obj if isinstance(error_obj, str) else str(error_obj or "")
    error_field = error_field.lower()

    if "invalid_grant" in error_field or "invalid_client" in error_field:
        return GoogleCalendarErrorKind.INVALID_GRANT
    if status_code == 404:
        return GoogleCalendarErrorKind.NOT_FOUND
    if status_code == 429:
        return GoogleCalendarErrorKind.RATE_LIMITED
    if status_code in (401, 403):
        return GoogleCalendarErrorKind.UNAUTHORIZED
    return GoogleCalendarErrorKind.UNKNOWN


def _safe_message(status_code: int) -> str:
    """A generic, non-leaking message for a failed Google call."""
    return f"Google API returned HTTP {status_code}."


@dataclass
class TokenExchangeResult:
    access_token: str | None = None
    refresh_token: str | None = None
    google_account_email: str | None = None
    error: GoogleCalendarErrorKind | None = None
    error_message: str | None = None


@dataclass
class RefreshResult:
    access_token: str | None = None
    new_refresh_token: str | None = None
    error: GoogleCalendarErrorKind | None = None
    error_message: str | None = None


@dataclass
class UserinfoResult:
    email: str | None = None
    error: GoogleCalendarErrorKind | None = None
    error_message: str | None = None


@dataclass
class EventOpResult:
    event_id: str | None = None
    error: GoogleCalendarErrorKind | None = None
    error_message: str | None = None


def build_event_payload(
    *,
    med_name: str,
    dosage: str | None,
    schedule_label: str | None,
    start_dt: Any,
    timezone: str,
    recurrence: list[str] | None = None,
) -> dict[str, Any]:
    """Build a Google Calendar event body for one medication reminder.

    Only medication name, dose, schedule, and the MedGuardian source go into the
    description — never ABHA id, diagnosis, allergies, or any token. The event
    is 5 minutes long with a popup reminder 10 minutes before, and a bounded
    ``COUNT`` recurrence when supplied.
    """
    end_dt = start_dt + timedelta(minutes=5)
    title = f"MedGuardian: {med_name}".strip()
    if dosage:
        title = f"{title} {dosage}".strip()

    description_lines = ["MedGuardian medication reminder."]
    description_lines.append(f"Medication: {med_name}")
    if dosage:
        description_lines.append(f"Dose: {dosage}")
    if schedule_label:
        description_lines.append(f"Schedule: {schedule_label}")
    description_lines.append("Source: MedGuardian post-discharge care plan.")

    payload: dict[str, Any] = {
        "summary": title,
        "description": "\n".join(description_lines),
        "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 10}],
        },
    }
    if recurrence:
        payload["recurrence"] = recurrence
    return payload


class GoogleCalendarService:
    """REST wrapper around Google OAuth2 + Calendar Events.

    All network state lives on a short-lived ``httpx.Client`` created per
    service instance; methods are safe to call from request handlers.
    """

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=_HTTP_TIMEOUT)

    # -- OAuth authorization ----------------------------------------------

    def build_consent_url(self, *, state: str) -> str:
        """Build the Google consent URL with the calendar.events scope."""
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": f"{CALENDAR_EVENTS_SCOPE} {EMAIL_SCOPE}",
            "access_type": "offline",
            # prompt=consent forces a fresh refresh_token on every connect so a
            # re-connect after a revoked grant still yields an offline token.
            "prompt": "consent",
            "state": state,
        }
        return httpx.Request("GET", GOOGLE_AUTH_URL, params=params).url

    def exchange_authorization_code(self, *, code: str) -> TokenExchangeResult:
        """Exchange an authorization code for access + refresh tokens."""
        data = {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }
        try:
            response = self._client.post(GOOGLE_TOKEN_URL, data=data)
        except httpx.HTTPError:
            return TokenExchangeResult(
                error=GoogleCalendarErrorKind.NETWORK,
                error_message="Could not reach Google to exchange the code.",
            )

        if response.status_code != 200:
            kind = _classify_status(response.status_code, _safe_json(response))
            return TokenExchangeResult(error=kind, error_message=_safe_message(response.status_code))

        body = _safe_json(response) or {}
        return TokenExchangeResult(
            access_token=body.get("access_token"),
            refresh_token=body.get("refresh_token"),
            google_account_email=None,  # resolved separately via userinfo
        )

    def fetch_userinfo(self, *, access_token: str) -> UserinfoResult:
        """Resolve the connected Google account's email (and nothing else)."""
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            response = self._client.get(GOOGLE_USERINFO_URL, headers=headers)
        except httpx.HTTPError:
            return UserinfoResult(
                error=GoogleCalendarErrorKind.NETWORK,
                error_message="Could not reach Google userinfo.",
            )
        if response.status_code != 200:
            kind = _classify_status(response.status_code, _safe_json(response))
            return UserinfoResult(error=kind, error_message=_safe_message(response.status_code))
        body = _safe_json(response) or {}
        return UserinfoResult(email=body.get("email"))

    # -- Token rotation ----------------------------------------------------

    def refresh_access_token(self, *, refresh_token: str) -> RefreshResult:
        """Refresh an access token. Google rotates the refresh token sometimes;
        the returned ``new_refresh_token`` is the value to persist (it falls
        back to the supplied token when Google does not rotate)."""
        data = {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        try:
            response = self._client.post(GOOGLE_TOKEN_URL, data=data)
        except httpx.HTTPError:
            return RefreshResult(
                error=GoogleCalendarErrorKind.NETWORK,
                error_message="Could not reach Google to refresh the token.",
            )
        if response.status_code != 200:
            kind = _classify_status(response.status_code, _safe_json(response))
            return RefreshResult(error=kind, error_message=_safe_message(response.status_code))
        body = _safe_json(response) or {}
        return RefreshResult(
            access_token=body.get("access_token"),
            # Google rarely returns a new refresh_token on refresh; keep the
            # existing one so the connection stays usable.
            new_refresh_token=body.get("refresh_token") or refresh_token,
        )

    # -- Calendar events ---------------------------------------------------

    def _events_url(self, *, calendar_id: str) -> str:
        return f"{GOOGLE_CALENDAR_EVENTS_URL}/{calendar_id}/events"

    def create_event(
        self, *, access_token: str, calendar_id: str, payload: dict[str, Any]
    ) -> EventOpResult:
        headers = _bearer(access_token)
        try:
            response = self._client.post(
                self._events_url(calendar_id=calendar_id), headers=headers, json=payload
            )
        except httpx.HTTPError:
            return EventOpResult(
                error=GoogleCalendarErrorKind.NETWORK,
                error_message="Could not reach Google Calendar to create the event.",
            )
        if response.status_code not in (200, 201):
            kind = _classify_status(response.status_code, _safe_json(response))
            return EventOpResult(error=kind, error_message=_safe_message(response.status_code))
        body = _safe_json(response) or {}
        return EventOpResult(event_id=body.get("id"))

    def update_event(
        self,
        *,
        access_token: str,
        calendar_id: str,
        event_id: str,
        payload: dict[str, Any],
    ) -> EventOpResult:
        headers = _bearer(access_token)
        url = f"{self._events_url(calendar_id=calendar_id)}/{event_id}"
        try:
            response = self._client.put(url, headers=headers, json=payload)
        except httpx.HTTPError:
            return EventOpResult(
                error=GoogleCalendarErrorKind.NETWORK,
                error_message="Could not reach Google Calendar to update the event.",
            )
        if response.status_code not in (200, 201):
            kind = _classify_status(response.status_code, _safe_json(response))
            return EventOpResult(error=kind, error_message=_safe_message(response.status_code))
        body = _safe_json(response) or {}
        # PUT may return a new event id; keep the original otherwise.
        return EventOpResult(event_id=body.get("id") or event_id)

    def delete_event(
        self, *, access_token: str, calendar_id: str, event_id: str
    ) -> EventOpResult:
        headers = _bearer(access_token)
        url = f"{self._events_url(calendar_id=calendar_id)}/{event_id}"
        try:
            response = self._client.delete(url, headers=headers)
        except httpx.HTTPError:
            # A network failure during delete is best-effort; do not block the
            # caller's delete on it.
            return EventOpResult(error=GoogleCalendarErrorKind.NETWORK)
        if response.status_code in (204, 200):
            return EventOpResult(event_id=event_id)
        if response.status_code == 404:
            return EventOpResult(event_id=event_id, error=GoogleCalendarErrorKind.NOT_FOUND)
        kind = _classify_status(response.status_code, _safe_json(response))
        return EventOpResult(error=kind, error_message=_safe_message(response.status_code))

    # -- Disconnect --------------------------------------------------------

    def revoke_token(self, *, token: str) -> None:
        """Best-effort token revocation. Never raises — disconnect must still
        succeed locally if Google is unreachable."""
        try:
            self._client.post(GOOGLE_REVOKE_URL, params={"token": token}, timeout=5.0)
        except httpx.HTTPError:
            return


def _bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _safe_json(response: httpx.Response) -> Any:
    """Parse JSON defensively; return None on any decode failure so error
    classification never raises on a non-JSON Google response."""
    try:
        return response.json()
    except (ValueError, TypeError):
        return None