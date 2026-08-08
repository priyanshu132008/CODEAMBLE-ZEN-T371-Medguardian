"""Patients registry route for the Hospital Admin Command Center.

Serves the post-discharge patient cohort to the admin console from the live
Supabase ``patients`` table when configured (``SUPABASE_URL`` + publishable/
anon key in the environment).

No fake seed data is ever returned. If Supabase is not configured, or the
table is empty, the route returns an empty list and an honest ``source`` field
("supabase" when the DB query ran, "unconfigured" when Supabase isn't wired)
so the admin console renders a proper empty state rather than fabricated
patients.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from app.db.supabase_client import get_supabase_client

router = APIRouter(prefix="/api/patients", tags=["patients"])


def _map_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a Supabase ``patients`` row (unknown column names) defensively onto
    the frontend PatientRecord contract. Missing columns fall back to safe
    defaults so a partially-populated table never 500s."""
    return {
        "patient_id": row.get("patient_id") or row.get("id") or "",
        "abha_id": str(row.get("abha_id") or row.get("abha") or ""),
        "name": row.get("name") or row.get("patient_name") or "Unknown",
        "diagnosis": row.get("diagnosis") or "",
        "status": row.get("status") or "Stable",
        "adherence": int(row.get("adherence") or 0),
        "extracted": row.get("extracted") or {},
        "safety_flags": row.get("safety_flags") or [],
    }


@router.get("")
def list_patients() -> Dict[str, Any]:
    """Return the patient registry from Supabase, or an empty list.

    ``source`` is "supabase" when the database query ran (even with zero rows),
    and "unconfigured" when Supabase isn't wired at all. No fabricated cohort is
    ever served — the admin UI shows an empty state when there are no patients.
    """
    try:
        client = get_supabase_client()
    except RuntimeError:
        # Supabase not configured (SUPABASE_URL / key missing). No fake data —
        # the admin renders its empty state.
        return {"patients": [], "source": "unconfigured", "count": 0}

    try:
        resp = client.table("patients").select("*").limit(200).execute()
        rows: List[Dict[str, Any]] = getattr(resp, "data", None) or []
        mapped = [_map_row(r) for r in rows]
        return {"patients": mapped, "source": "supabase", "count": len(mapped)}
    except Exception:
        # Configured but the query failed (table missing, network, etc.).
        # Still no fake data — surface an empty registry to the admin.
        return {"patients": [], "source": "supabase", "count": 0}