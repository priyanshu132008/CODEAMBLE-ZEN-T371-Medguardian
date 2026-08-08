"""Patient persistence operations."""

from __future__ import annotations

from app.db.supabase_client import get_authenticated_supabase_client
from app.schemas.patients import PatientProfile


PATIENT_PROFILE_COLUMNS = "id, patient_code, full_name, email, phone, created_at"


def get_patient_profile(
    *,
    user_id: str,
    access_token: str,
) -> PatientProfile | None:
    """Load the patient row belonging to the authenticated Supabase user.

    The query deliberately filters on ``patients.id`` only. The supplied
    access token is forwarded to PostgREST so the database's existing RLS
    policy can enforce ``auth.uid() = id``.
    """
    client = get_authenticated_supabase_client(access_token)
    response = (
        client.table("patients")
        .select(PATIENT_PROFILE_COLUMNS)
        .eq("id", user_id)
        .limit(1)
        .execute()
    )

    rows = response.data or []
    if not rows:
        return None

    return PatientProfile.model_validate(rows[0])
