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
