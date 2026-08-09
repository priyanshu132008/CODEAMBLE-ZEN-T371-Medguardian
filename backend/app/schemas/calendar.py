"""Safe calendar connection response schema."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CalendarConnectionProfile(BaseModel):
    """Calendar connection metadata without any encrypted token material."""

    id: UUID
    user_id: UUID
    provider: str
    google_account_email: str | None = None
    calendar_id: str
    scopes: list[object] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CalendarStatusResponse(BaseModel):
    """Safe connection status for the patient portal.

    ``profile`` is the full safe metadata when connected, ``None`` otherwise. No
    token material (encrypted or otherwise) is ever present in either field.
    """

    connected: bool
    profile: CalendarConnectionProfile | None = None


class CalendarConnectResponse(BaseModel):
    """The Google consent URL the frontend navigates to."""

    authorization_url: str
