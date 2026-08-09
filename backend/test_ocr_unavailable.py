"""Tests for the /api/upload OCR-unavailable 503 contract (OpenRouter).

When OCR extraction through OpenRouter fails (model unavailable / 404, rate
limited, or the provider errored), Agent 1 must return a labelled 503 with a
clean human-readable message — never the raw upstream JSON stack trace — so the
frontend UploadZone can show it verbatim in its red error box.
"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase

import httpx
from openai import APIConnectionError, NotFoundError

import main
from agents import document_intelligence as di
from agents.document_intelligence import OCRModelUnavailableError

EXPECTED_MESSAGE = "OCR Extraction failed via OpenRouter."

# A minimal 1x1 JPEG so the upload route's content-type + non-empty-file gates
# pass before we reach the mocked extraction step.
_JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xc0\x00\x0b"
    b"\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05"
    b"\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03"
    b"\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00"
    b"\xfb\xff\xd9"
)


async def _raise_ocr_unavailable(file_bytes: bytes, content_type: str | None) -> dict:
    """Stand in for extract_discharge when OpenRouter OCR fails."""
    raise OCRModelUnavailableError(model=di.MODEL)


class OCRUnavailableTests(IsolatedAsyncioTestCase):
    async def test_upload_returns_503_with_clean_message_when_model_unreachable(self):
        original = main.extract_discharge
        main.extract_discharge = _raise_ocr_unavailable
        try:
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/upload",
                    files={"file": ("summary.jpg", _JPEG_BYTES, "image/jpeg")},
                    data={"consent_granted": "true", "abha_id": "12341234123412"},
                )
        finally:
            main.extract_discharge = original

        self.assertEqual(resp.status_code, 503)
        body = resp.json()
        self.assertIn("error", body)
        message = body["error"]
        # The exact human-readable message the frontend must render verbatim.
        self.assertEqual(message, EXPECTED_MESSAGE)
        # Must NOT leak the raw upstream JSON / stack-trace shape.
        self.assertNotIn("Traceback", message)
        self.assertNotIn("model not found", message)
        self.assertNotIn("\\", message)


class ExtractDischargeInterceptionTests(IsolatedAsyncioTestCase):
    """extract_discharge must try the primary model + fallbacks, then raise the
    typed, clean OCRModelUnavailableError (with the OpenRouter message) instead
    of a raw RuntimeError carrying the upstream JSON body."""

    async def _assert_raises_unavailable(self, upstream_error: Exception) -> None:
        original = di._call_model
        attempted: list[str] = []

        async def _boom(model, user_content, timeout=25.0):
            attempted.append(model)
            raise upstream_error

        di._call_model = _boom
        try:
            with self.assertRaises(OCRModelUnavailableError) as ctx:
                await di.extract_discharge(_JPEG_BYTES, "image/jpeg")
        finally:
            di._call_model = original

        # The typed error carries the clean, exact human-readable message.
        self.assertEqual(str(ctx.exception), EXPECTED_MESSAGE)
        # It attempted the configured primary OpenRouter vision model first.
        self.assertEqual(attempted[0], di.MODEL)
        self.assertIn("google/gemini-2.5-flash", attempted[0])

    async def test_not_found_error_intercepted(self):
        # OpenRouter returns 404 when the vision model slug is unavailable.
        response = httpx.Response(
            status_code=404,
            request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
        )
        await self._assert_raises_unavailable(
            NotFoundError("model not found", response=response, body=None)
        )

    async def test_connection_error_intercepted(self):
        # OpenRouter / network is unreachable (connection refused).
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        await self._assert_raises_unavailable(
            APIConnectionError(message="connection refused", request=request)
        )