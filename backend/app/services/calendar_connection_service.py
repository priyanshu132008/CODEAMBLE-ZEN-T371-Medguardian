"""Persistence abstraction for encrypted Google Calendar connections."""

from __future__ import annotations

from collections.abc import Sequence

from app.api.dependencies import AuthenticatedUser
from app.db.supabase_client import (
    get_authenticated_supabase_client,
    get_supabase_service_client,
)
from app.schemas.calendar import CalendarConnectionProfile
from app.services.token_encryption import TokenEncryptionService


CALENDAR_CONNECTION_COLUMNS = (
    "id, user_id, provider, google_account_email, calendar_id, scopes, "
    "created_at, updated_at"
)


class CalendarConnectionService:
    """Store and retrieve one user's encrypted Google connection.

    ``current_user`` must come from ``get_current_user`` and ``access_token``
    must come from the authenticated request dependency. No method accepts a
    frontend-supplied user identity.
    """

    def __init__(self, encryption_service: TokenEncryptionService | None = None) -> None:
        self._encryption_service = encryption_service

    def _encryptor(self) -> TokenEncryptionService:
        return self._encryption_service or TokenEncryptionService()

    def _table(self, access_token: str):
        if not access_token or any(character.isspace() for character in access_token):
            raise ValueError("A valid authenticated access token is required.")
        return get_authenticated_supabase_client(access_token).table("calendar_connections")

    @staticmethod
    def _secret_table():
        return get_supabase_service_client().table("calendar_connection_secrets")

    @staticmethod
    def _user_filter(query, current_user: AuthenticatedUser):
        return query.eq("user_id", current_user.user_id).eq("provider", "google")

    @staticmethod
    def _profile(rows: Sequence[dict]) -> CalendarConnectionProfile | None:
        if not rows:
            return None
        return CalendarConnectionProfile.model_validate(rows[0])

    def save_google_connection(
        self,
        *,
        current_user: AuthenticatedUser,
        access_token: str,
        refresh_token: str,
        google_account_email: str | None = None,
        calendar_id: str = "primary",
        scopes: list[str] | None = None,
    ) -> CalendarConnectionProfile:
        """Encrypt and upsert a Google refresh token for the current user."""

        # Resolve the privileged client before changing metadata so a missing
        # service-role configuration fails closed without leaving an orphan row.
        secret_table = self._secret_table()
        encrypted_refresh_token = self._encryptor().encrypt(refresh_token)
        response = (
            self._table(access_token).upsert(
                {
                    "user_id": current_user.user_id,
                    "provider": "google",
                    "google_account_email": google_account_email,
                    "calendar_id": calendar_id,
                    "scopes": scopes or [],
                },
                on_conflict="user_id,provider",
            )
            .select(CALENDAR_CONNECTION_COLUMNS)
            .execute()
        )
        profile = self._profile(response.data or [])
        if profile is None:
            raise RuntimeError("Calendar connection was not persisted.")

        secret_table.upsert(
            {
                "connection_id": str(profile.id),
                "encrypted_refresh_token": encrypted_refresh_token,
            },
            on_conflict="connection_id",
        ).execute()
        return profile

    def get_google_connection(
        self,
        *,
        current_user: AuthenticatedUser,
        access_token: str,
    ) -> CalendarConnectionProfile | None:
        """Return safe connection metadata without encrypted token material."""

        response = (
            self._user_filter(
                self._table(access_token).select(CALENDAR_CONNECTION_COLUMNS),
                current_user,
            )
            .limit(1)
            .execute()
        )
        return self._profile(response.data or [])

    def get_decrypted_refresh_token(
        self,
        *,
        current_user: AuthenticatedUser,
        access_token: str,
    ) -> str | None:
        """Explicitly decrypt the current user's token for backend use only."""

        connection = self.get_google_connection(
            current_user=current_user,
            access_token=access_token,
        )
        if connection is None:
            return None

        # The authenticated client resolves ownership through metadata. Only
        # then is the backend-only service client allowed to read the secret.
        response = (
            self._secret_table()
            .select("encrypted_refresh_token")
            .eq("connection_id", str(connection.id))
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        encrypted_value = rows[0].get("encrypted_refresh_token")
        if not encrypted_value:
            raise RuntimeError("Stored calendar connection is invalid.")
        return self._encryptor().decrypt(encrypted_value)

    def delete_google_connection(
        self,
        *,
        current_user: AuthenticatedUser,
        access_token: str,
    ) -> bool:
        """Delete only the current user's Google connection."""

        connection = self.get_google_connection(
            current_user=current_user,
            access_token=access_token,
        )
        if connection is None:
            return False

        # Explicitly delete secret material through the privileged backend
        # client before deleting metadata through the authenticated client.
        self._secret_table().delete().eq("connection_id", str(connection.id)).execute()
        self._user_filter(self._table(access_token).delete(), current_user).execute()
        return True

    def has_google_connection(
        self,
        *,
        current_user: AuthenticatedUser,
        access_token: str,
    ) -> bool:
        """Check whether the current user has a Google connection."""

        response = (
            self._user_filter(self._table(access_token).select("id"), current_user)
            .limit(1)
            .execute()
        )
        return bool(response.data)
