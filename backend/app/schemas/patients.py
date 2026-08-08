"""Patient API response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PatientProfile(BaseModel):
    """Safe patient profile fields exposed to the authenticated patient."""

    id: UUID
    patient_code: str
    full_name: str
    email: str
    phone: str | None = None
    created_at: datetime | None = None
