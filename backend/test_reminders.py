"""Tests for the medication-reminder pipeline: schedule parser, schedule hash,
reminder sync orchestration, and the protected reminder endpoints.

Google + Supabase are mocked — no network and no real credentials. The sync
service is exercised both directly (constructor-injected fakes) and through
the FastAPI app (``from main import app`` + ``httpx.ASGITransport``), the same
pattern the existing suites use. Existing assertions elsewhere are untouched.
"""

from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from uuid import UUID

import httpx

from app.api.dependencies import AuthenticatedUser
from app.services.google_calendar_service import (
    EventOpResult,
    GoogleCalendarErrorKind,
    RefreshResult,
)
from app.services.medication_schedule import (
    parse_duration,
    parse_frequency,
    parse_schedule,
)
from app.services.reminder_sync_service import (
    GoogleConnectionMissingError,
    GoogleConnectionRevokedError,
    ReminderSyncService,
    compute_schedule_hash,
)
from main import app

USER_ID = "11111111-1111-4111-8111-111111111111"
TODAY = date(2026, 1, 15)


# ---------------------------------------------------------------------------
# Schedule parser (pure / deterministic)
# ---------------------------------------------------------------------------


class ScheduleParserTests(unittest.TestCase):
    def _parse(self, frequency: str | None, duration: str | None = None):
        return parse_schedule(
            {"name": "Med", "frequency": frequency, "duration": duration},
            today=TODAY,
        )

    def test_once_daily_yields_single_morning_time(self):
        r = self._parse("once daily", "10 days")
        self.assertEqual([t.time for t in r.times], ["09:00"])
        self.assertTrue(r.recurring)
        self.assertFalse(r.prn)
        self.assertFalse(r.one_time)
        self.assertEqual(r.duration_days, 10)
        self.assertEqual(r.rrule, "FREQ=DAILY;COUNT=10")
        self.assertFalse(r.needs_review)
        self.assertEqual(r.start_date, TODAY)

    def test_twice_daily_yields_morning_and_night(self):
        r = self._parse("twice daily", "5 days")
        self.assertEqual([t.time for t in r.times], ["09:00", "21:00"])

    def test_three_times_daily_yields_three_slots(self):
        r = self._parse("three times daily", "7 days")
        self.assertEqual([t.time for t in r.times], ["08:00", "14:00", "20:00"])

    def test_four_times_daily_yields_four_slots(self):
        r = self._parse("four times daily", "7 days")
        self.assertEqual([t.time for t in r.times], ["08:00", "12:00", "16:00", "20:00"])

    def test_bedtime_yields_late_slot(self):
        r = self._parse("bedtime", "7 days")
        self.assertEqual([t.time for t in r.times], ["22:00"])

    def test_before_meals_yields_three_meal_slots(self):
        r = self._parse("before meals", "7 days")
        self.assertEqual([t.time for t in r.times], ["08:00", "12:00", "18:00"])

    def test_after_meals_yields_three_meal_slots(self):
        r = self._parse("after meals", "7 days")
        self.assertEqual([t.time for t in r.times], ["09:00", "13:00", "19:00"])

    def test_time_of_day_fragments(self):
        self.assertEqual([t.time for t in self._parse("morning", "7 days").times], ["09:00"])
        self.assertEqual([t.time for t in self._parse("afternoon", "7 days").times], ["14:00"])
        self.assertEqual([t.time for t in self._parse("evening", "7 days").times], ["20:00"])
        combined = self._parse("morning and evening", "7 days")
        self.assertEqual([t.time for t in combined.times], ["09:00", "20:00"])

    def test_prn_is_non_recurring_with_no_rrule(self):
        r = self._parse("as needed")
        self.assertEqual(r.times, [])
        self.assertTrue(r.prn)
        self.assertFalse(r.recurring)
        self.assertIsNone(r.rrule)
        self.assertFalse(r.needs_review)  # PRN with no duration is not flagged

    def test_stat_is_one_time_with_no_rrule(self):
        r = self._parse("immediately")
        self.assertEqual([t.time for t in r.times], ["09:00"])
        self.assertTrue(r.one_time)
        self.assertFalse(r.recurring)
        self.assertIsNone(r.rrule)
        self.assertFalse(r.needs_review)

    def test_raw_sigils_normalize(self):
        self.assertEqual([t.time for t in self._parse("OD", "7 days").times], ["09:00"])
        self.assertEqual([t.time for t in self._parse("BD", "7 days").times], ["09:00", "21:00"])
        self.assertEqual(
            [t.time for t in self._parse("TDS", "7 days").times], ["08:00", "14:00", "20:00"]
        )
        self.assertEqual(
            [t.time for t in self._parse("QID", "7 days").times],
            ["08:00", "12:00", "16:00", "20:00"],
        )
        self.assertEqual([t.time for t in self._parse("HS", "7 days").times], ["22:00"])

    def test_duration_bounds_and_capping(self):
        self.assertEqual(parse_duration("5 days"), (5, False))
        self.assertEqual(parse_duration("2 weeks"), (14, False))
        self.assertEqual(parse_duration("1 month"), (30, True))  # month→days is approximate
        self.assertEqual(parse_duration("3 months"), (90, True))
        # Missing duration → short safe fallback flagged for review.
        self.assertEqual(parse_duration(None), (7, True))
        self.assertEqual(parse_duration(""), (7, True))
        # Ambiguous bare integer → treated as days, flagged review.
        self.assertEqual(parse_duration("10"), (10, True))

    def test_missing_duration_flags_recurring_for_review(self):
        r = self._parse("once daily")  # no duration
        self.assertTrue(r.needs_review)
        self.assertEqual(r.rrule, "FREQ=DAILY;COUNT=7")  # bounded fallback

    def test_parser_is_deterministic(self):
        a = self._parse("twice daily", "10 days")
        b = self._parse("twice daily", "10 days")
        self.assertEqual([t.__dict__ for t in a.times], [t.__dict__ for t in b.times])
        self.assertEqual(a.rrule, b.rrule)
        self.assertEqual(a.schedule, b.schedule)

    def test_unrecognized_frequency_defaults_with_review(self):
        r = self._parse("whenever I feel like it", "7 days")
        # No recognizable token → defaults to a single morning slot flagged review.
        self.assertEqual([t.time for t in r.times], ["09:00"])
        self.assertTrue(r.needs_review)


# ---------------------------------------------------------------------------
# Schedule hash (idempotency anchor)
# ---------------------------------------------------------------------------


class ScheduleHashTests(unittest.TestCase):
    def test_case_and_whitespace_insensitive(self):
        h1 = compute_schedule_hash(
            patient_id="p1", med_name="  Amoxicillin  ", dosage="500 MG",
            frequency="OD", schedule_times=["09:00"],
        )
        h2 = compute_schedule_hash(
            patient_id="p1", med_name="amoxicillin", dosage="500 mg",
            frequency="once daily", schedule_times=["09:00"],
        )
        self.assertEqual(h1, h2)

    def test_schedule_order_insensitive(self):
        h1 = compute_schedule_hash(
            patient_id="p1", med_name="m", dosage="d", frequency="twice daily",
            schedule_times=["21:00", "09:00"],
        )
        h2 = compute_schedule_hash(
            patient_id="p1", med_name="m", dosage="d", frequency="twice daily",
            schedule_times=["09:00", "21:00"],
        )
        self.assertEqual(h1, h2)

    def test_patient_id_sensitive(self):
        h1 = compute_schedule_hash(patient_id="p1", med_name="m", dosage="d", frequency="once daily", schedule_times=["09:00"])
        h2 = compute_schedule_hash(patient_id="p2", med_name="m", dosage="d", frequency="once daily", schedule_times=["09:00"])
        self.assertNotEqual(h1, h2)

    def test_dosage_sensitive(self):
        h1 = compute_schedule_hash(patient_id="p1", med_name="m", dosage="500 mg", frequency="once daily", schedule_times=["09:00"])
        h2 = compute_schedule_hash(patient_id="p1", med_name="m", dosage="250 mg", frequency="once daily", schedule_times=["09:00"])
        self.assertNotEqual(h1, h2)

    def test_frequency_sigil_equivalence(self):
        h1 = compute_schedule_hash(patient_id="p1", med_name="m", dosage="d", frequency="BD", schedule_times=["09:00", "21:00"])
        h2 = compute_schedule_hash(patient_id="p1", med_name="m", dosage="d", frequency="twice daily", schedule_times=["09:00", "21:00"])
        self.assertEqual(h1, h2)


# ---------------------------------------------------------------------------
# Sync service (constructor-injected fakes + patched Supabase table)
# ---------------------------------------------------------------------------


class _FakeConnectionService:
    def __init__(self, refresh_token: str | None = "rt-123"):
        self.refresh_token = refresh_token
        self.saved: list[str | None] = []
        self.deleted = False

    def get_decrypted_refresh_token(self, **_kwargs) -> str | None:
        return self.refresh_token

    def save_google_connection(self, **kwargs):
        self.saved.append(kwargs.get("refresh_token"))
        return None

    def delete_google_connection(self, **_kwargs):
        self.deleted = True
        return True


class _FakeGoogleService:
    def __init__(
        self,
        *,
        access_token: str = "gt-access",
        create_ids: list[str] | None = None,
        refresh_error: GoogleCalendarErrorKind | None = None,
        create_error: GoogleCalendarErrorKind | None = None,
        update_error: GoogleCalendarErrorKind | None = None,
        delete_error: GoogleCalendarErrorKind | None = None,
        rotate: str | None = None,
    ):
        self.access_token = access_token
        self._create_ids = create_ids or ["evt-1"]
        self.refresh_error = refresh_error
        self.create_error = create_error
        self.update_error = update_error
        self.delete_error = delete_error
        self.rotate = rotate
        self.created_payloads: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.deleted_ids: list[str] = []
        self._idx = 0

    def refresh_access_token(self, *, refresh_token: str) -> RefreshResult:
        if self.refresh_error is not None:
            return RefreshResult(error=self.refresh_error)
        return RefreshResult(
            access_token=self.access_token,
            new_refresh_token=self.rotate or refresh_token,
        )

    def create_event(self, *, access_token: str, calendar_id: str, payload: dict) -> EventOpResult:
        self.created_payloads.append(payload)
        if self.create_error is not None:
            return EventOpResult(error=self.create_error)
        eid = self._create_ids[min(self._idx, len(self._create_ids) - 1)]
        self._idx += 1
        return EventOpResult(event_id=eid)

    def update_event(self, *, access_token: str, calendar_id: str, event_id: str, payload: dict) -> EventOpResult:
        self.updated.append((event_id, payload))
        if self.update_error is not None:
            return EventOpResult(error=self.update_error, event_id=None)
        return EventOpResult(event_id=event_id)

    def delete_event(self, *, access_token: str, calendar_id: str, event_id: str) -> EventOpResult:
        self.deleted_ids.append(event_id)
        if self.delete_error is not None:
            return EventOpResult(error=self.delete_error)
        return EventOpResult(event_id=event_id)


class _ReminderStore:
    """Shared backing store for the mocked medication_reminders table."""

    def __init__(self, existing: list[dict] | None = None):
        self.existing = list(existing or [])
        self.upserts: list[dict] = []
        self.updates: list[dict] = []
        self.deletes: list[dict] = []

    def query(self) -> "_FakeReminderQuery":
        return _FakeReminderQuery(self)


class _FakeReminderQuery:
    def __init__(self, store: _ReminderStore):
        self.store = store

    def select(self, _columns: str) -> "_FakeReminderQuery":
        return self

    def eq(self, _column: str, _value: object) -> "_FakeReminderQuery":
        return self

    def limit(self, _value: int) -> "_FakeReminderQuery":
        return self

    def order(self, _column: str, desc: bool = False) -> "_FakeReminderQuery":
        return self

    def upsert(self, row: dict, on_conflict: str | None = None) -> "_FakeReminderQuery":
        self.store.upserts.append(row)
        return self

    def update(self, payload: dict) -> "_FakeReminderQuery":
        self.store.updates.append(payload)
        return self

    def delete(self) -> "_FakeReminderQuery":
        self.store.deletes.append({"called": True})
        return self

    def execute(self):
        return SimpleNamespace(data=list(self.store.existing))


class _FakeDbClient:
    def __init__(self, store: _ReminderStore):
        self.store = store
        self.table_names: list[str] = []

    def table(self, name: str) -> _FakeReminderQuery:
        self.table_names.append(name)
        return self.store.query()


CURRENT_USER = AuthenticatedUser(user_id=USER_ID, email="patient@example.com")


class ReminderSyncServiceTests(unittest.TestCase):
    def _service(self, conn: _FakeConnectionService, google: _FakeGoogleService) -> ReminderSyncService:
        return ReminderSyncService(
            calendar_connection_service=conn,
            google_service=google,
        )

    def _patch_db(self, store: _ReminderStore):
        return patch(
            "app.services.reminder_sync_service.get_authenticated_supabase_client",
            return_value=_FakeDbClient(store),
        )

    def test_sync_creates_event_and_persists_row(self):
        conn = _FakeConnectionService()
        google = _FakeGoogleService(create_ids=["evt-1"])
        store = _ReminderStore(existing=[])
        service = self._service(conn, google)
        with self._patch_db(store):
            result = service.sync(
                current_user=CURRENT_USER,
                access_token="user-token",
                medications=[{"name": "Amoxicillin", "frequency": "once daily", "duration": "10 days"}],
                timezone="Asia/Kolkata",
                patient_id="p1",
                today=TODAY,
            )
        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["reminders"][0]["status"], "active")
        self.assertEqual(result["reminders"][0]["schedule"], [{"time": "09:00", "label": "morning"}])
        self.assertTrue(result["reminders"][0]["recurring"])
        self.assertEqual(len(store.upserts), 1)
        row = store.upserts[0]
        self.assertEqual(row["google_event_ids"], ["evt-1"])
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["medication_name"], "Amoxicillin")
        self.assertEqual(row["end_date"], str(date(2026, 1, 24)))  # today + 9 days
        # The upserted row never carries token material.
        self.assertNotIn("refresh_token", str(row))
        self.assertNotIn("access_token", str(row))

    def test_idempotent_resync_patches_existing_without_new_create(self):
        conn = _FakeConnectionService()
        google = _FakeGoogleService()
        store = _ReminderStore(existing=[{"id": "rid", "google_event_ids": ["evt-old"]}])
        service = self._service(conn, google)
        with self._patch_db(store):
            result = service.sync(
                current_user=CURRENT_USER,
                access_token="user-token",
                medications=[{"name": "Amoxicillin", "frequency": "once daily", "duration": "10 days"}],
                timezone="Asia/Kolkata",
                patient_id="p1",
                today=TODAY,
            )
        self.assertEqual(result["synced"], 1)
        # Existing event was PATCHed, never re-created.
        self.assertEqual(len(google.updated), 1)
        self.assertEqual(google.created_payloads, [])
        # The persisted event id is the existing one, not a fresh id.
        self.assertEqual(store.upserts[0]["google_event_ids"], ["evt-old"])

    def test_prn_medication_is_skipped_with_no_google_event(self):
        conn = _FakeConnectionService()
        google = _FakeGoogleService()
        store = _ReminderStore(existing=[])
        service = self._service(conn, google)
        with self._patch_db(store):
            result = service.sync(
                current_user=CURRENT_USER,
                access_token="user-token",
                medications=[{"name": "Ibuprofen", "frequency": "PRN"}],
                timezone="Asia/Kolkata",
                patient_id="p1",
                today=TODAY,
            )
        self.assertEqual(result["synced"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["reminders"][0]["status"], "skipped")
        self.assertEqual(google.created_payloads, [])
        self.assertEqual(google.updated, [])
        self.assertEqual(store.upserts[0]["google_event_ids"], [])
        self.assertEqual(store.upserts[0]["status"], "skipped")

    def test_invalid_grant_disconnects_connection_and_raises(self):
        conn = _FakeConnectionService()
        google = _FakeGoogleService(refresh_error=GoogleCalendarErrorKind.INVALID_GRANT)
        store = _ReminderStore(existing=[])
        service = self._service(conn, google)
        with self._patch_db(store):
            with self.assertRaises(GoogleConnectionRevokedError):
                service.sync(
                    current_user=CURRENT_USER,
                    access_token="user-token",
                    medications=[{"name": "M", "frequency": "once daily", "duration": "5 days"}],
                    timezone="Asia/Kolkata",
                    patient_id="p1",
                    today=TODAY,
                )
        self.assertTrue(conn.deleted)

    def test_missing_connection_raises_missing_error(self):
        conn = _FakeConnectionService(refresh_token=None)
        google = _FakeGoogleService()
        service = self._service(conn, google)
        with self.assertRaises(GoogleConnectionMissingError):
            service.sync(
                current_user=CURRENT_USER,
                access_token="user-token",
                medications=[{"name": "M", "frequency": "once daily", "duration": "5 days"}],
                timezone="Asia/Kolkata",
                patient_id="p1",
                today=TODAY,
            )

    def test_rate_limit_error_records_no_event_id(self):
        conn = _FakeConnectionService()
        google = _FakeGoogleService(create_error=GoogleCalendarErrorKind.RATE_LIMITED)
        store = _ReminderStore(existing=[])
        service = self._service(conn, google)
        with self._patch_db(store):
            result = service.sync(
                current_user=CURRENT_USER,
                access_token="user-token",
                medications=[{"name": "M", "frequency": "once daily", "duration": "5 days"}],
                timezone="Asia/Kolkata",
                patient_id="p1",
                today=TODAY,
            )
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["reminders"][0]["status"], "error")
        self.assertEqual(result["reminders"][0]["error"], "google:rate_limited")
        # No event id persisted for the failed slot so a re-sync recreates it.
        self.assertEqual(store.upserts[0]["google_event_ids"], [None])

    def test_google_404_on_update_falls_back_to_create(self):
        conn = _FakeConnectionService()
        google = _FakeGoogleService(create_ids=["evt-new"], update_error=GoogleCalendarErrorKind.NOT_FOUND)
        store = _ReminderStore(existing=[{"id": "rid", "google_event_ids": ["evt-old"]}])
        service = self._service(conn, google)
        with self._patch_db(store):
            result = service.sync(
                current_user=CURRENT_USER,
                access_token="user-token",
                medications=[{"name": "M", "frequency": "once daily", "duration": "5 days"}],
                timezone="Asia/Kolkata",
                patient_id="p1",
                today=TODAY,
            )
        self.assertEqual(result["synced"], 1)
        # update returned 404 → fallback create produced a new event id.
        self.assertEqual(len(google.updated), 1)
        self.assertEqual(len(google.created_payloads), 1)
        self.assertEqual(store.upserts[0]["google_event_ids"], ["evt-new"])

    def test_rotation_persists_new_refresh_token(self):
        conn = _FakeConnectionService()
        google = _FakeGoogleService(rotate="rt-rotated")
        store = _ReminderStore(existing=[])
        service = self._service(conn, google)
        with self._patch_db(store):
            service.sync(
                current_user=CURRENT_USER,
                access_token="user-token",
                medications=[{"name": "M", "frequency": "once daily", "duration": "5 days"}],
                timezone="Asia/Kolkata",
                patient_id="p1",
                today=TODAY,
            )
        self.assertEqual(conn.saved, ["rt-rotated"])

    def test_no_token_material_in_sync_outcome(self):
        conn = _FakeConnectionService()
        google = _FakeGoogleService(access_token="SECRET-GOOGLE-ACCESS")
        store = _ReminderStore(existing=[])
        service = self._service(conn, google)
        with self._patch_db(store):
            result = service.sync(
                current_user=CURRENT_USER,
                access_token="SECRET-USER-TOKEN",
                medications=[{"name": "M", "frequency": "once daily", "duration": "5 days"}],
                timezone="Asia/Kolkata",
                patient_id="p1",
                today=TODAY,
            )
        blob = str(result) + str(store.upserts)
        self.assertNotIn("SECRET-GOOGLE-ACCESS", blob)
        self.assertNotIn("SECRET-USER-TOKEN", blob)
        self.assertNotIn("rt-123", blob)


# ---------------------------------------------------------------------------
# Reminder endpoints (httpx + mocked auth + mocked services)
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


class ReminderEndpointTests(IsolatedAsyncioTestCase):
    async def _client(self):
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    async def test_sync_unauthenticated_returns_401(self):
        async with await self._client() as client:
            response = await client.post(
                "/api/calendar/reminders/sync",
                json={"medications": [{"name": "M"}], "timezone": "Asia/Kolkata"},
            )
        self.assertEqual(response.status_code, 401)

    async def test_sync_invalid_timezone_returns_422(self):
        auth_client, _ = _auth_client()
        with patch("app.api.dependencies.get_supabase_client", return_value=auth_client):
            async with await self._client() as client:
                response = await client.post(
                    "/api/calendar/reminders/sync",
                    json={"medications": [{"name": "M", "frequency": "once daily"}], "timezone": "Not/A_TZ"},
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 422)
        self.assertIn("timezone", response.json()["detail"].lower())

    async def test_sync_no_connection_returns_409(self):
        auth_client, _ = _auth_client()
        conn = _FakeConnectionService(refresh_token=None)
        google = _FakeGoogleService()
        store = _ReminderStore()
        with (
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch("app.services.reminder_sync_service.CalendarConnectionService", return_value=conn),
            patch("app.services.reminder_sync_service.GoogleCalendarService", return_value=google),
            patch(
                "app.services.reminder_sync_service.get_authenticated_supabase_client",
                return_value=_FakeDbClient(store),
            ),
        ):
            async with await self._client() as client:
                response = await client.post(
                    "/api/calendar/reminders/sync",
                    json={"medications": [{"name": "M", "frequency": "once daily", "duration": "5 days"}], "timezone": "Asia/Kolkata"},
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 409)

    async def test_sync_revoked_connection_returns_401(self):
        auth_client, _ = _auth_client()
        conn = _FakeConnectionService()
        google = _FakeGoogleService(refresh_error=GoogleCalendarErrorKind.INVALID_GRANT)
        store = _ReminderStore()
        with (
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch("app.services.reminder_sync_service.CalendarConnectionService", return_value=conn),
            patch("app.services.reminder_sync_service.GoogleCalendarService", return_value=google),
            patch(
                "app.services.reminder_sync_service.get_authenticated_supabase_client",
                return_value=_FakeDbClient(store),
            ),
        ):
            async with await self._client() as client:
                response = await client.post(
                    "/api/calendar/reminders/sync",
                    json={"medications": [{"name": "M", "frequency": "once daily", "duration": "5 days"}], "timezone": "Asia/Kolkata"},
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 401)
        self.assertTrue(conn.deleted)

    async def test_sync_success_returns_outcomes_without_tokens(self):
        auth_client, auth = _auth_client()
        conn = _FakeConnectionService()
        google = _FakeGoogleService(access_token="SECRET-GOOGLE-ACCESS", create_ids=["evt-9"])
        store = _ReminderStore(existing=[])
        with (
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch("app.services.reminder_sync_service.CalendarConnectionService", return_value=conn),
            patch("app.services.reminder_sync_service.GoogleCalendarService", return_value=google),
            patch(
                "app.services.reminder_sync_service.get_authenticated_supabase_client",
                return_value=_FakeDbClient(store),
            ),
        ):
            async with await self._client() as client:
                response = await client.post(
                    "/api/calendar/reminders/sync",
                    json={
                        "medications": [{"name": "Amoxicillin", "frequency": "once daily", "duration": "10 days"}],
                        "timezone": "Asia/Kolkata",
                        "patient_id": "p1",
                    },
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["synced"], 1)
        self.assertEqual(body["reminders"][0]["status"], "active")
        self.assertEqual(body["reminders"][0]["schedule"], [{"time": "09:00", "label": "morning"}])
        # The Supabase access token used for the request is not echoed, and no
        # Google token material leaks into the response body.
        self.assertNotIn("valid-token", response.text)
        self.assertNotIn("SECRET-GOOGLE-ACCESS", response.text)
        self.assertNotIn("rt-123", response.text)
        self.assertEqual(auth.tokens, ["valid-token"])
        # The request never trusted a frontend user_id; ownership came from auth.
        self.assertEqual(store.upserts[0]["user_id"], USER_ID)

    async def test_list_unauthenticated_returns_401(self):
        async with await self._client() as client:
            response = await client.get("/api/calendar/reminders")
        self.assertEqual(response.status_code, 401)

    async def test_list_returns_own_reminders(self):
        auth_client, _ = _auth_client()
        row = {
            "id": "33333333-3333-4333-8333-333333333333",
            "medication_name": "Amoxicillin",
            "dosage": "500 mg",
            "frequency": "once daily",
            "schedule_json": [{"time": "09:00", "label": "morning"}],
            "google_event_ids": ["evt-1"],
            "status": "active",
            "needs_review": False,
            "recurring": True,
            "start_date": "2026-01-15",
            "end_date": "2026-01-24",
            "timezone": "Asia/Kolkata",
        }
        store = _ReminderStore(existing=[row])
        with (
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch(
                "app.services.reminder_sync_service.get_authenticated_supabase_client",
                return_value=_FakeDbClient(store),
            ),
        ):
            async with await self._client() as client:
                response = await client.get(
                    "/api/calendar/reminders",
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["reminders"][0]["medication_name"], "Amoxicillin")
        self.assertEqual(body["reminders"][0]["google_event_ids"], ["evt-1"])
        # UUID + date are coerced by the response model.
        self.assertEqual(
            UUID(body["reminders"][0]["id"]),
            UUID("33333333-3333-4333-8333-333333333333"),
        )

    async def test_list_empty_returns_zero(self):
        auth_client, _ = _auth_client()
        store = _ReminderStore(existing=[])
        with (
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch(
                "app.services.reminder_sync_service.get_authenticated_supabase_client",
                return_value=_FakeDbClient(store),
            ),
        ):
            async with await self._client() as client:
                response = await client.get(
                    "/api/calendar/reminders",
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"reminders": [], "count": 0})

    async def test_delete_own_reminder_returns_204(self):
        auth_client, _ = _auth_client()
        conn = _FakeConnectionService()
        google = _FakeGoogleService()
        row = {"id": "rid", "google_event_ids": ["evt-1"]}
        store = _ReminderStore(existing=[row])
        with (
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch("app.services.reminder_sync_service.CalendarConnectionService", return_value=conn),
            patch("app.services.reminder_sync_service.GoogleCalendarService", return_value=google),
            patch(
                "app.services.reminder_sync_service.get_authenticated_supabase_client",
                return_value=_FakeDbClient(store),
            ),
        ):
            async with await self._client() as client:
                response = await client.delete(
                    "/api/calendar/reminders/rid",
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(google.deleted_ids, ["evt-1"])

    async def test_delete_other_users_reminder_returns_404(self):
        auth_client, _ = _auth_client()
        store = _ReminderStore(existing=[])  # not found for this user
        with (
            patch("app.api.dependencies.get_supabase_client", return_value=auth_client),
            patch(
                "app.services.reminder_sync_service.get_authenticated_supabase_client",
                return_value=_FakeDbClient(store),
            ),
        ):
            async with await self._client() as client:
                response = await client.delete(
                    "/api/calendar/reminders/rid",
                    headers={"Authorization": "Bearer valid-token"},
                )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()