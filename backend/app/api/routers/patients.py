"""Patient routes for the Admin Command Center and the authenticated patient.

Two endpoints share this router (prefix ``/api/patients``):

- ``GET /api/patients``     — the post-discharge cohort listing for the admin
  console, served from the live Supabase ``patients`` table. This is an
  ADMIN-ONLY endpoint: it requires a validated Supabase access token whose
  email is on the ``ADMIN_EMAILS`` allowlist (see ``require_admin``). No fake
  seed data is ever returned: if Supabase is not configured, or the table is
  empty, the route returns an empty list with an honest ``source`` field
  ("supabase" when the DB query ran, "unconfigured" when Supabase isn't wired)
  so the admin console renders a proper empty state rather than fabricated
  patients. Unauthenticated callers get 401; authenticated non-admins get 403.
- ``GET /api/patients/me``  — the authenticated patient's own profile, looked
  up by the user id encoded in the bearer access token.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    AuthenticatedUser,
    get_current_access_token,
    get_current_user,
    require_admin,
)
from app.db.supabase_client import get_supabase_client
from app.schemas.patients import PatientProfile
from app.services.patient_service import get_patient_profile

router = APIRouter(prefix="/api/patients", tags=["patients"])

# Dedicated logger so the admin read path is grep-able: the row count
# returned from Supabase is the single most useful number when the admin
# console shows "No active patients." despite a known-good row in the DB.
_PATIENTS_LOG = logging.getLogger("medguardian.patients")


def _map_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a row from the existing ``patients`` table onto the frontend
    PatientRecord contract.

    The existing ``patients`` schema is exactly:
        id (UUID, REFERENCES auth.users(id)), patient_code, full_name,
        email, phone, created_at
    (see ``app/services/patient_service.py`` — ``PATIENT_PROFILE_COLUMNS``).
    Identity fields are mapped FROM those columns. The cohort-enrichment
    fields the admin grid also renders (abha_id, diagnosis, status,
    adherence, extracted, safety_flags) are NOT columns of the ``patients``
    table — they live in related tables (admissions / discharge_summaries) and
    are not joined here, so they fall back to safe defaults. Every read is a
    defensive ``.get()``: no column is ever assumed to exist, so a
    patients-only row never 500s, and nothing here creates/drops/alters the
    ``patients`` table.
    """
    return {
        # --- identity: mapped from the existing patients columns ---
        "patient_id": row.get("patient_code") or row.get("id") or "",
        "name": row.get("full_name") or row.get("name") or row.get("patient_name") or "Unknown",
        # abha_id is not a patients-table column; defaults to "" until a join
        # supplies it.
        "abha_id": str(row.get("abha_id") or row.get("abha") or ""),
        # --- cohort enrichment: not patients-table columns; safe defaults ---
        "diagnosis": row.get("diagnosis") or "",
        "status": row.get("status") or "Stable",
        "adherence": int(row.get("adherence") or 0),
        "extracted": row.get("extracted") or {},
        "safety_flags": row.get("safety_flags") or [],
    }


@router.get("")
def list_patients(
    current_user: AuthenticatedUser = Depends(require_admin),
) -> Dict[str, Any]:
    """Return the patient registry from Supabase, or an empty list.

    ADMIN-ONLY. The ``current_user`` dependency (``require_admin``) both
    authenticates the bearer token AND authorizes the caller against the
    ``ADMIN_EMAILS`` allowlist; the server resolves admin status from the
    validated Supabase email, never from any client-supplied claim.

    ``source`` is "supabase" when the database query ran (even with zero rows),
    and "unconfigured" when Supabase isn't wired at all. No fabricated cohort is
    ever served — the admin UI shows an empty state when there are no patients.
    """
    # DIAGNOSTIC: fires ONLY when require_admin passed. If you don't see
    # this line, the 403 came from require_admin above. The Supabase row
    # count is the next signal — `raw_rows=0` means the read query ran
    # but RLS filtered the result; `raw_rows=1` means the row was found.
    print(
        f"[DEBUG] API route /api/patients triggered. "
        f"User: {current_user.email}"
    )
    _PATIENTS_LOG.info(
        "list_patients: route entered admin_email=%s", current_user.email
    )
    try:
        client = get_supabase_client()
    except RuntimeError:
        # Supabase not configured (SUPABASE_URL / key missing). No fake data —
        # the admin renders its empty state.
        print(
            f"[DEBUG] API route /api/patients: Supabase unconfigured. "
            f"User: {current_user.email}"
        )
        _PATIENTS_LOG.warning(
            "list_patients: Supabase unconfigured admin_email=%s",
            current_user.email,
        )
        return {"patients": [], "source": "unconfigured", "count": 0}

    try:
        print(
            f"[DEBUG] API route /api/patients: about to query Supabase. "
            f"User: {current_user.email}"
        )
        resp = client.table("patients").select("*").limit(200).execute()
        rows: List[Dict[str, Any]] = getattr(resp, "data", None) or []
        mapped = [_map_row(r) for r in rows]
        # DIAGNOSTIC: the row count is the number the admin console actually
        # sees as `patients.length`. If this is 0 while the service-role
        # debug script returned 1+, the bug is in the SELECT-side RLS.
        print(
            f"[DEBUG] API route /api/patients: Supabase query OK. "
            f"raw_rows={len(rows)} mapped_rows={len(mapped)} "
            f"User: {current_user.email}"
        )
        _PATIENTS_LOG.info(
            "list_patients: supabase query OK admin_email=%s raw_rows=%s mapped_rows=%s",
            current_user.email,
            len(rows),
            len(mapped),
        )
        return {"patients": mapped, "source": "supabase", "count": len(mapped)}
    except Exception as exc:  # noqa: BLE001 - defensive: any Supabase failure here
        # Configured but the query failed (table missing, network, RLS,
        # PostgREST 4xx, etc.). Still no fake data — surface an empty
        # registry to the admin AND log loudly so the operator can see
        # the real reason for the empty UI.
        print(
            f"[DEBUG] API route /api/patients: Supabase query FAILED. "
            f"exc_type={type(exc).__name__} exc={exc!r} "
            f"User: {current_user.email}"
        )
        _PATIENTS_LOG.error(
            "list_patients: supabase query FAILED admin_email=%s exc_type=%s exc=%r",
            current_user.email,
            type(exc).__name__,
            str(exc),
        )
        return {"patients": [], "source": "supabase", "count": 0}


@router.get("/me", response_model=PatientProfile)
def get_my_patient_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    access_token: str = Depends(get_current_access_token),
) -> PatientProfile:
    """Return the patient row identified by the authenticated user ID."""
    patient = get_patient_profile(
        user_id=current_user.user_id,
        access_token=access_token,
    )
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No patient record found for the authenticated user.",
        )
    return patient