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

    def get_user(self, token: str):
        self.tokens.append(token)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(user=self.user)


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

        with patch(
            "app.api.dependencies.get_supabase_client",
            return_value=fake_client,
        ):
            response = await self.request({"Authorization": "Bearer valid-token"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"user_id": "user-123", "email": "patient@example.com"},
        )
        self.assertEqual(fake_auth.tokens, ["valid-token"])


if __name__ == "__main__":
    import unittest

    unittest.main()
