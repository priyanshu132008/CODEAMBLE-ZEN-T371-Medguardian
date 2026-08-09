"""Tests for authenticated patient profile lookup."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import httpx

from main import app


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


class _FakePatientQuery:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.selected_columns: str | None = None
        self.filters: list[tuple[str, str]] = []
        self.limit_value: int | None = None

    def select(self, columns: str):
        self.selected_columns = columns
        return self

    def eq(self, column: str, value: str):
        self.filters.append((column, value))
        return self

    def limit(self, value: int):
        self.limit_value = value
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _FakeDatabaseClient:
    def __init__(self, query: _FakePatientQuery):
        self.query = query
        self.table_names: list[str] = []

    def table(self, table_name: str):
        self.table_names.append(table_name)
        return self.query


class PatientEndpointTests(IsolatedAsyncioTestCase):
    user_id = "11111111-1111-1111-1111-111111111111"
    access_token = "valid-token"

    async def request(self, headers: dict[str, str] | None = None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/patients/me", headers=headers or {})

    def _auth_client(self):
        user = SimpleNamespace(
            id=self.user_id,
            email="auth@example.com",
        )
        auth = _FakeAuth(user)
        return _FakeAuthClient(auth), auth

    async def test_authenticated_user_with_matching_patient_row_returns_200(self):
        auth_client, auth = self._auth_client()
        query = _FakePatientQuery(
            [
                {
                    "id": self.user_id,
                    "patient_code": "MG-001",
                    "full_name": "Test Patient",
                    "email": "patient-record@example.com",
                    "phone": "+91 9000000000",
                    "created_at": "2026-08-08T12:00:00Z",
                    "private_note": "must not be returned",
                }
            ]
        )
        database_client = _FakeDatabaseClient(query)

        with (
            patch(
                "app.api.dependencies.get_supabase_client",
                return_value=auth_client,
            ),
            patch(
                "app.services.patient_service.get_authenticated_supabase_client",
                return_value=database_client,
            ),
        ):
            response = await self.request(
                {"Authorization": f"Bearer {self.access_token}"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "id": self.user_id,
                "patient_code": "MG-001",
                "full_name": "Test Patient",
                "email": "patient-record@example.com",
                "phone": "+91 9000000000",
                "created_at": "2026-08-08T12:00:00Z",
            },
        )
        self.assertEqual(auth.tokens, [self.access_token])
        self.assertEqual(database_client.table_names, ["patients"])

    async def test_authenticated_user_without_patient_row_returns_404(self):
        auth_client, _ = self._auth_client()
        query = _FakePatientQuery([])
        database_client = _FakeDatabaseClient(query)

        with (
            patch(
                "app.api.dependencies.get_supabase_client",
                return_value=auth_client,
            ),
            patch(
                "app.services.patient_service.get_authenticated_supabase_client",
                return_value=database_client,
            ),
        ):
            response = await self.request(
                {"Authorization": f"Bearer {self.access_token}"}
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["detail"],
            "No patient record found for the authenticated user.",
        )

    async def test_unauthenticated_request_returns_401(self):
        response = await self.request()
        self.assertEqual(response.status_code, 401)

    async def test_lookup_uses_authenticated_user_id_not_email(self):
        auth_client, _ = self._auth_client()
        query = _FakePatientQuery(
            [
                {
                    "id": self.user_id,
                    "patient_code": "MG-002",
                    "full_name": "Identity Test",
                    "email": "different-record-email@example.com",
                    "phone": None,
                    "created_at": None,
                }
            ]
        )
        database_client = _FakeDatabaseClient(query)

        with (
            patch(
                "app.api.dependencies.get_supabase_client",
                return_value=auth_client,
            ),
            patch(
                "app.services.patient_service.get_authenticated_supabase_client",
                return_value=database_client,
            ),
        ):
            response = await self.request(
                {"Authorization": f"Bearer {self.access_token}"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(query.filters, [("id", self.user_id)])
        self.assertNotIn(("email", "auth@example.com"), query.filters)
        self.assertEqual(database_client.table_names, ["patients"])


class PatientListEndpointTests(IsolatedAsyncioTestCase):
    """Admin-authorization for GET /api/patients (the cohort listing).

    The list endpoint requires a validated Supabase token whose email is on the
    ADMIN_EMAILS allowlist. Unauthenticated → 401, authenticated non-admin →
    403, admin → the registry. The server resolves admin status; a patient
    cannot reach it by changing frontend state.
    """

    async def request(self, headers: dict[str, str] | None = None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/patients", headers=headers or {})

    def _auth_client(self, email: str):
        user = SimpleNamespace(id="u-1", email=email)
        auth = _FakeAuth(user)
        return _FakeAuthClient(auth), auth

    async def test_unauthenticated_request_returns_401(self):
        response = await self.request()
        self.assertEqual(response.status_code, 401)

    async def test_authenticated_non_admin_returns_403(self):
        auth_client, _ = self._auth_client("patient@example.com")
        with (
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch("app.api.dependencies.settings.is_admin_email", return_value=False),
        ):
            response = await self.request({"Authorization": "Bearer valid-token"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Admin access required.")

    async def test_admin_returns_registry(self):
        auth_client, auth = self._auth_client("admin@hospital.in")
        query = _FakePatientQuery(
            [
                {
                    "id": "u-1",
                    "patient_code": "MG-001",
                    "full_name": "Admin View Patient",
                    "email": "p@example.com",
                    "phone": None,
                    "created_at": None,
                    "diagnosis": "Hypertension",
                }
            ]
        )
        database_client = _FakeDatabaseClient(query)
        with (
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch("app.api.dependencies.settings.is_admin_email", return_value=True),
            # The admin listing reads through the authenticated client so the
            # admin's JWT is forwarded to PostgREST and the patients_admin_select_all
            # RLS policy matches — so mock the authenticated client, not the anon one.
            patch("app.api.routers.patients.get_authenticated_supabase_client", return_value=database_client),
        ):
            response = await self.request({"Authorization": "Bearer valid-token"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "supabase")
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["patients"][0]["name"], "Admin View Patient")
        self.assertEqual(auth.tokens, ["valid-token"])


if __name__ == "__main__":
    import unittest

    unittest.main()
