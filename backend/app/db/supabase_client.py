"""Reusable Supabase client for authenticated server-side requests.

The client uses the Supabase publishable/anon key. It is sufficient for
validating a user's access token through Supabase Auth and does not grant
privileged database access.
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
