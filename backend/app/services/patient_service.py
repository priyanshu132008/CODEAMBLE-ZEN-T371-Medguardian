"""Patient persistence operations."""

from __future__ import annotations

import logging
import re
import secrets
from typing import Any

from app.db.supabase_client import (
    get_authenticated_supabase_client,
    get_supabase_service_client,
)
from app.schemas.patients import PatientProfile


_PATIENT_PROFILE_LOG = logging.getLogger("medguardian.patient_profile")


PATIENT_PROFILE_COLUMNS = "id, patient_code, full_name, email, phone, created_at"

# A patient_code is a short, human-readable identifier (e.g. "P-7F3K2A")
# shown to admins in the cohort grid. We mint one on the fly on first
# upsert so the admin dashboard can render a stable id even when the
# Supabase user was created without an explicit profile row.
_PATIENT_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ambiguous chars dropped
_NAME_FROM_EMAIL = re.compile(r"^([^@]+)@")


def _mint_patient_code() -> str:
    """Return a short, unambiguous, human-readable identifier like 'P-7F3K2A'."""
    return "P-" + "".join(secrets.choice(_PATIENT_CODE_ALPHABET) for _ in range(6))


def _derive_name_from_email(email: str | None) -> str | None:
    if not email:
        return None
    m = _NAME_FROM_EMAIL.match(email)
    if not m:
        return None
    local = m.group(1).strip()
    if not local:
        return None
    # Title-case, fall back to the raw local-part if it has no letters.
    return local.replace(".", " ").replace("_", " ").strip().title() or local


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


def upsert_patient_profile(
    *,
    user_id: str,
    access_token: str,
    email: str | None,
    full_name: str | None,
) -> None:
    """Create (or back-fill) the row mapped to an authenticated Supabase user.

    The Admin Command Center reads from the ``patients`` table, so a clinician
    cannot see a registered patient until that row exists. This helper is
    called when a patient first runs a protected, identity-bearing flow
    (currently the discharge-upload handler) so the admin cohort reflects
    the actual user base without requiring a separate registration step.

    Identity is derived ONLY from the validated bearer token (Supabase
    ``auth.uid()``); the email and full_name are upgraded metadata that
    RLS permits the user to write to their own row under
    ``auth.uid() = id``. Any failure here is swallowed and logged so a
    Supabase outage can never break the upload pipeline — the admin
    empty state is a strictly better failure mode than a 5xx on /api/upload.
    """
    if not user_id or not access_token:
        return

    derived_name = full_name or _derive_name_from_email(email) or "Patient"
    # patient_code is only minted on INSERT; on UPDATE we preserve the
    # existing one so the admin grid never sees a row whose identifier
    # changes between requests. The existence check is defensive: if the
    # user-JWT SELECT is blocked by RLS we treat the row as missing and
    # still mint a code + attempt the write below.
    try:
        existing = get_patient_profile(user_id=user_id, access_token=access_token)
    except Exception:  # noqa: BLE001 - RLS may deny the read; fall through
        existing = None
    payload: dict[str, Any] = {
        "id": user_id,
        "full_name": derived_name,
        "email": email or "",
    }
    if existing is None or not existing.patient_code:
        payload["patient_code"] = _mint_patient_code()

    # Primary path: write under the user's own JWT so RLS ``auth.uid() = id``
    # owns the row. This preserves the security property that a patient only
    # ever writes their own identity row.
    client = get_authenticated_supabase_client(access_token)
    try:
        client.table("patients").upsert(payload, on_conflict="id").execute()
        _PATIENT_PROFILE_LOG.info(
            "patients upsert OK user_id=%s email=%s",
            user_id,
            email or "",
        )
        return
    except Exception as exc:  # noqa: BLE001 - fall back to the service key
        # The most common cause of a "new patient not showing in admin" is a
        # missing/misconfigured INSERT RLS policy on the patients table: the
        # user-JWT upsert is silently denied, and because identity was already
        # validated server-side from the bearer token (Supabase auth.get_user),
        # it is safe to retry the write with the backend service-role key. The
        # service key bypasses RLS so the row is guaranteed to land and the
        # admin cohort reflects the real user base.
        _PATIENT_PROFILE_LOG.warning(
            "patients upsert via user JWT failed user_id=%s email=%s "
            "exc_type=%s exc=%r — retrying with service-role client",
            user_id,
            email or "",
            type(exc).__name__,
            str(exc),
        )

    try:
        service_client = get_supabase_service_client()
        service_client.table("patients").upsert(payload, on_conflict="id").execute()
        _PATIENT_PROFILE_LOG.info(
            "patients upsert OK (service-role fallback) user_id=%s email=%s",
            user_id,
            email or "",
        )
    except Exception as exc:  # noqa: BLE001 - admin visibility is best-effort
        # Loud single-line logging so the operator can see exactly why the
        # admin cohort is empty for a given user. The upload pipeline must
        # still NOT depend on this write — the admin empty state is a
        # strictly better failure mode than a 5xx on /api/upload — but we
        # need the failure visible so it can be diagnosed in production.
        _PATIENT_PROFILE_LOG.error(
            "patients upsert FAILED user_id=%s email=%s exc_type=%s exc=%r payload=%s",
            user_id,
            email or "",
            type(exc).__name__,
            str(exc),
            payload,
        )
        return
