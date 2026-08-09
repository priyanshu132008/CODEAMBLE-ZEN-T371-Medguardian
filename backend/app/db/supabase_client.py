"""Reusable Supabase client for authenticated server-side requests.

The client uses the Supabase publishable/anon key. It is sufficient for
validating a user's access token through Supabase Auth and does not grant
privileged database access.

The admin cohort read on `GET /api/patients` is gated by TWO checks: the
app-layer `require_admin` dependency (which validates the bearer token and
matches the email against `ADMIN_EMAILS`), AND a database-level RLS policy
(`patients_admin_select_all`, see `db/schema.sql`) that re-applies the same
allowlist at the row level. The policy is the second line of defence — the
service-role key never reads PHI on the request path.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


def _create_configured_client() -> Client:
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and "
            "SUPABASE_PUBLISHABLE_KEY (or SUPABASE_ANON_KEY)."
        )

    return create_client(settings.supabase_url, settings.supabase_publishable_key)


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return the process-wide Supabase client.

    Configuration is validated lazily so the existing local/demo pipeline can
    still start when Supabase has not been configured yet.
    """
    return _create_configured_client()


def get_authenticated_supabase_client(access_token: str) -> Client:
    """Create a Supabase client whose PostgREST requests carry a user JWT.

    A fresh client is used per request so changing the Authorization header
    cannot leak one user's token into another concurrent request. The
    publishable/anon key remains the API key, while the user access token is
    what allows Supabase RLS to evaluate ``auth.uid()`` for this request.
    """
    client = _create_configured_client()
    client.postgrest.auth(access_token)
    return client


def _create_service_client() -> Client:
    """Create the backend-only client used for secret-table operations."""

    if not settings.supabase_url or not settings.supabase_secret_key:
        raise RuntimeError(
            "Backend Supabase secret access is not configured. Set SUPABASE_URL "
            "and SUPABASE_SECRET_KEY."
        )

    return create_client(settings.supabase_url, settings.supabase_secret_key)


@lru_cache(maxsize=1)
def get_supabase_service_client() -> Client:
    """Return the privileged backend-only Supabase client.

    This client must remain confined to server-side secret persistence code.
    It is deliberately separate from the publishable/anon client used by
    normal authenticated requests.
    """

    return _create_service_client()
