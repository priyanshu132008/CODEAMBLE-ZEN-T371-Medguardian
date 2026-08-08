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


settings = Settings()
