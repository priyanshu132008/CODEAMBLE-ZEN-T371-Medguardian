"""Read-only helpers that pull a patient's *latest* prescriptions from Supabase.

Used by Agent 3 (teach-back) so the LLM prompt is grounded in the
patient's CURRENT discharge summary rather than whatever the frontend
last remembered. The original symptom was the teach-back agent still
asking about "Metformin" from a previous session even after a new
discharge summary had been uploaded and registered with new medications
(Levofloxacin, Paracetamol). The cause was that Agent 3 received only
the frontend-supplied ``extracted`` payload — if the frontend hadn't
reloaded its extraction state yet (or the chat component had a
hard-coded seed question), the LLM kept the old ground truth.

Two layers of defence here:

1. The frontend no longer hard-codes a Metformin question (see
   ``frontend/Components/TeachBackChat.tsx``); the seed question is now
   derived from ``extractedData.medications`` at every state transition.

2. This service re-reads the authoritative ``discharge_summaries`` row
   (if one exists for the supplied ``patient_id``) and merges its
   medications into the teach-back ground truth. The frontend payload
   still flows through so the chat works without auth, but anything
   stored in Supabase for the same patient OVERRIDES the frontend's
   values when the IDs conflict — preventing stale state from leaking
   into the LLM prompt.

The function never raises: a missing patient_id, missing table, or
network error returns ``None`` and the caller falls back to the
frontend's payload. The teach-back endpoint must remain available
during a Supabase outage.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.db.supabase_client import get_supabase_service_client


_PRESCRIPTIONS_LOG = logging.getLogger("medguardian.prescriptions")


def persist_discharge_summary(
    *,
    user_id: str,
    extracted: Dict[str, Any],
) -> None:
    """Store the latest extracted discharge summary so Agent 3 can re-read it.

    Called by /api/upload after a successful OCR extraction. The row is keyed by
    ``patient_id = user_id`` (the validated Supabase auth uid) — the same value
    the frontend sends to /api/teach-back, so ``fetch_latest_prescriptions`` can
    find it. A new row is written on every upload (not an upsert) so the
    created_at ordering gives us "latest wins" for the teach-back overlay.

    Best-effort: a missing table, a Supabase outage, or an unconfigured service
    key is swallowed and logged. The upload pipeline must never 5xx because the
    authoritative-copy write failed — the frontend payload is the fallback.
    """
    if not user_id or not extracted:
        return

    try:
        client = get_supabase_service_client()
    except RuntimeError:
        # Service role not configured; the teach-back overlay simply stays
        # disabled and the frontend payload is used as ground truth.
        return

    payload = {
        "patient_id": user_id,
        "user_id": user_id,
        "diagnosis": str(extracted.get("diagnosis") or ""),
        "medications": extracted.get("medications") or [],
        "precautions": extracted.get("precautions") or [],
        "follow_up_date": str(extracted.get("follow_up_date") or ""),
        "warning_signs": extracted.get("warning_signs") or [],
        "allergies": extracted.get("allergies") or [],
    }
    try:
        client.table("discharge_summaries").insert(payload).execute()
        _PRESCRIPTIONS_LOG.info(
            "discharge_summaries insert OK patient_id=%s meds=%s",
            user_id,
            len(payload["medications"]),
        )
    except Exception as exc:  # noqa: BLE001 - best-effort persistence
        _PRESCRIPTIONS_LOG.warning(
            "discharge_summaries insert FAILED patient_id=%s exc_type=%s exc=%r",
            user_id,
            type(exc).__name__,
            exc,
        )


def fetch_latest_prescriptions(patient_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the patient's most recent discharge summary, or None.

    The query reads the ``discharge_summaries`` table provisioned in
    ``db/schema.sql``. The table has RLS enabled with NO client-facing
    policies, so the read MUST use the backend service-role client — the
    anon/publishable client would see zero rows.

    Returns a dict shaped like an Agent-1 ``extracted`` payload:

        {
            "diagnosis": str,
            "medications": [{"name": str, "dosage": str, ...}],
            "precautions": [str],
            "follow_up_date": str,
            "warning_signs": [str],
            "allergies": [str],
            "source": "discharge_summaries",
            "fetched_at": iso-8601 str,
        }

    or ``None`` when no row is found / the table is missing / Supabase
    is not configured. The caller falls back to the frontend's payload
    in either case so the chat keeps working offline.
    """
    if not patient_id:
        return None

    try:
        client = get_supabase_service_client()
    except RuntimeError:
        # Service role not configured; the demo flow keeps working with
        # the frontend-supplied ground truth.
        return None

    try:
        # We deliberately fetch the most recent row by sorting on
        # created_at desc and limiting to 1. If the schema doesn't
        # have a created_at column the query simply returns []; the
        # caller then falls back to the frontend payload.
        resp = (
            client.table("discharge_summaries")
            .select("patient_id, diagnosis, medications, precautions, follow_up_date, warning_signs, allergies, created_at")
            .eq("patient_id", patient_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 — best-effort lookup
        _PRESCRIPTIONS_LOG.warning(
            "fetch_latest_prescriptions: query failed patient_id=%s err=%r",
            patient_id,
            exc,
        )
        return None

    rows = getattr(resp, "data", None) or []
    if not rows:
        return None

    row = rows[0]
    # Normalise to the Agent-1 extracted shape so the merge below is
    # transparent to the teach-back prompt builder.
    meds_raw = row.get("medications") or []
    medications: List[Dict[str, Any]] = []
    if isinstance(meds_raw, list):
        for m in meds_raw:
            if isinstance(m, dict) and m.get("name"):
                medications.append({
                    "name": str(m.get("name") or ""),
                    "dosage": str(m.get("dosage") or "") or None,
                    "frequency": str(m.get("frequency") or "") or None,
                    "duration": str(m.get("duration") or "") or None,
                })
            elif isinstance(m, str) and m.strip():
                # Some legacy OCR outputs store bare medication strings.
                medications.append({"name": m.strip()})

    import datetime as _dt

    return {
        "diagnosis": str(row.get("diagnosis") or ""),
        "medications": medications,
        "precautions": list(row.get("precautions") or []),
        "follow_up_date": str(row.get("follow_up_date") or ""),
        "warning_signs": list(row.get("warning_signs") or []),
        "allergies": list(row.get("allergies") or []),
        "source": "discharge_summaries",
        "fetched_at": _dt.datetime.utcnow().isoformat() + "Z",
    }


def merge_ground_truth(
    frontend_extracted: Dict[str, Any],
    db_extracted: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Overlay ``db_extracted`` onto ``frontend_extracted``.

    Merge semantics (per field):
      * ``medications``: replace entirely with the DB list when present
        AND non-empty — this is the primary fix for the "stale Metformin"
        bug. The DB is authoritative because the discharge summary row
        was just persisted by /api/upload; if the chat is looking at a
        cached frontend payload from a previous session, the DB has the
        truth.
      * ``diagnosis``, ``follow_up_date``: prefer DB when non-empty.
      * ``precautions``, ``warning_signs``, ``allergies``: prefer DB
        (longest non-empty list wins; ties go to the DB so a stale
        empty list on the frontend cannot clobber real warnings).
      * ``language``: untouched — frontend only.

    If ``db_extracted`` is None (no row, no patient_id, Supabase
    unreachable), the frontend payload is returned as-is. This is the
    graceful-degradation path that keeps the demo working without
    Supabase.
    """
    if not db_extracted:
        return frontend_extracted

    merged = dict(frontend_extracted or {})

    # Medications — primary fix. Empty DB list does NOT clear the
    # frontend's meds (a row with no meds column is just a missing
    # data point, not authoritative "no medications").
    db_meds = db_extracted.get("medications") or []
    if db_meds:
        merged["medications"] = db_meds

    if db_extracted.get("diagnosis"):
        merged["diagnosis"] = db_extracted["diagnosis"]
    if db_extracted.get("follow_up_date"):
        merged["follow_up_date"] = db_extracted["follow_up_date"]

    for key in ("precautions", "warning_signs", "allergies"):
        db_list = db_extracted.get(key) or []
        fe_list = merged.get(key) or []
        # Longest non-empty list wins.
        if len(db_list) >= len(fe_list) and db_list:
            merged[key] = db_list
        elif fe_list:
            merged[key] = fe_list

    return merged


__all__ = ["persist_discharge_summary", "fetch_latest_prescriptions", "merge_ground_truth"]