"""Protected medication-reminder endpoints.

Routes (prefix ``/api/calendar/reminders``):

- ``POST /sync``  — parse each medication, create/PATCH Google Calendar events,
  and persist idempotent reminder rows.
- ``GET  /``     — list the authenticated user's reminder rows (RLS-protected).
- ``DELETE /{id}`` — delete the caller's own reminder + best-effort Google delete.

Every route derives identity from ``get_current_user`` /
``get_current_access_token``; no frontend-supplied ``user_id`` or ``patient_id``
is ever trusted for ownership — ownership is enforced by Supabase RLS on
``user_id``. No token material appears in any request or response model.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    AuthenticatedUser,
    get_current_access_token,
    get_current_user,
)
from app.schemas.reminders import (
    ReminderItem,
    ReminderListResponse,
    ReminderSyncRequest,
    ReminderSyncResponse,
    ReminderTimeSpec,
)
from app.services.reminder_sync_service import (
    GoogleConnectionMissingError,
    GoogleConnectionRevokedError,
    ReminderSyncService,
)

router = APIRouter(prefix="/api/calendar/reminders", tags=["reminders"])


def _row_to_item(row: dict) -> ReminderItem:
    schedule_raw = row.get("schedule_json") or []
    schedule = [
        ReminderTimeSpec(time=entry.get("time", ""), label=entry.get("label", ""))
        for entry in schedule_raw
        if isinstance(entry, dict)
    ]
    ids = row.get("google_event_ids") or []
    return ReminderItem(
        id=row.get("id"),
        medication_name=row.get("medication_name") or "",
        dosage=row.get("dosage"),
        frequency=row.get("frequency"),
        schedule=schedule,
        google_event_ids=[str(x) for x in ids if x] if isinstance(ids, list) else [],
        status=row.get("status") or "active",
        needs_review=bool(row.get("needs_review")),
        recurring=bool(row.get("recurring")),
        start_date=row.get("start_date"),
        end_date=row.get("end_date"),
        timezone=row.get("timezone") or "",
    )


@router.post("/sync", response_model=ReminderSyncResponse)
def sync_reminders(
    request: ReminderSyncRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    access_token: str = Depends(get_current_access_token),
) -> ReminderSyncResponse:
    """Create or update Google Calendar reminders for the supplied medications."""
    # Validate the IANA timezone before doing any work.
    try:
        ZoneInfo(request.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="timezone must be a valid IANA timezone (e.g. Asia/Kolkata).",
        )

    service = ReminderSyncService()
    try:
        result = service.sync(
            current_user=current_user,
            access_token=access_token,
            medications=[m.model_dump() for m in request.medications],
            timezone=request.timezone,
            patient_id=request.patient_id,
            today=date.today(),
        )
    except GoogleConnectionMissingError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect your Google Calendar before syncing reminders.",
        )
    except GoogleConnectionRevokedError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your Google Calendar connection was revoked. Please reconnect.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ReminderSyncResponse(**result)


@router.get("", response_model=ReminderListResponse)
def list_reminders(
    current_user: AuthenticatedUser = Depends(get_current_user),
    access_token: str = Depends(get_current_access_token),
) -> ReminderListResponse:
    """List the authenticated user's reminder rows."""
    rows = ReminderSyncService().list_reminders(
        current_user=current_user,
        access_token=access_token,
    )
    reminders = [_row_to_item(r) for r in rows]
    return ReminderListResponse(reminders=reminders, count=len(reminders))


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reminder(
    reminder_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    access_token: str = Depends(get_current_access_token),
) -> None:
    """Delete the caller's own reminder row (404 if it is not theirs)."""
    deleted = ReminderSyncService().delete_reminder(
        current_user=current_user,
        access_token=access_token,
        reminder_id=reminder_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reminder not found for the authenticated user.",
        )
    return None