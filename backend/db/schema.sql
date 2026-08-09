-- =============================================================================
-- MedGuardian — Supabase / PostgreSQL schema (ABDM + DPDP Act 2023 compliant)
-- =============================================================================
-- This file provisions ONLY the MedGuardian-specific tables the FastAPI backend
-- added on top of the project's main patient schema. It is deliberately
-- additive and idempotent (every statement is IF NOT EXISTS / DROP-then-CREATE
-- for policies) so it is safe to re-run on an existing Supabase project.
--
-- Compliance invariants enforced at the application layer (main.py):
--   * No medical record is processed unless `consent_granted = true`
--     (DPDP Act 2023) — a False value is rejected with HTTP 403.
--   * `abha_id`, when present, is exactly 14 digits (ABHA health identifier).
--   * Only de-identified clinical tokens ever leave the local edge for cloud
--     LLMs (Privacy Sandbox); raw PHI is retained on the local edge.
--
-- IMPORTANT — the main patient schema is NOT created here.
-- -----------------------------------------------------------------------------
-- The project's Supabase database already owns the core patient tables (they
-- predate the calendar/reminder work). This file must NOT redefine them — doing
-- so would create a SECOND, conflicting `patients` table. The main schema the
-- backend expects (queried by app/services/patient_service.py and the admin
-- /api/patients route) is:
--
--   patients (
--     id           UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
--     patient_code TEXT,
--     full_name    TEXT,
--     email        TEXT,
--     phone        TEXT,
--     created_at   TIMESTAMPTZ DEFAULT now()
--   )
--   -- plus the related cohort tables: admissions, billing_items,
--   -- discharge_summaries, insurance_claims.
--
-- `patient_service.get_patient_profile` selects
--   (id, patient_code, full_name, email, phone, created_at) .eq("id", user_id)
-- where user_id is the validated Supabase auth uid — so patient identity is
-- derived from the bearer token, never from a frontend-supplied id. If your
-- project does not yet have this `patients` table, create it with the columns
-- above (it must reference auth.users(id)); this file intentionally does not.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- calendar_connections (Google Calendar connection metadata)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calendar_connections (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider             TEXT NOT NULL DEFAULT 'google',
    google_account_email TEXT,
    calendar_id          TEXT NOT NULL DEFAULT 'primary',
    scopes               JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT calendar_connections_user_provider_unique UNIQUE (user_id, provider)
);

-- Secret material is isolated from metadata. This table intentionally has RLS
-- enabled but no client-facing policies; only the backend service-role client
-- can access it. The service role key never leaves the backend.
CREATE TABLE IF NOT EXISTS calendar_connection_secrets (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id          UUID NOT NULL REFERENCES calendar_connections(id) ON DELETE CASCADE,
    encrypted_refresh_token TEXT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT calendar_connection_secrets_connection_unique UNIQUE (connection_id)
);

-- Migrate rows from the pre-3B-3a layout, if that layout was deployed, before
-- removing the secret column from the metadata table. Dynamic SQL keeps a fresh
-- installation from referencing a column that does not exist.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'calendar_connections'
          AND column_name = 'encrypted_refresh_token'
    ) THEN
        EXECUTE $migration$
            INSERT INTO public.calendar_connection_secrets
                (connection_id, encrypted_refresh_token)
            SELECT id, encrypted_refresh_token
            FROM public.calendar_connections
            WHERE encrypted_refresh_token IS NOT NULL
            ON CONFLICT (connection_id) DO NOTHING
        $migration$;
        ALTER TABLE calendar_connections DROP COLUMN encrypted_refresh_token;
    END IF;
END
$$;

ALTER TABLE calendar_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE calendar_connection_secrets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS calendar_connections_select_own ON calendar_connections;
CREATE POLICY calendar_connections_select_own
    ON calendar_connections FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS calendar_connections_insert_own ON calendar_connections;
CREATE POLICY calendar_connections_insert_own
    ON calendar_connections FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS calendar_connections_update_own ON calendar_connections;
CREATE POLICY calendar_connections_update_own
    ON calendar_connections FOR UPDATE TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS calendar_connections_delete_own ON calendar_connections;
CREATE POLICY calendar_connections_delete_own
    ON calendar_connections FOR DELETE TO authenticated
    USING (auth.uid() = user_id);

-- No SELECT/INSERT/UPDATE/DELETE policies are intentionally defined for
-- calendar_connection_secrets. Normal authenticated and anonymous clients are
-- denied by RLS; the backend service-role client bypasses RLS for secret work.

-- -----------------------------------------------------------------------------
-- oauth_states (single-use, expiring Google OAuth state binding)
-- -----------------------------------------------------------------------------
-- The Google OAuth callback is a top-level browser navigation with no bearer
-- token, so the callback handler has no authenticated Supabase client. This
-- table holds, keyed by a single-use nonce, the caller's Supabase access token
-- *encrypted* (enc_access_token) for the ~10 minutes the consent flow may take.
-- The opaque `state` string the browser carries is an AES-256-GCM envelope over
-- {uid, nonce, exp}; the access token never leaves our origin.
--
-- RLS is enabled with NO client policies: only the backend service-role client
-- reads/writes this table. A row is deleted the moment its state is consumed
-- (verify is single-use) and expired rows are purged on each issue().
CREATE TABLE IF NOT EXISTS oauth_states (
    nonce             TEXT PRIMARY KEY,
    user_id           UUID NOT NULL,
    enc_access_token  TEXT NOT NULL,                 -- AES-256-GCM envelope of the Supabase access token
    exp_at            TIMESTAMPTZ NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE oauth_states ENABLE ROW LEVEL SECURITY;
-- No policies: authenticated/anon are denied by RLS; the service role bypasses
-- RLS. This table is backend-only.

-- -----------------------------------------------------------------------------
-- medication_reminders (synced Google Calendar medication reminders)
-- -----------------------------------------------------------------------------
-- One row per (user, schedule_hash). schedule_hash is a stable SHA-256 over the
-- canonical {patient_id, medication_name, dosage, normalized frequency, sorted
-- schedule times}, giving idempotency: re-syncing the same medication PATCHes
-- the existing Google events instead of creating duplicates.
--
-- google_event_ids is a JSONB list parallel to schedule_json (one Google event
-- id per reminder time) — a "twice daily" medication therefore owns two daily
-- recurring events. No credential material lives here: google_event_ids are
-- opaque Google resource ids, never tokens. RLS restricts every operation to
-- the owning user; ownership is derived from the bearer token, never from a
-- frontend-supplied user_id or patient_id.
CREATE TABLE IF NOT EXISTS medication_reminders (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    patient_id       TEXT,
    medication_name  TEXT NOT NULL,
    dosage           TEXT,
    frequency        TEXT,
    schedule_json    JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{time:"HH:MM",label}]
    google_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,   -- ["evt1", ...] parallel to schedule_json
    calendar_id      TEXT NOT NULL DEFAULT 'primary',
    start_date       DATE NOT NULL,
    end_date         DATE,
    status           TEXT NOT NULL DEFAULT 'active',       -- active | skipped | error | disconnected
    schedule_hash    TEXT NOT NULL,
    needs_review     BOOLEAN NOT NULL DEFAULT FALSE,
    recurring        BOOLEAN NOT NULL DEFAULT FALSE,
    timezone         TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT medication_reminders_user_hash_unique UNIQUE (user_id, schedule_hash)
);

ALTER TABLE medication_reminders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS medication_reminders_select_own ON medication_reminders;
CREATE POLICY medication_reminders_select_own
    ON medication_reminders FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS medication_reminders_insert_own ON medication_reminders;
CREATE POLICY medication_reminders_insert_own
    ON medication_reminders FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS medication_reminders_update_own ON medication_reminders;
CREATE POLICY medication_reminders_update_own
    ON medication_reminders FOR UPDATE TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS medication_reminders_delete_own ON medication_reminders;
CREATE POLICY medication_reminders_delete_own
    ON medication_reminders FOR DELETE TO authenticated
    USING (auth.uid() = user_id);

-- =============================================================================
-- Reference: the compliance_metadata object returned by the API
-- =============================================================================
--   {
--     "abdm_abha_id": "<14-digit id or null>",
--     "dpdp_consent": true,
--     "data_residency": "PHI Retained on Local Edge",
--     "cloud_transmission": "Strictly De-identified Clinical Tokens Only"
--   }
-- =============================================================================

-- -----------------------------------------------------------------------------
-- patients — admin SELECT policy
-- -----------------------------------------------------------------------------
-- The application's `patients` table is owned by `auth.users(id)` and protected
-- by a per-row `auth.uid() = id` SELECT policy so a patient can only read
-- their own row. The Admin Command Center (GET /api/patients) needs to read
-- the full cohort for the dashboard grid.
--
-- We grant admins the SELECT at the DATABASE level rather than bypassing RLS
-- with the service-role key on the request path. Two reasons:
--   1. Defense in depth: even if the app-layer `require_admin` dependency is
--      ever removed or refactored, the database still refuses to leak PHI to
--      a non-admin JWT.
--   2. The service-role key remains a write-side tool only (calendar
--      connections, OAuth state, audit logs) — never on a read path that
--      returns PHI to the browser.
--
-- The allowlist below MUST match the backend's `ADMIN_EMAILS` env var. The
-- backend also gates the route via `require_admin`, so this policy is the
-- second line of defence — not the only one. If you rotate admins, re-run
-- this file (idempotent — DROP + CREATE) after updating ADMIN_EMAILS in
-- backend/.env, then redeploy.
--
-- The policy is additive and idempotent (DROP IF EXISTS + CREATE) — safe to
-- re-run on an existing Supabase project. The companion one-shot migration
-- lives in `db/migrations/2026_08_09_patients_admin_select.sql` for projects
-- that prefer to apply migrations to the live database without re-running
-- the full schema.
-- -----------------------------------------------------------------------------

DROP POLICY IF EXISTS patients_admin_select_all ON patients;
CREATE POLICY patients_admin_select_all
    ON patients FOR SELECT TO authenticated
    USING (
        -- Only grant the row-level bypass to a JWT whose `email` claim is
        -- present in the admin allowlist. Supabase signs JWTs server-side,
        -- so a patient cannot edit their own JWT to satisfy this predicate.
        -- Lower-case comparison matches the backend's `is_admin_email`.
        lower(coalesce(auth.jwt() ->> 'email', '')) IN (
            'priyanshusawant200813@gmail.com',
            'admin@hospital.in'
        )
    );

-- Note: the existing per-row `auth.uid() = id` policy (if any) is left
-- intact. Postgres OR-combines permissive policies on the same operation, so
-- a patient still sees only their own row (the per-user policy) AND an admin
-- sees every row (this policy). No DROP of the per-user policy is needed.
-- =============================================================================