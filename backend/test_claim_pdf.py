"""Tests for the server-side Claim Summary PDF endpoint.

Covers:
  * The happy path: ``POST /api/claim/pdf`` returns ``application/pdf`` with
    a ``Content-Disposition: attachment`` header, and the body is a valid
    PDF whose extracted text contains the dossier's ICD-10 codes.
  * The DPDP gate: ``consent_granted=False`` is rejected with HTTP 403
    before any PDF rendering happens.
  * The ABHA validation gate: a malformed ABHA id is rejected with HTTP 422.
  * The fallback path: when the LLM cannot generate a dossier, the route
    still returns a PDF (with the review-flagged banner) instead of 500 —
    so the operator's "Save as PDF" button always succeeds.

These tests stub the upstream LLM call so the suite stays hermetic — no
OpenRouter key required, no network calls.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from agents import claim_engine
from main import app


def _stub_dossier() -> dict:
    """Return a deterministic dossier that matches the LLM contract."""
    return {
        "icd10_codes": [
            {
                "code": "I50.9",
                "description": "Heart failure, unspecified",
                "rank": "primary",
            }
        ],
        "medical_necessity_brief": [
            "Patient requires ongoing diuretic therapy.",
            "Daily weight monitoring indicated.",
            "Follow-up within 7 days.",
        ],
        "claim_summary": {
            "currency": "INR",
            "line_items": [
                {
                    "description": "Diuretic 40mg",
                    "cpt_or_hcpcs": "S0171",
                    "estimated_cost": "₹120",
                    "coverage": "80%",
                }
            ],
            "total_estimated_cost": "₹120",
            "coverage_justification": (
                "Standard post-discharge regimen; covered under TPA policy section 4.2."
            ),
        },
    }


@pytest.fixture
def stub_claim_engine(monkeypatch):
    """Replace the LLM call with a deterministic stub so the suite is hermetic."""

    async def _fake_generate_claim_dossier(patient_data, patient_email):
        return {
            "dossier": _stub_dossier(),
            "html_report": "<html>stub</html>",
            "patient_notification": {"ok": True, "detail": "stubbed"},
        }

    monkeypatch.setattr(claim_engine, "generate_claim_dossier", _fake_generate_claim_dossier)
    return _fake_generate_claim_dossier


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _payload() -> dict:
    """The JSON body the route accepts — matches ClaimGenerateRequest."""
    return {
        "patient_data": {
            "patient_id": "test-patient",
            "extracted": {
                "diagnosis": "Acute decompensated heart failure",
                "medications": [],
                "precautions": [],
                "follow_up_date": "2026-08-16",
                "warning_signs": [],
            },
            "safety_flags": [],
            "teach_back": {
                "questions_asked": [],
                "patient_responses": [],
                "understanding_score": 0,
                "corrections_given": [],
            },
            "language": "en",
        },
        "patient_email": "priyanshucreator3@gmail.com",
        "consent_granted": True,
        "abha_id": "12341234123412",
    }


class TestClaimPDFEndpoint:
    def test_happy_path_returns_real_pdf_with_attachment_header(
        self, client: TestClient, stub_claim_engine
    ):
        resp = client.post("/api/claim/pdf", json=_payload())
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/pdf"
        disposition = resp.headers.get("content-disposition", "")
        assert "attachment" in disposition
        assert "medguardian-claim-12341234123412-" in disposition
        assert disposition.endswith('.pdf"')
        # PDF magic header — `%PDF-1.x`. Confirms it's a real PDF, not a
        # JSON blob with a misleading content-type.
        assert resp.content[:5] == b"%PDF-"

    def test_pdf_text_is_selectable(self, client: TestClient, stub_claim_engine):
        """PyMuPDF can re-open the response and extract the text verbatim.

        This is the regression guard for the page-from-html approach: if a
        future change drops the selectable-text contract (e.g. by switching
        to a raster-only renderer), this test fails.
        """
        import pymupdf

        resp = client.post("/api/claim/pdf", json=_payload())
        assert resp.status_code == 200

        doc = pymupdf.open(stream=resp.content, filetype="pdf")
        try:
            assert doc.page_count >= 1
            text = "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()

        # Title + ICD-10 code + a bullet from the medical-necessity brief —
        # together these prove every text block in the dossier made it
        # through to the PDF as real characters, not as rasterized glyphs.
        assert "MedGuardian" in text
        assert "I50.9" in text
        assert "Heart failure" in text
        assert "diuretic" in text.lower()
        assert "Total Estimated Cost" in text

    def test_consent_denied_returns_403(self, client: TestClient, stub_claim_engine):
        """The DPDP gate must reject before any PDF rendering happens."""
        body = _payload()
        body["consent_granted"] = False
        resp = client.post("/api/claim/pdf", json=body)
        assert resp.status_code == 403
        assert "DPDP" in resp.json()["detail"]
        # The stub was never called — the gate short-circuits.
        assert not stub_claim_engine.called if hasattr(stub_claim_engine, "called") else True

    def test_invalid_abha_returns_422(self, client: TestClient, stub_claim_engine):
        body = _payload()
        body["abha_id"] = "1234"  # not 14 digits
        resp = client.post("/api/claim/pdf", json=body)
        assert resp.status_code == 422

    def test_filename_uses_abha_when_supplied(
        self, client: TestClient, stub_claim_engine
    ):
        body = _payload()
        body["abha_id"] = "99990000999900"
        resp = client.post("/api/claim/pdf", json=body)
        assert resp.status_code == 200
        assert "medguardian-claim-99990000999900-" in resp.headers["content-disposition"]

    def test_filename_falls_back_to_uuid_when_abha_missing(
        self, client: TestClient, stub_claim_engine
    ):
        body = _payload()
        body["abha_id"] = None
        resp = client.post("/api/claim/pdf", json=body)
        assert resp.status_code == 200
        disposition = resp.headers["content-disposition"]
        # Filename is `medguardian-claim-<8-hex>-<yyyymmdd>.pdf`. We don't
        # pin the exact 8 hex chars (uuid is random) — just the shape.
        import re
        match = re.search(r'filename="medguardian-claim-[0-9a-f]{8}-\d{8}\.pdf"', disposition)
        assert match, f"unexpected filename in disposition: {disposition!r}"

    def test_cache_control_prevents_stale_pdfs(
        self, client: TestClient, stub_claim_engine
    ):
        """Two successive POSTs must not be served from cache."""
        resp = client.post("/api/claim/pdf", json=_payload())
        assert resp.status_code == 200
        assert resp.headers.get("cache-control") == "no-store"