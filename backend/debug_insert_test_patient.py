"""Debug: insert ONE row into public.patients and report whether it lands.

Why a standalone script?
    The Admin dashboard has been reporting an empty patient cohort even
    though `/api/upload` returns success. Two failure modes are conflated:
        (a) `/api/upload` is silently failing to persist the patient row
            (likely RLS / FK rejection — see patient_service.upsert
            logs).
        (b) `/api/patients` is silently returning an empty list (RLS on
            the read path filtering rows the admin should see).
    This script bypasses both routes and inserts the row DIRECTLY with
    the service-role client. If the admin dashboard sees the row after
    this script runs, the read path is fine and the bug is in (a).
    If the row is invisible, the bug is in (b) and we read the
    service-role / admin-list implementation next.

Run:
    cd backend && source venv/bin/activate && python debug_insert_test_patient.py

Idempotency:
    The script is safe to re-run. It creates a fresh auth user on each
    invocation (the email is suffixed with a nanosecond timestamp) so
    re-running never collides on the (id) PK or the patients.email index.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any

# Load backend/.env the same way uvicorn does. python-dotenv is already a
# transitive dep of the project via supabase / pydantic-settings.
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from supabase import create_client  # noqa: E402  (after env load)


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        print(f"ERROR: env var {name!r} is empty.", file=sys.stderr)
        sys.exit(2)
    return value


def _banner(title: str) -> None:
    line = "=" * 64
    print(f"\n{line}\n  {title}\n{line}")


def main() -> int:
    url = _env("SUPABASE_URL")
    secret = _env("SUPABASE_SECRET_KEY")

    service = create_client(url, secret)

    # -----------------------------------------------------------------
    # 1. Create a real auth.users row. The patients.id FK requires a real
    #    auth user — we cannot insert with a synthetic UUID.
    # -----------------------------------------------------------------
    _banner("STEP 1 — create a Supabase Auth user (admin createUser)")
    # Unique email per run; never collides on re-runs.
    nonce = uuid.uuid4().hex[:8]
    email = f"test+{nonce}@example.com"
    password = "debug-" + uuid.uuid4().hex  # not used — user is never signed in
    print(f"email: {email}")
    try:
        auth_resp = service.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,  # skip the confirmation email path
            }
        )
    except Exception as exc:
        print(f"FAIL: create_user raised: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    created_user: Any = getattr(auth_resp, "user", None)
    if created_user is None and isinstance(auth_resp, dict):
        created_user = auth_resp.get("user")
    if created_user is None:
        print(f"FAIL: create_user returned no user object: {auth_resp!r}", file=sys.stderr)
        return 1

    user_id = getattr(created_user, "id", None) or (
        created_user.get("id") if isinstance(created_user, dict) else None
    )
    if not user_id:
        print(f"FAIL: created user has no id: {created_user!r}", file=sys.stderr)
        return 1
    print(f"user_id: {user_id}")

    # -----------------------------------------------------------------
    # 2. Upsert the patients row tied to that user. ABHA is NOT a
    #    patients-table column (we don't store ABHA there yet), but the
    #    user's request mentioned it — log it so the test report stays
    #    consistent with what the user asked for.
    # -----------------------------------------------------------------
    _banner("STEP 2 — insert into public.patients (service-role bypass)")
    abha = "12341234123412"
    print(f"ABHA (logged only, not stored in patients table): {abha}")

    # patient_code matches the production mint format (P-XXXXXX).
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    import secrets as _secrets
    patient_code = "P-" + "".join(_secrets.choice(alphabet) for _ in range(6))

    payload = {
        "id": user_id,
        "patient_code": patient_code,
        "full_name": "Test Patient",
        "email": email,
        "phone": None,
    }
    print(f"insert payload: {payload}")

    try:
        resp = service.table("patients").insert(payload).execute()
    except Exception as exc:
        print(f"FAIL: insert raised: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    inserted = getattr(resp, "data", None) or []
    if not inserted:
        print(f"FAIL: insert returned no data. full resp: {resp!r}", file=sys.stderr)
        return 1
    print(f"inserted rows: {inserted}")

    # -----------------------------------------------------------------
    # 3. Verify by reading the row back through the same client.
    # -----------------------------------------------------------------
    _banner("STEP 3 — verify by re-reading the row")
    time.sleep(0.5)  # tiny grace so PostgREST returns the just-committed row
    try:
        read = (
            service.table("patients")
            .select("id, patient_code, full_name, email, phone, created_at")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        print(f"FAIL: re-read raised: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    rows = read.data or []
    if not rows:
        print("FAIL: re-read returned 0 rows. The insert was rejected by RLS/CHECK.",
              file=sys.stderr)
        return 1
    print(f"re-read OK: {rows[0]}")

    # -----------------------------------------------------------------
    # Final report — what the human needs to do next.
    # -----------------------------------------------------------------
    _banner("DONE — refresh the Admin dashboard")
    print(
        "The patients row has been written directly with the service-role key,\n"
        "bypassing the FastAPI `/api/upload` route entirely.\n"
        "\n"
        "  Now refresh the Admin dashboard and look for this user:\n"
        f"    patient_code: {patient_code}\n"
        f"    full_name:    Test Patient\n"
        f"    email:        {email}\n"
        "\n"
        "  If the row IS visible  →  the read path is fine; the bug is\n"
        "    in `/api/upload` (almost certainly the RLS policy on the\n"
        "    INSERT path refusing the user's own-row upsert). Check the\n"
        "    backend log line tagged `medguardian.patient_profile` for\n"
        "    the exact exception.\n"
        "\n"
        "  If the row is NOT visible →  the bug is in the read path\n"
        "    (`GET /api/patients` / RLS policy on SELECT for admins).\n"
        "    The write succeeded; the read is filtered out."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())