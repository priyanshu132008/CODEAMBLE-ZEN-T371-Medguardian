-- =============================================================================
-- Migration: 2026_08_09_patients_admin_select.sql
-- =============================================================================
-- One-shot migration to grant admins a SELECT-all policy on the `patients`
-- table so the Admin Command Center (GET /api/patients) can read the full
-- cohort under RLS, without bypassing RLS on the request path.
--
-- This is the second line of defence — the application layer's `require_admin`
-- dependency already gates the route by validating the bearer token and
-- matching the email against the `ADMIN_EMAILS` env var. The policy below
-- re-applies the same allowlist at the row level so that even if the app-layer
-- check is ever bypassed (route refactor, middleware regression, etc.), the
-- database still refuses to leak PHI to a non-admin JWT.
--
-- The allowlist literal below MUST be kept in sync with `ADMIN_EMAILS` in
-- backend/.env. Both the app-layer check and the policy read the same list;
-- a divergence would mean either the route 403s (env has email not in policy)
-- or the policy allows someone the app rejects. To rotate admins:
--   1. Update ADMIN_EMAILS in backend/.env.
--   2. Re-run this migration with the new email list (idempotent — DROP
--      IF EXISTS + CREATE).
--   3. Redeploy the backend so the new env var takes effect.
--
-- Run this in the Supabase SQL editor (Project → SQL → New query), or via
-- psql against the database.
-- =============================================================================

DROP POLICY IF EXISTS patients_admin_select_all ON patients;
CREATE POLICY patients_admin_select_all
    ON patients FOR SELECT TO authenticated
    USING (
        lower(coalesce(auth.jwt() ->> 'email', '')) IN (
            'priyanshusawant200813@gmail.com',
            'admin@hospital.in'
        )
    );

-- =============================================================================
-- Verify:
-- =============================================================================
-- After running, you can verify the policy is in effect with:
--
--   SELECT policyname, cmd, qual
--   FROM pg_policies
--   WHERE schemaname = 'public' AND tablename = 'patients';
--
-- You should see `patients_admin_select_all` with `cmd = 'SELECT'` and a
-- USING clause matching the email list above.
--
-- Then hit GET /api/patients from the admin account — the cohort grid will
-- populate immediately. Patients hitting /api/patients/me still see only
-- their own row, because the existing per-row `auth.uid() = id` policy is
-- untouched (Postgres OR-combines permissive SELECT policies).
-- =============================================================================