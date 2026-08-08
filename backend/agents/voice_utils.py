"""Voice utilities: Sarvam AI Text-to-Speech and Speech-to-Text integration.

Provides async helpers for converting text to audio (TTS) and audio bytes to
transcript (STT) via the Sarvam AI API. Requires the SARVAM_API_KEY environment
variable to be set.
"""

from __future__ import annotations

import logging
import os
from typing import Dict

import httpx

logger = logging.getLogger(__name__)

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")


class SarvamUnavailableError(RuntimeError):
    """Raised when the Sarvam AI STT endpoint is unreachable or returns a non-2xx status.

    Carries a user-safe message so the route can surface it directly without
    leaking upstream error details.
    """

    def __init__(self, user_message: str, *, status_code: int = 503) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code

TTS_URL = "https://api.sarvam.ai/text-to-speech"
STT_URL = "https://api.sarvam.ai/speech-to-text"

# Map our app's short language codes to Sarvam's target_language_code values.
LANGUAGE_CODE_MAP: Dict[str, str] = {
    "hi": "hi-IN",
    "mr": "mr-IN",
    "en": "en-IN",
}


async def generate_tts(text: str, language: str) -> str:
    """Convert text to speech via Sarvam AI.

    Args:
        text: The text to synthesise.
        language: One of our app language codes ("hi", "mr", "en").

    Returns:
        A base64-encoded audio string (first item of the `audios` array).
    """
    target_language_code = LANGUAGE_CODE_MAP.get(language, "en-IN")

    headers = {"api-subscription-key": SARVAM_API_KEY}
    payload = {
        "text": text,
        "target_language_code": target_language_code,
        "speaker": "shubh",
        "model": "bulbul:v3",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(TTS_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    return data["audios"][0]


async def transcribe_stt(audio_bytes: bytes) -> str:
    """Transcribe audio bytes to text via Sarvam AI.

    Args:
        audio_bytes: Raw audio file bytes (e.g. from a FastAPI UploadFile).

    Returns:
        The transcript string from the Sarvam response.

    Raises:
        SarvamUnavailableError: If the Sarvam STT endpoint is unreachable,
            times out, or returns a non-2xx status (e.g. 503 during an
            outage). The caller is expected to map this to a clean 503 JSON
            response rather than letting it crash the request.
    """
    headers = {"api-subscription-key": SARVAM_API_KEY}

    user_message = (
        "Voice service is temporarily overloaded. Please type your response instead."
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                STT_URL,
                headers=headers,
                files={"file": ("audio.wav", audio_bytes)},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        # Sarvam returned an error status (e.g. 503 Service Unavailable).
        logger.error(
            "Sarvam STT returned non-2xx status %s: %s",
            exc.response.status_code,
            exc.response.text[:500],
        )
        raise SarvamUnavailableError(user_message) from exc
    except httpx.RequestError as exc:
        # Network-level failure: connection refused, DNS error, timeout, etc.
        logger.error("Sarvam STT request failed: %s: %s", type(exc).__name__, exc)
        raise SarvamUnavailableError(user_message) from exc

    return data["transcript"]