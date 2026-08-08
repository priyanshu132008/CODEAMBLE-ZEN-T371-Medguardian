"""Unit tests for Task 3B-3a calendar credential infrastructure."""

from __future__ import annotations

import base64
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.api.dependencies import AuthenticatedUser
from app.schemas.calendar import CalendarConnectionProfile
from app.services.calendar_connection_service import (
    CALENDAR_CONNECTION_COLUMNS,
    CalendarConnectionService,
)
from app.services.token_encryption import TokenEncryptionError, TokenEncryptionService


BACKEND_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BACKEND_DIR / "db" / "schema.sql"


def _test_key() -> str:
    return base64.urlsafe_b64encode(bytes(range(32))).decode("ascii").rstrip("=")


class TokenEncryptionTests(unittest.TestCase):
    def setUp(self):
        self.key = _test_key()
        self.service = TokenEncryptionService(key=self.key)

    def test_plaintext_round_trips(self):
        encrypted = self.service.encrypt("refresh-token-value")
        self.assertEqual(self.service.decrypt(encrypted), "refresh-token-value")

    def test_same_plaintext_produces_different_ciphertext(self):
        first = self.service.encrypt("refresh-token-value")
        second = self.service.encrypt("refresh-token-value")
        self.assertNotEqual(first, second)

    def test_tampered_ciphertext_fails(self):
        encrypted = self.service.encrypt("refresh-token-value")
        envelope = encrypted.split(".", 2)[-1]
        raw = bytearray(base64.urlsafe_b64decode(envelope + "=" * (-len(envelope) % 4)))
        document = json.loads(raw.decode("utf-8"))
        ciphertext = bytearray(
            base64.urlsafe_b64decode(
                document["ciphertext"] + "=" * (-len(document["ciphertext"]) % 4)
            )
        )
        ciphertext[-1] ^= 1
        document["ciphertext"] = base64.urlsafe_b64encode(bytes(ciphertext)).decode("ascii").rstrip("=")
        tampered = "mg-token-v1." + base64.urlsafe_b64encode(
            json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("ascii").rstrip("=")

        with self.assertRaises(TokenEncryptionError):
            self.service.decrypt(tampered)

    def test_missing_key_fails_closed(self):
        with patch("app.services.token_encryption.settings.medguardian_token_encryption_key", ""):
            with self.assertRaises(TokenEncryptionError):
                TokenEncryptionService()

    def test_plaintext_and_key_are_not_returned(self):
        plaintext = "refresh-token-value"
        encrypted = self.service.encrypt(plaintext)
        self.assertNotIn(plaintext, encrypted)
        self.assertNotIn(self.key, encrypted)
        self.assertFalse(hasattr(self.service, "key"))


class CalendarSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = SCHEMA_PATH.read_text(encoding="utf-8").lower()

    def test_calendar_connections_definition_and_foreign_key_exist(self):
        metadata_start = self.schema.index("create table if not exists calendar_connections")
        secrets_start = self.schema.index("create table if not exists calendar_connection_secrets")
        metadata_definition = self.schema[metadata_start:secrets_start]
        self.assertNotIn("encrypted_refresh_token", metadata_definition)
        self.assertIn(
            "user_id              uuid not null references auth.users(id) on delete cascade",
            metadata_definition,
        )

    def test_secret_table_is_cascading_and_unique_per_connection(self):
        self.assertIn(
            "create table if not exists calendar_connection_secrets",
            self.schema,
        )
        self.assertIn(
            "connection_id          uuid not null references calendar_connections(id) on delete cascade",
            self.schema,
        )
        self.assertIn("unique (connection_id)", self.schema)

    def test_unique_user_provider_constraint_exists(self):
        self.assertIn(
            "unique (user_id, provider)",
            self.schema,
        )

    def test_rls_and_own_user_policies_exist(self):
        self.assertIn("alter table calendar_connections enable row level security", self.schema)
        self.assertIn("alter table calendar_connection_secrets enable row level security", self.schema)
        self.assertIn("using (auth.uid() = user_id)", self.schema)
        self.assertIn("with check (auth.uid() = user_id)", self.schema)
        self.assertNotIn("create policy calendar_connection_secrets", self.schema)
        self.assertNotIn("to anon", self.schema)
        self.assertNotIn("for all to public", self.schema)


class _FakeQuery:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.selected_columns: list[str] = []
        self.upsert_payloads: list[dict] = []
        self.filters: list[tuple[str, str]] = []

    def select(self, columns: str):
        self.selected_columns.append(columns)
        return self

    def upsert(self, payload: dict, **kwargs):
        self.upsert_payloads.append(payload)
        return self

    def eq(self, column: str, value: str):
        self.filters.append((column, value))
        return self

    def limit(self, _value: int):
        return self

    def delete(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _FakeClient:
    def __init__(self, tables: dict[str, _FakeQuery]):
        self.tables = tables
        self.table_names: list[str] = []

    def table(self, name: str):
        self.table_names.append(name)
        return self.tables[name]


class CalendarServiceTests(unittest.TestCase):
    user = AuthenticatedUser(
        user_id="11111111-1111-4111-8111-111111111111",
        email="patient@example.com",
    )

    def setUp(self):
        self.encryption = TokenEncryptionService(key=_test_key())
        self.profile_row = {
            "id": "22222222-2222-4222-8222-222222222222",
            "user_id": self.user.user_id,
            "provider": "google",
            "google_account_email": "calendar@example.com",
            "calendar_id": "primary",
            "scopes": ["calendar.readonly"],
            "created_at": None,
            "updated_at": None,
        }

    def test_profile_and_metadata_columns_exclude_encrypted_token(self):
        self.assertNotIn("encrypted_refresh_token", CalendarConnectionProfile.model_fields)
        self.assertNotIn("encrypted_refresh_token", CALENDAR_CONNECTION_COLUMNS)

    def test_secret_persistence_uses_backend_only_client(self):
        metadata_query = _FakeQuery([self.profile_row])
        secret_query = _FakeQuery([])
        authenticated_client = _FakeClient({"calendar_connections": metadata_query})
        service_client = _FakeClient({"calendar_connection_secrets": secret_query})
        service = CalendarConnectionService(encryption_service=self.encryption)

        with (
            patch(
                "app.services.calendar_connection_service.get_authenticated_supabase_client",
                return_value=authenticated_client,
            ),
            patch(
                "app.services.calendar_connection_service.get_supabase_service_client",
                return_value=service_client,
            ),
        ):
            profile = service.save_google_connection(
                current_user=self.user,
                access_token="user-access-token",
                refresh_token="plain-refresh-token",
            )

        self.assertEqual(profile.id.hex, "22222222222242228222222222222222")
        self.assertEqual(authenticated_client.table_names, ["calendar_connections"])
        self.assertEqual(service_client.table_names, ["calendar_connection_secrets"])
        self.assertNotIn("encrypted_refresh_token", metadata_query.upsert_payloads[0])
        self.assertIn("encrypted_refresh_token", secret_query.upsert_payloads[0])
        self.assertNotIn("plain-refresh-token", str(secret_query.upsert_payloads[0]))

    def test_missing_service_role_configuration_fails_closed(self):
        service = CalendarConnectionService(encryption_service=self.encryption)
        with patch(
            "app.services.calendar_connection_service.get_supabase_service_client",
            side_effect=RuntimeError("secret client unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                service.save_google_connection(
                    current_user=self.user,
                    access_token="user-access-token",
                    refresh_token="plain-refresh-token",
                )


if __name__ == "__main__":
    unittest.main()
