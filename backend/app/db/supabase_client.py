"""Reusable Supabase client for authenticated server-side requests.

The client uses the Supabase publishable/anon key. It is sufficient for
validating a user's access token through Supabase Auth and does not grant
privileged database access.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return the process-wide Supabase client.

    Configuration is validated lazily so the existing local/demo pipeline can
    still start when Supabase has not been configured yet.
    """
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and "
            "SUPABASE_PUBLISHABLE_KEY (or SUPABASE_ANON_KEY)."
        )

    return create_client(settings.supabase_url, settings.supabase_publishable_key)
