from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


class Settings:
    """Application settings loaded from environment variables."""

    app_name: str = os.getenv("APP_NAME", "MedGuardian API")
    debug: bool = os.getenv("DEBUG", "False").lower() in {"1", "true", "yes", "on"}
    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]
    supabase_url: str = os.getenv("SUPABASE_URL", "").strip()
    # Supabase currently refers to this browser-safe key as the publishable
    # key; support the older anon-key name as a compatibility alias.
    supabase_publishable_key: str = (
        os.getenv("SUPABASE_PUBLISHABLE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or ""
    ).strip()
    medguardian_token_encryption_key: str = os.getenv(
        "MEDGUARDIAN_TOKEN_ENCRYPTION_KEY", ""
    ).strip()
    # Backend-only Supabase secret/service-role key. Never expose this value to
    # browser clients or include it in API responses.
    supabase_secret_key: str = os.getenv("SUPABASE_SECRET_KEY", "").strip()

    # ----- Google Calendar OAuth (backend-only REST via httpx, no SDK) -----
    # All three Google values are backend-only and never sent to the frontend.
    # The redirect URI is the backend callback route; the frontend origins are
    # an allowlist the callback may redirect back to (no open redirect).
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    google_redirect_uri: str = os.getenv(
        "GOOGLE_REDIRECT_URI",
        "http://localhost:8000/api/calendar/google/callback",
    ).strip()
    # Comma-separated list of frontend origins the OAuth callback may redirect
    # to after a successful connection. Anything not in this list is rejected so
    # the callback can never be used as an open redirect.
    frontend_redirect_origins: list[str] = [
        origin.strip()
        for origin in os.getenv(
            "FRONTEND_REDIRECT_ORIGINS", "http://localhost:3000"
        ).split(",")
        if origin.strip()
    ]
    # Default IANA timezone for medication reminder events (IST for the demo).
    default_timezone: str = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata").strip()

    # ----- Admin authorization (server-resolved, never client-supplied) -----
    # Comma-separated allowlist of Supabase Auth emails permitted to access the
    # admin patient registry. Admin status is resolved by the SERVER from this
    # list (matched against the validated Supabase user's email) and returned in
    # the auth response — never from any role claim sent by the browser. Empty
    # by default, so no one is an admin until an operator configures this. This
    # is the smallest safe mechanism compatible with Supabase email/password
    # auth (no custom roles table, no service-role call from the browser).
    admin_emails: set[str] = {
        addr.strip().lower()
        for addr in os.getenv("ADMIN_EMAILS", "").split(",")
        if addr.strip()
    }

    def is_admin_email(self, email: str | None) -> bool:
        """True only when a validated Supabase user's email is on the allowlist."""
        if not email:
            return False
        return email.strip().lower() in self.admin_emails

    def is_google_configured(self) -> bool:
        """True only when the backend holds a complete Google OAuth client.

        Routes that build a Google consent URL fail closed (503) when this is
        False rather than emitting a malformed authorization request.
        """
        return bool(self.google_client_id and self.google_client_secret and self.google_redirect_uri)


settings = Settings()
