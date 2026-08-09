"""Tests for Supabase token validation and the protected identity endpoint."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import httpx

from main import app


class _FakeAuth:
    def __init__(self, user: object | None = None, error: Exception | None = None):
        self.user = user
        self.error = error
        self.tokens: list[str] = []
        self.sign_up_payloads: list[dict] = []
        self.sign_in_payloads: list[dict] = []
        self.auth_result = SimpleNamespace(
            user=user,
            session=SimpleNamespace(access_token="test-access-token"),
        )

    def get_user(self, token: str):
        self.tokens.append(token)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(user=self.user)

    def sign_up(self, credentials: dict):
        self.sign_up_payloads.append(credentials)
        if self.error is not None:
            raise self.error
        return self.auth_result

    def sign_in_with_password(self, credentials: dict):
        self.sign_in_payloads.append(credentials)
        if self.error is not None:
            raise self.error
        return self.auth_result


class _FakeSupabaseClient:
    def __init__(self, auth: _FakeAuth):
        self.auth = auth


class AuthEndpointTests(IsolatedAsyncioTestCase):
    async def request(self, headers: dict[str, str] | None = None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/auth/me", headers=headers or {})

    async def post(self, path: str, payload: dict):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(path, json=payload)

    async def test_missing_authorization_header_returns_401(self):
        response = await self.request()
        self.assertEqual(response.status_code, 401)

    async def test_malformed_bearer_header_returns_401(self):
        response = await self.request({"Authorization": "Bearer"})
        self.assertEqual(response.status_code, 401)

    async def test_invalid_token_returns_401(self):
        fake_auth = _FakeAuth(error=ValueError("invalid token"))
        fake_client = _FakeSupabaseClient(fake_auth)

        with patch(
            "app.api.dependencies.get_supabase_client",
            return_value=fake_client,
        ):
            response = await self.request({"Authorization": "Bearer invalid-token"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(fake_auth.tokens, ["invalid-token"])

    async def test_valid_user_returns_safe_identity(self):
        fake_user = SimpleNamespace(
            id="user-123",
            email="patient@example.com",
            user_metadata={"sensitive": "not returned"},
        )
        fake_auth = _FakeAuth(user=fake_user)
        fake_client = _FakeSupabaseClient(fake_auth)

        with (
            patch("app.api.dependencies.get_supabase_client", return_value=fake_client),
            patch("app.api.routers.auth.settings.is_admin_email", return_value=False),
        ):
            response = await self.request({"Authorization": "Bearer valid-token"})

        self.assertEqual(response.status_code, 200)
        # /me now returns the server-resolved role + derived name so the
        # Google OAuth callback can finalize the session without the frontend
        # ever deciding admin status. No sensitive user_metadata leaks.
        self.assertEqual(
            response.json(),
            {
                "user_id": "user-123",
                "email": "patient@example.com",
                "role": "patient",
                "name": "patient",
            },
        )
        self.assertEqual(fake_auth.tokens, ["valid-token"])

    async def test_me_returns_admin_role_for_allowlisted_email(self):
        # The Google OAuth callback relies on /me to resolve the role. An
        # allowlisted email → role="admin" (server-resolved from ADMIN_EMAILS),
        # so the callback routes that user to /admin regardless of how they
        # authenticated.
        fake_user = SimpleNamespace(id="admin-9", email="admin@hospital.in")
        fake_auth = _FakeAuth(user=fake_user)
        fake_client = _FakeSupabaseClient(fake_auth)

        with (
            patch("app.api.dependencies.get_supabase_client", return_value=fake_client),
            patch("app.api.routers.auth.settings.is_admin_email", return_value=True),
        ):
            response = await self.request({"Authorization": "Bearer valid-token"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["role"], "admin")
        self.assertEqual(body["user_id"], "admin-9")
        self.assertEqual(body["email"], "admin@hospital.in")
        self.assertEqual(body["name"], "admin")

    async def test_successful_login_returns_access_token_and_safe_role(self):
        fake_user = SimpleNamespace(id="user-123", email="patient@example.com")
        fake_auth = _FakeAuth(user=fake_user)
        fake_client = _FakeSupabaseClient(fake_auth)

        with patch("app.api.routers.auth.get_supabase_client", return_value=fake_client):
            response = await self.post(
                "/api/auth/login",
                {"email": "patient@example.com", "password": "correct", "role": "admin"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["access_token"], "test-access-token")
        self.assertEqual(response.json()["token"], "test-access-token")
        self.assertEqual(response.json()["role"], "patient")
        self.assertEqual(
            fake_auth.sign_in_payloads,
            [{"email": "patient@example.com", "password": "correct"}],
        )

    async def test_invalid_login_returns_401(self):
        fake_auth = _FakeAuth(error=ValueError("invalid login credentials"))
        fake_client = _FakeSupabaseClient(fake_auth)

        with patch("app.api.routers.auth.get_supabase_client", return_value=fake_client):
            response = await self.post(
                "/api/auth/login",
                {"email": "patient@example.com", "password": "wrong"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid email or password.")

    async def test_allowlisted_email_login_returns_admin_role(self):
        # The server resolves admin status from ADMIN_EMAILS, not the
        # browser-supplied role field. An allowlisted email → role="admin"
        # even when the client sends no role claim at all.
        fake_user = SimpleNamespace(id="admin-1", email="admin@hospital.in")
        fake_auth = _FakeAuth(user=fake_user)
        fake_client = _FakeSupabaseClient(fake_auth)

        with (
            patch("app.api.routers.auth.get_supabase_client", return_value=fake_client),
            patch("app.api.routers.auth.settings.is_admin_email", return_value=True),
        ):
            response = await self.post(
                "/api/auth/login",
                {"email": "admin@hospital.in", "password": "correct"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "admin")

    async def test_client_supplied_admin_role_is_ignored_for_non_admin_email(self):
        # A patient who selects the "admin" toggle must NOT receive admin
        # privileges: the backend returns role="patient" because their email
        # is not on the allowlist, regardless of the client role claim.
        fake_user = SimpleNamespace(id="user-123", email="patient@example.com")
        fake_auth = _FakeAuth(user=fake_user)
        fake_client = _FakeSupabaseClient(fake_auth)

        with (
            patch("app.api.routers.auth.get_supabase_client", return_value=fake_client),
            patch("app.api.routers.auth.settings.is_admin_email", return_value=False),
        ):
            response = await self.post(
                "/api/auth/login",
                {"email": "patient@example.com", "password": "correct", "role": "admin"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "patient")

    async def test_successful_registration_returns_auth_contract(self):
        fake_user = SimpleNamespace(id="user-456", email="new@example.com")
        fake_auth = _FakeAuth(user=fake_user)
        fake_client = _FakeSupabaseClient(fake_auth)

        with patch("app.api.routers.auth.get_supabase_client", return_value=fake_client):
            response = await self.post(
                "/api/auth/register",
                {"email": "new@example.com", "password": "correct", "role": "admin"},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["access_token"], "test-access-token")
        self.assertEqual(response.json()["role"], "patient")
        self.assertEqual(
            fake_auth.sign_up_payloads,
            [{"email": "new@example.com", "password": "correct"}],
        )

    async def test_registration_error_returns_conflict(self):
        fake_auth = _FakeAuth(error=ValueError("User already registered"))
        fake_client = _FakeSupabaseClient(fake_auth)

        with patch("app.api.routers.auth.get_supabase_client", return_value=fake_client):
            response = await self.post(
                "/api/auth/register",
                {"email": "existing@example.com", "password": "correct"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"],
            "An account with this email already exists.",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
