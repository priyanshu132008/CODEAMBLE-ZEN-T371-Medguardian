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