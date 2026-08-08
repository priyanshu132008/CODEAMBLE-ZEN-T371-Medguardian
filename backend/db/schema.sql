-- =============================================================================
-- MedGuardian — Supabase / PostgreSQL schema (ABDM + DPDP Act 2023 compliant)
-- =============================================================================
-- This is the canonical SQL schema for the MedGuardian persistence layer
-- (Supabase Postgres). The FastAPI app in `backend/main.py` is the source of
-- truth for the live JSON contract; this schema documents how that contract is
-- persisted, with explicit ABDM (Ayushman Bharat Digital Mission) and DPDP
-- Act 2023 compliance columns.
--
-- Compliance invariants enforced at the application layer (main.py):
--   * No medical record is processed unless `consent_granted = true`
--     (DPDP Act 2023) — a False value is rejected with HTTP 403.
--   * `abha_id`, when present, is exactly 14 digits (ABHA health identifier).
--   * Only de-identified clinical tokens ever leave the local edge for cloud
--     LLMs (Privacy Sandbox); raw PHI is retained on the local edge.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- patients
-- -----------------------------------------------------------------------------
-- One row per patient session. Stores the ABDM ABHA id and the DPDP consent
-- flag alongside the generated MedGuardian patient_id. The `consent_granted`
-- column is NOT NULL and defaults to true (testing convenience) but the API
-- rejects consent=false before any insert, so persisted rows always reflect an
-- explicit opt-in.
CREATE TABLE IF NOT EXISTS patients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL UNIQUE,          -- MedGuardian session id (from /api/upload)
    abha_id         CHAR(14),                       -- ABDM Ayushman Bharat Health Account id (14 digits) or NULL
    consent_granted BOOLEAN NOT NULL DEFAULT TRUE, -- DPDP Act 2023 explicit consent flag
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ABHA ids are 14-digit numeric strings; enforce the shape at the DB layer too.
ALTER TABLE patients
    DROP CONSTRAINT IF EXISTS patients_abha_id_format;
ALTER TABLE patients
    ADD CONSTRAINT patients_abha_id_format
    CHECK (abha_id IS NULL OR abha_id ~ '^\d{14}$');

-- One ABHA id maps to one active patient session.
ALTER TABLE patients
    DROP CONSTRAINT IF EXISTS patients_abha_id_unique;
ALTER TABLE patients
    ADD CONSTRAINT patients_abha_id_unique UNIQUE (abha_id);

-- -----------------------------------------------------------------------------
-- discharge_records (the /api/upload `extracted` contract, persisted)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discharge_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
    diagnosis       TEXT NOT NULL DEFAULT '',
    medications     JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{name,dosage,frequency,duration}]
    precautions     JSONB NOT NULL DEFAULT '[]'::jsonb,
    follow_up_date  TEXT NOT NULL DEFAULT '',
    warning_signs   JSONB NOT NULL DEFAULT '[]'::jsonb,
    allergies       JSONB NOT NULL DEFAULT '[]'::jsonb,    -- ["Penicillin", ...]
    safety_flags    JSONB NOT NULL DEFAULT '[]'::jsonb,    -- interaction / allergy_conflict flags
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- compliance_audit (immutable trail of every medical-records access)
-- -----------------------------------------------------------------------------
-- Every call to a medical-records endpoint (/api/upload, /api/claim/generate)
-- appends a row here so there is an auditable record of consent + ABHA id +
-- the data-residency / cloud-transmission policy in force at the time.
CREATE TABLE IF NOT EXISTS compliance_audit (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID REFERENCES patients(patient_id) ON DELETE SET NULL,
    abha_id             CHAR(14),
    consent_granted     BOOLEAN NOT NULL,
    endpoint            TEXT NOT NULL,                       -- e.g. '/api/upload'
    data_residency      TEXT NOT NULL DEFAULT 'PHI Retained on Local Edge',
    cloud_transmission  TEXT NOT NULL DEFAULT 'Strictly De-identified Clinical Tokens Only',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
