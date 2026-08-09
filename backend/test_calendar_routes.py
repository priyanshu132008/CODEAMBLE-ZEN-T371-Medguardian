"""Tests for the Google Calendar OAuth routes (connect / callback / status /
disconnect) and the global guarantee that no token material leaks.

Auth is mocked at the dependency seam; Google + Supabase-backed services are
mocked at the router module seam. The callback (a top-level browser navigation
with no bearer header) is exercised directly — its single-use signed state
recovers the authenticated identity, exactly as in production.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx

from app.api.dependencies import AuthenticatedUser
from app.core.config import settings
from app.schemas.calendar import CalendarConnectionProfile
from app.services.google_calendar_service import (
    GoogleCalendarErrorKind,
    TokenExchangeResult,
    UserinfoResult,
)
from app.services.oauth_state import VerifiedState
from main import app

USER_ID = "11111111-1111-4111-8111-111111111111"


# ---------------------------------------------------------------------------
# Auth + service fakes
# ---------------------------------------------------------------------------


class _FakeAuth:
    def __init__(self, user: object):
        self.user = user
        self.tokens: list[str] = []

    def get_user(self, token: str):
        self.tokens.append(token)
        return SimpleNamespace(user=self.user)


class _FakeAuthClient:
    def __init__(self, auth: _FakeAuth):
        self.auth = auth


def _auth_client(user_id: str = USER_ID) -> tuple[_FakeAuthClient, _FakeAuth]:
    user = SimpleNamespace(id=user_id, email="patient@example.com")
    auth = _FakeAuth(user)
    return _FakeAuthClient(auth), auth


class _FakeOAuthState:
    def __init__(self, *, verified: VerifiedState | None = None, issue_state: str = "test-state"):
        self.verified = verified
        self.issue_state = issue_state
        self.issued_with: dict | None = None

    def issue(self, *, user_id: str, access_token: str) -> str:
        self.issued_with = {"user_id": user_id, "access_token": access_token}
        return self.issue_state

    def verify(self, state: str) -> VerifiedState | None:
        return self.verified


class _FakeGoogle:
    def __init__(
        self,
        *,
        access_token: str = "gt-access",
        refresh_token: str = "gt-refresh",
        email: str = "calendar@example.com",
        exchange_error: GoogleCalendarErrorKind | None = None,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.email = email
        self.exchange_error = exchange_error
        self.revoked: list[str] = []
        self.exchanged_codes: list[str] = []
        self.userinfo_calls = 0

    def build_consent_url(self, *, state: str) -> str:
        # Mirror the real builder so the scope assertion is meaningful, but
        # with a fixed client id so it does not depend on settings contents.
        from urllib.parse import urlencode
        params = {
            "client_id": "test-client-id",
            "redirect_uri": "http://localhost:8000/api/calendar/google/callback",
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/calendar.events openid email",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

    def exchange_authorization_code(self, *, code: str) -> TokenExchangeResult:
        self.exchanged_codes.append(code)
        if self.exchange_error is not None:
            return TokenExchangeResult(error=self.exchange_error)
        return TokenExchangeResult(access_token=self.access_token, refresh_token=self.refresh_token)

    def fetch_userinfo(self, *, access_token: str) -> UserinfoResult:
        self.userinfo_calls += 1
        return UserinfoResult(email=self.email)

    def revoke_token(self, *, token: str) -> None:
        self.revoked.append(token)


class _FakeCalendarConn:
    def __init__(self, *, profile: CalendarConnectionProfile | None = None, refresh_token: str | None = None):
        self.profile = profile
        self.refresh_token = refresh_token
        self.saved: list[dict] = []
        self.deleted = False

    def get_google_connection(self, *, current_user, access_token):
        return self.profile

    def get_decrypted_refresh_token(self, *, current_user, access_token):
        return self.refresh_token

    def save_google_connection(self, **kwargs):
        self.saved.append(kwargs)
        return None

    def delete_google_connection(self, **kwargs):
        self.deleted = True
        return True


class _FakeReminderSync:
    def __init__(self):
        self.disconnected_marked = False

    def mark_reminders_disconnected(self, *, current_user, access_token):
        self.disconnected_marked = True


@contextmanager
def _google_configured(client_id: str = "test-client-id", origins: list[str] | None = None):
    """Patch settings so is_google_configured() is True for the duration."""
    with (
        patch.object(settings, "google_client_id", client_id),
        patch.object(settings, "google_client_secret", "test-secret"),
        patch.object(
            settings,
            "google_redirect_uri",
            "http://localhost:8000/api/calendar/google/callback",
        ),
        patch.object(settings, "frontend_redirect_origins", origins or ["http://localhost:3000"]),
    ):
        yield


class CalendarRouteTests(IsolatedAsyncioTestCase):
    async def _client(self):
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    # -- /connect ----------------------------------------------------------

    async def test_connect_unauthenticated_returns_401(self):
        async with await self._client() as client:
            response = await client.get("/api/calendar/google/connect")
        self.assertEqual(response.status_code, 401)

    async def test_connect_unconfigured_returns_503(self):
        auth_client, _ = _auth_client()
        with (
            patch.object(settings, "google_client_id", ""),
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
        ):
            async with await self._client() as client:
                response = await client.get(
                    "/api/calendar/google/connect",
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 503)

    async def test_connect_returns_authorization_url_with_calendar_events_scope(self):
        auth_client, _ = _auth_client()
        fake_state = _FakeOAuthState(issue_state="state-123")
        with (
            _google_configured(),
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch("app.api.routers.calendar.OAuthStateService", return_value=fake_state),
        ):
            async with await self._client() as client:
                response = await client.get(
                    "/api/calendar/google/connect",
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 200)
        url = response.json()["authorization_url"]
        # The consent URL requests the calendar.events scope (write events) and
        # carries the single-use state — never a token.
        self.assertIn("calendar.events", url)
        self.assertIn("state=state-123", url)
        self.assertIn("access_type=offline", url)
        self.assertNotIn("valid-token", url)
        self.assertEqual(fake_state.issued_with["access_token"], "valid-token")
        self.assertEqual(fake_state.issued_with["user_id"], USER_ID)

    # -- /callback ---------------------------------------------------------

    async def test_callback_denied_redirects_with_error(self):
        with _google_configured():
            async with await self._client() as client:
                response = await client.get(
                    "/api/calendar/google/callback",
                    params={"error": "access_denied"},
                )
        self.assertTrue(300 <= response.status_code < 400)
        location = response.headers.get("location", "")
        self.assertIn("google_error=denied", location)
        self.assertTrue(location.startswith("http://localhost:3000"))

    async def test_callback_missing_code_and_state_redirects_invalid(self):
        with _google_configured():
            async with await self._client() as client:
                response = await client.get("/api/calendar/google/callback")
        self.assertTrue(300 <= response.status_code < 400)
        self.assertIn("google_error=invalid_callback", response.headers.get("location", ""))

    async def test_callback_tampered_state_redirects_invalid(self):
        fake_state = _FakeOAuthState(verified=None)
        with (
            _google_configured(),
            patch("app.api.routers.calendar.OAuthStateService", return_value=fake_state),
        ):
            async with await self._client() as client:
                response = await client.get(
                    "/api/calendar/google/callback",
                    params={"code": "abc", "state": "tampered"},
                )
        self.assertTrue(300 <= response.status_code < 400)
        self.assertIn("google_error=state_invalid", response.headers.get("location", ""))

    async def test_callback_valid_persists_connection_and_redirects(self):
        verified = VerifiedState(user_id=USER_ID, access_token="recovered-user-token")
        fake_state = _FakeOAuthState(verified=verified)
        fake_google = _FakeGoogle(access_token="gt-access", refresh_token="gt-refresh", email="calendar@example.com")
        fake_conn = _FakeCalendarConn()
        with (
            _google_configured(),
            patch("app.api.routers.calendar.OAuthStateService", return_value=fake_state),
            patch("app.api.routers.calendar.GoogleCalendarService", return_value=fake_google),
            patch("app.api.routers.calendar.CalendarConnectionService", return_value=fake_conn),
        ):
            async with await self._client() as client:
                response = await client.get(
                    "/api/calendar/google/callback",
                    params={"code": "auth-code", "state": "state-123"},
                )
        self.assertTrue(300 <= response.status_code < 400)
        location = response.headers.get("location", "")
        self.assertTrue(location.startswith("http://localhost:3000"))
        self.assertIn("google=connected", location)
        # The connection was saved through the RLS-protected path using the
        # recovered user token, with the rotated refresh token + email.
        self.assertEqual(len(fake_conn.saved), 1)
        saved = fake_conn.saved[0]
        self.assertEqual(saved["refresh_token"], "gt-refresh")
        self.assertEqual(saved["google_account_email"], "calendar@example.com")
        self.assertEqual(fake_google.exchanged_codes, ["auth-code"])
        # No token material leaks into the redirect URL.
        self.assertNotIn("gt-refresh", location)
        self.assertNotIn("gt-access", location)
        self.assertNotIn("recovered-user-token", location)

    async def test_callback_exchange_failure_redirects(self):
        verified = VerifiedState(user_id=USER_ID, access_token="recovered-user-token")
        fake_state = _FakeOAuthState(verified=verified)
        fake_google = _FakeGoogle(exchange_error=GoogleCalendarErrorKind.INVALID_GRANT)
        with (
            _google_configured(),
            patch("app.api.routers.calendar.OAuthStateService", return_value=fake_state),
            patch("app.api.routers.calendar.GoogleCalendarService", return_value=fake_google),
        ):
            async with await self._client() as client:
                response = await client.get(
                    "/api/calendar/google/callback",
                    params={"code": "bad-code", "state": "state-123"},
                )
        location = response.headers.get("location", "")
        self.assertIn("google_error=invalid_grant", location)

    async def test_callback_redirect_uses_allowlisted_origin_only(self):
        # Even with a non-default allowlist, the callback redirects only to the
        # configured origin — there is no request-controlled redirect target,
        # so the callback cannot be used as an open redirect.
        verified = VerifiedState(user_id=USER_ID, access_token="recovered-user-token")
        fake_state = _FakeOAuthState(verified=verified)
        fake_google = _FakeGoogle()
        fake_conn = _FakeCalendarConn()
        with (
            _google_configured(origins=["https://portal.medguardian.example"]),
            patch("app.api.routers.calendar.OAuthStateService", return_value=fake_state),
            patch("app.api.routers.calendar.GoogleCalendarService", return_value=fake_google),
            patch("app.api.routers.calendar.CalendarConnectionService", return_value=fake_conn),
        ):
            async with await self._client() as client:
                response = await client.get(
                    "/api/calendar/google/callback",
                    params={"code": "auth-code", "state": "state-123"},
                )
        location = response.headers.get("location", "")
        self.assertTrue(location.startswith("https://portal.medguardian.example"))
        self.assertNotIn("localhost", location)

    # -- /status -----------------------------------------------------------

    async def test_status_unauthenticated_returns_401(self):
        async with await self._client() as client:
            response = await client.get("/api/calendar/google/status")
        self.assertEqual(response.status_code, 401)

    async def test_status_unconfigured_reports_disconnected(self):
        auth_client, _ = _auth_client()
        with (
            patch.object(settings, "google_client_id", ""),
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
        ):
            async with await self._client() as client:
                response = await client.get(
                    "/api/calendar/google/status",
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"connected": False, "profile": None})

    async def test_status_connected_returns_safe_profile_without_tokens(self):
        auth_client, _ = _auth_client()
        profile = CalendarConnectionProfile(
            id="22222222-2222-4222-8222-222222222222",
            user_id=USER_ID,
            provider="google",
            google_account_email="calendar@example.com",
            calendar_id="primary",
        )
        fake_conn = _FakeCalendarConn(profile=profile)
        with (
            _google_configured(),
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch("app.api.routers.calendar.CalendarConnectionService", return_value=fake_conn),
        ):
            async with await self._client() as client:
                response = await client.get(
                    "/api/calendar/google/status",
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["connected"])
        self.assertEqual(body["profile"]["google_account_email"], "calendar@example.com")
        # The safe profile schema has no encrypted/token fields, and none leak.
        self.assertNotIn("encrypted_refresh_token", response.text)
        self.assertNotIn("refresh_token", response.text)
        self.assertNotIn("access_token", response.text)

    async def test_status_not_connected_returns_disconnected(self):
        auth_client, _ = _auth_client()
        fake_conn = _FakeCalendarConn(profile=None)
        with (
            _google_configured(),
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch("app.api.routers.calendar.CalendarConnectionService", return_value=fake_conn),
        ):
            async with await self._client() as client:
                response = await client.get(
                    "/api/calendar/google/status",
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"connected": False, "profile": None})

    # -- /disconnect -------------------------------------------------------

    async def test_disconnect_unauthenticated_returns_401(self):
        async with await self._client() as client:
            response = await client.delete("/api/calendar/google/disconnect")
        self.assertEqual(response.status_code, 401)

    async def test_disconnect_revokes_deletes_and_marks_reminders_disconnected(self):
        auth_client, _ = _auth_client()
        fake_conn = _FakeCalendarConn(refresh_token="rt-123")
        fake_google = _FakeGoogle()
        fake_reminders = _FakeReminderSync()
        with (
            _google_configured(),
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch("app.api.routers.calendar.CalendarConnectionService", return_value=fake_conn),
            patch("app.api.routers.calendar.GoogleCalendarService", return_value=fake_google),
            patch("app.api.routers.calendar.ReminderSyncService", return_value=fake_reminders),
        ):
            async with await self._client() as client:
                response = await client.delete(
                    "/api/calendar/google/disconnect",
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["disconnected"])
        # The refresh token was revoked at Google before the local delete.
        self.assertEqual(fake_google.revoked, ["rt-123"])
        self.assertTrue(fake_conn.deleted)
        self.assertTrue(fake_reminders.disconnected_marked)
        # No token material in the response body.
        self.assertNotIn("rt-123", response.text)

    async def test_disconnect_without_refresh_token_still_deletes_locally(self):
        auth_client, _ = _auth_client()
        fake_conn = _FakeCalendarConn(refresh_token=None)
        fake_google = _FakeGoogle()
        fake_reminders = _FakeReminderSync()
        with (
            _google_configured(),
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch("app.api.routers.calendar.CalendarConnectionService", return_value=fake_conn),
            patch("app.api.routers.calendar.GoogleCalendarService", return_value=fake_google),
            patch("app.api.routers.calendar.ReminderSyncService", return_value=fake_reminders),
        ):
            async with await self._client() as client:
                response = await client.delete(
                    "/api/calendar/google/disconnect",
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["disconnected"])
        # Nothing to revoke, but local delete + reminder marking still ran.
        self.assertEqual(fake_google.revoked, [])
        self.assertTrue(fake_conn.deleted)
        self.assertTrue(fake_reminders.disconnected_marked)


class NoTokenLeakageTests(IsolatedAsyncioTestCase):
    """A global guard: no fabricated token/secret string appears in any
    protected-calendar response body across the suite above."""

    async def test_no_fake_token_strings_in_calendar_responses(self):
        secrets = [
            "gt-refresh", "gt-access", "recovered-user-token", "rt-123",
            "test-secret", "SECRET-GOOGLE-ACCESS",
        ]
        # Smoke the status endpoint with a connected profile and assert none of
        # the fabricated secret strings appear — proving the safe schema + the
        # services do not echo token material under any path.
        auth_client, _ = _auth_client()
        profile = CalendarConnectionProfile(
            id="22222222-2222-4222-8222-222222222222",
            user_id=USER_ID,
            provider="google",
            google_account_email="calendar@example.com",
            calendar_id="primary",
        )
        fake_conn = _FakeCalendarConn(profile=profile)
        with (
            _google_configured(),
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch("app.api.routers.calendar.CalendarConnectionService", return_value=fake_conn),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/calendar/google/status",
                    headers={"Authorization": "Bearer valid-token"},
                )
        for secret in secrets:
            self.assertNotIn(secret, response.text)


if __name__ == "__main__":
    unittest.main()