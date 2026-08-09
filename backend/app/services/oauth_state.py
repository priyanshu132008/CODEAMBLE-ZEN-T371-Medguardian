"""Single-use, expiring OAuth state binding for the Google Calendar flow.

The hard problem this module solves: the Google OAuth ``callback`` is a
top-level browser navigation (GET ``/callback?code=...&state=...``) with no
``Authorization`` header, so the callback handler has no bearer token to
reconstruct the authenticated Supabase client that owns the connection we are
about to write.

We solve it without ever putting a token in the browser:

1. ``issue(user_id, access_token)`` mints an opaque ``state`` string that is an
   AES-256-GCM envelope (reusing :class:`TokenEncryptionService`) over
   ``{uid, nonce, exp}``. It simultaneously stores the caller's Supabase
   ``access_token`` **encrypted** in an ``oauth_states`` row keyed by ``nonce``
   with a short (10-minute) expiry. The browser only ever sees the opaque
   ``state``.
2. ``verify(state)`` decrypts the envelope, checks ``exp``, looks up the nonce
   row, decrypts the stored access token, and **deletes the nonce row** so the
   state is single-use. On any failure it returns ``None`` and deletes the row.

The service-role Supabase client owns the ``oauth_states`` table; it carries no
client-facing RLS policies. No token material — plaintext, encrypted, or in a
URL — ever leaves our origin.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.db.supabase_client import get_supabase_service_client
from app.services.token_encryption import TokenEncryptionService

# State envelope is valid for 10 minutes — long enough for a human to complete
# the Google consent screen, short enough to bound replay risk.
_STATE_TTL_SECONDS = 600


@dataclass(frozen=True)
class VerifiedState:
    """A verified, single-use OAuth state and the access token it bound."""

    user_id: str
    access_token: str


class OAuthStateError(RuntimeError):
    """Raised when the OAuth state cannot be issued or the table is unavailable."""


class OAuthStateService:
    """Issue and verify single-use, expiring OAuth state tokens.

    The encryption service is constructor-injected so tests can pass a
    deterministic key. Production builds it lazily from settings.
    """

    def __init__(self, encryption_service: TokenEncryptionService | None = None) -> None:
        self._encryption_service = encryption_service

    def _encryptor(self) -> TokenEncryptionService:
        return self._encryption_service or TokenEncryptionService()

    @staticmethod
    def _table():
        # The oauth_states table is owned by the backend service-role client
        # only; it has no client-facing RLS policies.
        return get_supabase_service_client().table("oauth_states")

    def issue(self, *, user_id: str, access_token: str) -> str:
        """Mint a single-use state that binds ``user_id`` + ``access_token``.

        Returns the opaque state string to embed in the Google consent URL. The
        caller's access token is stored encrypted in the nonce row.
        """
        if not user_id or not access_token:
            raise OAuthStateError("user_id and access_token are required to issue state.")

        encryptor = self._encryptor()
        nonce = secrets.token_urlsafe(16)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=_STATE_TTL_SECONDS)
        ).isoformat()

        # The state envelope carries only identity + expiry; the access token
        # is stored separately, encrypted, keyed by the nonce.
        payload = json.dumps({"uid": user_id, "nonce": nonce, "exp": expires_at})
        state = encryptor.encrypt(payload)

        # Best-effort cleanup of expired rows so the table cannot grow without
        # bound. A failure here must not block issuance.
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            self._table().delete().lt("exp_at", now_iso).execute()
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            pass

        try:
            self._table().insert(
                {
                    "nonce": nonce,
                    "user_id": user_id,
                    "enc_access_token": encryptor.encrypt(access_token),
                    "exp_at": expires_at,
                }
            ).execute()
        except Exception as exc:  # noqa: BLE001 - surface a clear failure
            raise OAuthStateError("Could not persist OAuth state.") from exc

        return state

    def verify(self, state: str) -> VerifiedState | None:
        """Verify a single-use state and recover the bound access token.

        Returns ``None`` and consumes the nonce row on any failure (tampered
        envelope, expired, missing row, decryption failure). On success the
        nonce row is deleted so the state cannot be replayed.
        """
        if not state:
            return None
        try:
            payload = self._encryptor().decrypt(state)
            data = json.loads(payload)
            user_id = data["uid"]
            nonce = data["nonce"]
            exp = data["exp"]
        except Exception:  # noqa: BLE001 - any envelope failure is a rejection
            return None

        # Expiry check. ISO strings compare correctly for UTC timestamps.
        if datetime.now(timezone.utc).isoformat() > str(exp):
            self._delete_nonce(nonce)
            return None

        try:
            response = self._table().select("enc_access_token").eq("nonce", nonce).limit(1).execute()
        except Exception:  # noqa: BLE001 - table unavailable
            return None

        rows = getattr(response, "data", None) or []
        if not rows:
            return None

        # Single-use: delete the row before returning so a replay cannot work
        # even if decryption below were to raise.
        self._delete_nonce(nonce)

        encrypted_token = rows[0].get("enc_access_token")
        if not encrypted_token:
            return None
        try:
            access_token = self._encryptor().decrypt(encrypted_token)
        except Exception:  # noqa: BLE001 - tampered stored token
            return None

        return VerifiedState(user_id=str(user_id), access_token=access_token)

    def _delete_nonce(self, nonce: str) -> None:
        try:
            self._table().delete().eq("nonce", nonce).execute()
        except Exception:  # noqa: BLE101 - deletion is best-effort
            pass