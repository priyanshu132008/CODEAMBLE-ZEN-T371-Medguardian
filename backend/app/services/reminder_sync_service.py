"""Sync medication reminders into Google Calendar + the medication_reminders table.

Keeps the reminder router thin: owns the schedule-hash lookup, the Google event
create-or-PATCH idempotency, token rotation persistence, and per-medication
error recording. All Supabase writes go through the authenticated client so
RLS (``auth.uid() = user_id``) enforces ownership; the user_id is taken from the
authenticated request, never from the frontend.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from app.api.dependencies import AuthenticatedUser
from app.db.supabase_client import get_authenticated_supabase_client
from app.services.calendar_connection_service import CalendarConnectionService
from app.services.google_calendar_service import (
    GoogleCalendarErrorKind,
    GoogleCalendarService,
    build_event_payload,
)
from app.services.medication_schedule import (
    ScheduleResult,
    parse_schedule,
    normalize_frequency,
)

_TABLE = "medication_reminders"
_CALENDAR_ID = "primary"


class GoogleConnectionMissingError(RuntimeError):
    """Raised when the user has no Google Calendar connection."""


class GoogleConnectionRevokedError(RuntimeError):
    """Raised when Google rejects the refresh token (invalid_grant)."""


def compute_schedule_hash(
    *,
    patient_id: str | None,
    med_name: str | None,
    dosage: str | None,
    frequency: str | None,
    schedule_times: list[str],
) -> str:
    """Stable SHA-256 over a canonical, case/whitespace/order-insensitive form.

    ``patient_id`` and ``dosage`` are part of the key so the same drug at a
    different dose (or for a different patient session) yields a distinct
    reminder; the schedule list is sorted so reordering does not change the hash.
    """
    canonical = {
        "patient_id": (patient_id or "").strip().lower(),
        "name": (med_name or "").strip().lower(),
        "dosage": (dosage or "").strip().lower(),
        "frequency": normalize_frequency(frequency),
        "schedule": sorted(schedule_times),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReminderSyncService:
    """Orchestrates Google Calendar reminder creation + persistence."""

    def __init__(
        self,
        *,
        calendar_connection_service: CalendarConnectionService | None = None,
        google_service: GoogleCalendarService | None = None,
    ) -> None:
        self._connections = calendar_connection_service or CalendarConnectionService()
        self._google = google_service or GoogleCalendarService()

    # -- Supabase helpers --------------------------------------------------

    def _table(self, access_token: str):
        return get_authenticated_supabase_client(access_token).table(_TABLE)

    @staticmethod
    def _row_to_event_ids(row: dict[str, Any]) -> list[str]:
        ids = row.get("google_event_ids") or []
        if isinstance(ids, list):
            return [str(x) for x in ids if x]
        return []

    # -- Public API --------------------------------------------------------

    def sync(
        self,
        *,
        current_user: AuthenticatedUser,
        access_token: str,
        medications: list[Any],
        timezone: str,
        patient_id: str | None,
        today: date,
    ) -> dict[str, Any]:
        """Sync every medication, returning aggregate + per-med outcomes."""
        refresh_token = self._connections.get_decrypted_refresh_token(
            current_user=current_user,
            access_token=access_token,
        )
        if not refresh_token:
            raise GoogleConnectionMissingError("No Google Calendar connection.")

        google_access = self._refresh_or_revoke(
            current_user=current_user,
            access_token=access_token,
            refresh_token=refresh_token,
        )

        outcomes: list[dict[str, Any]] = []
        synced = skipped = errors = 0

        for med in medications:
            outcome = self._sync_one(
                current_user=current_user,
                access_token=access_token,
                google_access=google_access,
                med=med,
                timezone=timezone,
                patient_id=patient_id,
                today=today,
            )
            outcomes.append(outcome)
            status = outcome["status"]
            if status == "skipped":
                skipped += 1
            elif status == "active":
                synced += 1
            else:
                errors += 1

        return {
            "synced": synced,
            "skipped": skipped,
            "errors": errors,
            "reminders": outcomes,
        }

    # -- Internals ---------------------------------------------------------

    def _refresh_or_revoke(
        self,
        *,
        current_user: AuthenticatedUser,
        access_token: str,
        refresh_token: str,
    ) -> str:
        """Refresh the Google access token; persist rotation; revoke on any rejection.

        Google's token endpoint returns ``invalid_grant`` when the refresh
        token was explicitly revoked. It returns 401/403 (``UNAUTHORIZED``)
        when the client credentials are stale, the refresh token has been
        disabled out-of-band (e.g. password reset, app revoked in Google
        account security), or the project's OAuth consent screen is in a
        state Google won't honor. Both conditions mean the same thing for
        us: the stored connection is dead and the user must reconnect.
        """
        refresh = self._google.refresh_access_token(refresh_token=refresh_token)
        # Any rejection — invalid_grant OR unauthorized OR network — drops
        # the local connection so the portal re-surfaces the Connect flow.
        # The frontend distinguishes "must reconnect" (401) from "Google
        # temporarily down" (5xx / network) so the patient gets the right
        # recovery CTA.
        is_revoked = refresh.error == GoogleCalendarErrorKind.INVALID_GRANT
        is_unauthorized = refresh.error == GoogleCalendarErrorKind.UNAUTHORIZED
        if (is_revoked or is_unauthorized) or not refresh.access_token:
            try:
                self._connections.delete_google_connection(
                    current_user=current_user,
                    access_token=access_token,
                )
            except Exception:  # noqa: BLE101 - best-effort cleanup
                pass
            if is_revoked:
                raise GoogleConnectionRevokedError("Google connection was revoked.")
            if is_unauthorized:
                raise GoogleConnectionRevokedError(
                    "Google rejected the connection (token expired or revoked)."
                )
            # No access token and no recognised error — treat as revoked
            # so the patient sees the Reconnect CTA rather than a confusing
            # empty error.
            raise GoogleConnectionRevokedError(
                "Google Calendar could not refresh the connection."
            )
        # Google occasionally rotates the refresh token; persist the new one.
        if refresh.new_refresh_token and refresh.new_refresh_token != refresh_token:
            try:
                self._connections.save_google_connection(
                    current_user=current_user,
                    access_token=access_token,
                    refresh_token=refresh.new_refresh_token,
                )
            except Exception:  # noqa: BLE101 - rotation persistence is best-effort
                pass
        return refresh.access_token

    def _sync_one(
        self,
        *,
        current_user: AuthenticatedUser,
        access_token: str,
        google_access: str,
        med: Any,
        timezone: str,
        patient_id: str | None,
        today: date,
    ) -> dict[str, Any]:
        name = _get(med, "name") or "Unknown medication"
        dosage = _get(med, "dosage")
        frequency = _get(med, "frequency")

        schedule: ScheduleResult = parse_schedule(med, today=today)
        schedule_times = [t.time for t in schedule.times]
        schedule_hash = compute_schedule_hash(
            patient_id=patient_id,
            med_name=name,
            dosage=dosage,
            frequency=frequency,
            schedule_times=schedule_times,
        )

        existing = self._find_existing(
            access_token=access_token,
            user_id=current_user.user_id,
            schedule_hash=schedule_hash,
        )

        # PRN medications are skipped — no recurring reminder, no Google event.
        if schedule.prn:
            self._upsert_row(
                access_token=access_token,
                current_user=current_user,
                patient_id=patient_id,
                name=name,
                dosage=dosage,
                frequency=frequency,
                schedule=schedule,
                schedule_hash=schedule_hash,
                event_ids=[],
                status="skipped",
                timezone=timezone,
                end_date=None,
            )
            return {
                "medication_name": name,
                "status": "skipped",
                "needs_review": schedule.needs_review,
                "recurring": False,
                "schedule": [t.__dict__ for t in schedule.times],
                "error": None,
            }

        event_ids, event_status, event_error = self._sync_events(
            google_access=google_access,
            schedule=schedule,
            med_name=name,
            dosage=dosage,
            timezone=timezone,
            existing_ids=self._row_to_event_ids(existing or {}),
        )

        self._upsert_row(
            access_token=access_token,
            current_user=current_user,
            patient_id=patient_id,
            name=name,
            dosage=dosage,
            frequency=frequency,
            schedule=schedule,
            schedule_hash=schedule_hash,
            event_ids=event_ids,
            status=event_status,
            timezone=timezone,
            end_date=self._end_date(schedule, today),
        )

        return {
            "medication_name": name,
            "status": event_status,
            "needs_review": schedule.needs_review,
            "recurring": schedule.recurring,
            "schedule": [t.__dict__ for t in schedule.times],
            "error": event_error,
        }

    def _sync_events(
        self,
        *,
        google_access: str,
        schedule: ScheduleResult,
        med_name: str,
        dosage: str | None,
        timezone: str,
        existing_ids: list[str],
    ) -> tuple[list[str], str, str | None]:
        """Create or PATCH one Google event per scheduled time.

        Returns (event_ids, status, error_message). On a transient Google
        failure for a time, that slot's id is recorded as None and the overall
        status becomes ``error`` — but the row still persists so a re-sync can
        PATCH the slots that did succeed.
        """
        tz = ZoneInfo(timezone)
        recurrence = [schedule.rrule] if schedule.rrule else None
        event_ids: list[str] = []
        had_error = False
        first_error: str | None = None

        for idx, sched_time in enumerate(schedule.times):
            hh, mm = (int(x) for x in sched_time.time.split(":"))
            start_dt = datetime.combine(schedule.start_date, time(hh, mm), tzinfo=tz)
            payload = build_event_payload(
                med_name=med_name,
                dosage=dosage,
                schedule_label=sched_time.label,
                start_dt=start_dt,
                timezone=timezone,
                recurrence=recurrence,
            )

            existing_id = existing_ids[idx] if idx < len(existing_ids) else None
            event_id, err = self._create_or_update(
                google_access=google_access,
                existing_id=existing_id,
                payload=payload,
            )
            event_ids.append(event_id)
            if err is not None:
                had_error = True
                if first_error is None:
                    first_error = err

        status = "error" if had_error else "active"
        return event_ids, status, first_error

    def _create_or_update(
        self,
        *,
        google_access: str,
        existing_id: str | None,
        payload: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        """PATCH an existing event, falling back to create on Google 404."""
        if existing_id:
            result = self._google.update_event(
                access_token=google_access,
                calendar_id=_CALENDAR_ID,
                event_id=existing_id,
                payload=payload,
            )
            if result.error == GoogleCalendarErrorKind.NOT_FOUND:
                # Event was deleted out-of-band — recreate and capture the new id.
                created = self._google.create_event(
                    access_token=google_access, calendar_id=_CALENDAR_ID, payload=payload
                )
                return (created.event_id, _maybe_error(created.error))
            if result.error is not None:
                # Rate-limited / network / unauthorized: keep no id for this slot
                # so a later re-sync can recreate it cleanly.
                return (None, _maybe_error(result.error))
            return (result.event_id, None)

        created = self._google.create_event(
            access_token=google_access, calendar_id=_CALENDAR_ID, payload=payload
        )
        return (created.event_id, _maybe_error(created.error))

    # -- Persistence -------------------------------------------------------

    def _find_existing(
        self, *, access_token: str, user_id: str, schedule_hash: str
    ) -> dict[str, Any] | None:
        response = (
            self._table(access_token)
            .select("id, google_event_ids")
            .eq("user_id", user_id)
            .eq("schedule_hash", schedule_hash)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        return rows[0] if rows else None

    def _upsert_row(
        self,
        *,
        access_token: str,
        current_user: AuthenticatedUser,
        patient_id: str | None,
        name: str,
        dosage: str | None,
        frequency: str | None,
        schedule: ScheduleResult,
        schedule_hash: str,
        event_ids: list[str],
        status: str,
        timezone: str,
        end_date: date | None,
    ) -> None:
        row = {
            "user_id": current_user.user_id,
            "patient_id": patient_id,
            "medication_name": name,
            "dosage": dosage,
            "frequency": frequency,
            "schedule_json": [t.__dict__ for t in schedule.times],
            "google_event_ids": event_ids,
            "calendar_id": _CALENDAR_ID,
            "start_date": str(schedule.start_date),
            "end_date": str(end_date) if end_date else None,
            "status": status,
            "schedule_hash": schedule_hash,
            "needs_review": schedule.needs_review,
            "recurring": schedule.recurring,
            "timezone": timezone,
        }
        self._table(access_token).upsert(row, on_conflict="user_id,schedule_hash").execute()

    @staticmethod
    def _end_date(schedule: ScheduleResult, today: date) -> date | None:
        if not schedule.recurring or schedule.duration_days <= 0:
            return None
        from datetime import timedelta

        return today + timedelta(days=schedule.duration_days - 1)

    # -- List / delete (used by the router) --------------------------------

    def mark_reminders_disconnected(
        self, *, current_user: AuthenticatedUser, access_token: str
    ) -> None:
        """Mark the caller's reminder rows as disconnected after a Google disconnect.

        Best-effort: a Supabase failure here must not block the disconnect.
        """
        try:
            self._table(access_token).update({"status": "disconnected"}).eq(
                "user_id", current_user.user_id
            ).execute()
        except Exception:  # noqa: BLE101 - best-effort
            pass

    def list_reminders(
        self, *, current_user: AuthenticatedUser, access_token: str
    ) -> list[dict[str, Any]]:
        response = (
            self._table(access_token)
            .select(
                "id, medication_name, dosage, frequency, schedule_json, "
                "google_event_ids, status, needs_review, recurring, "
                "start_date, end_date, timezone"
            )
            .eq("user_id", current_user.user_id)
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        )
        return getattr(response, "data", None) or []

    def delete_reminder(
        self,
        *,
        current_user: AuthenticatedUser,
        access_token: str,
        reminder_id: str,
    ) -> bool:
        """Delete the caller's own reminder row + best-effort Google event delete."""
        response = (
            self._table(access_token)
            .select("id, google_event_ids")
            .eq("user_id", current_user.user_id)
            .eq("id", reminder_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if not rows:
            return False
        event_ids = self._row_to_event_ids(rows[0])
        # Best-effort revoke of the access token to delete events. A missing
        # connection or revoked token must not block the local delete.
        try:
            refresh_token = self._connections.get_decrypted_refresh_token(
                current_user=current_user,
                access_token=access_token,
            )
            if refresh_token:
                refresh = self._google.refresh_access_token(refresh_token=refresh_token)
                if refresh.access_token:
                    for event_id in event_ids:
                        self._google.delete_event(
                            access_token=refresh.access_token,
                            calendar_id=_CALENDAR_ID,
                            event_id=event_id,
                        )
        except Exception:  # noqa: BLE101 - remote delete is best-effort
            pass

        self._table(access_token).delete().eq("user_id", current_user.user_id).eq(
            "id", reminder_id
        ).execute()
        return True


def _get(obj: Any, key: str) -> str | None:
    if obj is None:
        return None
    if isinstance(obj, dict):
        value = obj.get(key)
    else:
        value = getattr(obj, key, None)
    return None if value is None else str(value)


def _maybe_error(error: GoogleCalendarErrorKind | None) -> str | None:
    return None if error is None else f"google:{error.value}"