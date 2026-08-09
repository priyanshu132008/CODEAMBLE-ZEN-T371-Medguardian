"""Pydantic schemas for the medication-reminder routes.

No schema exposes token material of any kind — encrypted or plaintext. The
frontend never sees a refresh token, access token, client secret, or the
service-role key through these models.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class MedicationInput(BaseModel):
    """One medication as supplied by the patient portal for reminder sync."""

    name: str
    dosage: str | None = None
    frequency: str | None = None
    duration: str | None = None


class ReminderTimeSpec(BaseModel):
    time: str  # "HH:MM"
    label: str


class ReminderItem(BaseModel):
    """A persisted reminder row (no token material)."""

    id: UUID
    medication_name: str
    dosage: str | None = None
    frequency: str | None = None
    schedule: list[ReminderTimeSpec] = Field(default_factory=list)
    google_event_ids: list[str] = Field(default_factory=list)
    status: str
    needs_review: bool
    recurring: bool
    start_date: date
    end_date: date | None = None
    timezone: str


class ReminderSyncRequest(BaseModel):
    """Body of POST /api/calendar/reminders/sync."""

    medications: list[MedicationInput]
    timezone: str
    patient_id: str | None = None


class MedicationSyncOutcome(BaseModel):
    """Per-medication outcome within a sync response."""

    medication_name: str
    status: str  # active | skipped | error
    needs_review: bool
    recurring: bool
    schedule: list[ReminderTimeSpec] = Field(default_factory=list)
    error: str | None = None


class ReminderSyncResponse(BaseModel):
    """Aggregate result of a sync."""

    synced: int
    skipped: int
    errors: int
    reminders: list[MedicationSyncOutcome]


class ReminderListResponse(BaseModel):
    reminders: list[ReminderItem]
    count: int