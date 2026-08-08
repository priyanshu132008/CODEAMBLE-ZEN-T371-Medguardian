"""Authentication request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class AuthCredentials(BaseModel):
    """Credentials accepted by the backend auth gateway.

    ``role`` and ``name`` remain accepted for compatibility with the current
    frontend payload, but the backend never uses them for authorization.
    """

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    role: str | None = None
    name: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value: str) -> str:
        normalized = value.strip()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("A valid email address is required.")
        return normalized


class AuthResponse(BaseModel):
    """Stable frontend-compatible response for login and registration."""

    access_token: str | None = None
    token: str | None = None
    user_id: str | None = None
    email: str | None = None
    name: str
    role: str = "patient"
    abha_id: str | None = None
    email_confirmation_required: bool = False
