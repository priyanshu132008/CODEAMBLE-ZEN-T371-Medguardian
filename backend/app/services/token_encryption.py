"""Authenticated encryption for OAuth refresh tokens at rest."""

from __future__ import annotations

import base64
import binascii
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


class TokenEncryptionError(RuntimeError):
    """Raised when token encryption configuration or ciphertext is invalid."""


_ENVELOPE_PREFIX = "mg-token-v1."
_ALGORITHM = "AES-256-GCM"
_ASSOCIATED_DATA = b"medguardian:oauth-refresh-token:v1"
_NONCE_BYTES = 12
_KEY_BYTES = 32


def _decode_key(encoded_key: str | None) -> bytes:
    if not encoded_key or not encoded_key.strip():
        raise TokenEncryptionError(
            "MEDGUARDIAN_TOKEN_ENCRYPTION_KEY is required for token encryption."
        )

    value = encoded_key.strip()

    # Accept a 64-character hex key for operational convenience.
    if len(value) == _KEY_BYTES * 2:
        try:
            key = bytes.fromhex(value)
        except ValueError:
            key = b""
        if len(key) == _KEY_BYTES:
            return key

    # The preferred deployment format is URL-safe base64 containing 32 bytes.
    try:
        padded = value + ("=" * (-len(value) % 4))
        key = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise TokenEncryptionError(
            "MEDGUARDIAN_TOKEN_ENCRYPTION_KEY must encode a 32-byte key."
        ) from exc

    if len(key) != _KEY_BYTES:
        raise TokenEncryptionError(
            "MEDGUARDIAN_TOKEN_ENCRYPTION_KEY must encode a 32-byte key."
        )
    return key


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_bytes(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise TokenEncryptionError("Encrypted token envelope is invalid.")
    try:
        padded = value + ("=" * (-len(value) % 4))
        return base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise TokenEncryptionError("Encrypted token envelope is invalid.") from exc


class TokenEncryptionService:
    """Encrypt and decrypt refresh tokens using AES-256-GCM.

    The key is accepted only as constructor injection for tests or loaded from
    ``MEDGUARDIAN_TOKEN_ENCRYPTION_KEY``. It is never included in an envelope,
    return value, log message, or public attribute.
    """

    def __init__(self, key: str | None = None) -> None:
        self._cipher = AESGCM(_decode_key(key if key is not None else settings.medguardian_token_encryption_key))

    def encrypt(self, plaintext: str) -> str:
        if not isinstance(plaintext, str) or not plaintext:
            raise TokenEncryptionError("A non-empty refresh token is required.")

        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._cipher.encrypt(
            nonce,
            plaintext.encode("utf-8"),
            _ASSOCIATED_DATA,
        )
        envelope = {
            "v": 1,
            "alg": _ALGORITHM,
            "nonce": _encode_bytes(nonce),
            "ciphertext": _encode_bytes(ciphertext),
        }
        serialized = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        return _ENVELOPE_PREFIX + _encode_bytes(serialized)

    def decrypt(self, encrypted_value: str) -> str:
        if not isinstance(encrypted_value, str) or not encrypted_value.startswith(_ENVELOPE_PREFIX):
            raise TokenEncryptionError("Encrypted token envelope is invalid.")

        try:
            envelope = json.loads(
                _decode_bytes(encrypted_value[len(_ENVELOPE_PREFIX) :]).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise TokenEncryptionError("Encrypted token envelope is invalid.") from exc

        if not isinstance(envelope, dict) or envelope.get("v") != 1 or envelope.get("alg") != _ALGORITHM:
            raise TokenEncryptionError("Encrypted token envelope is invalid.")

        nonce = _decode_bytes(envelope.get("nonce"))
        ciphertext = _decode_bytes(envelope.get("ciphertext"))
        if len(nonce) != _NONCE_BYTES or not ciphertext:
            raise TokenEncryptionError("Encrypted token envelope is invalid.")

        try:
            plaintext = self._cipher.decrypt(nonce, ciphertext, _ASSOCIATED_DATA)
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise TokenEncryptionError("Encrypted token authentication failed.") from exc
