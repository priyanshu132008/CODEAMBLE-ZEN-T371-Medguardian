"""Privacy Sandbox — HIPAA/DPDP PII scrubbing layer.

Sits in front of every external (cloud LLM) call so that no Protected Health
Information (PHI) / personally identifiable information ever leaves the
MedGuardian boundary before being redacted. The scrubber is intentionally
regex-based and deterministic — no network, no model — so its behavior is
auditable for the judges.

Pattern coverage (Phase 1):
  - Standard Indian phone numbers (with/without +91 / 0 prefix).
  - Generic email addresses.
  - Project-specific identifiers such as "Patient ID: ZEN-T371".

The original tokens are kept in an in-memory mapping so that downstream
results can, in principle, be re-identified via `restore_payload` (placeholder
for now — restoration across the LLM round-trip is a Phase 2 concern).
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Redaction marker (single, shared token so it is easy to grep in logs)
# ---------------------------------------------------------------------------

REDACTED_MARKER = "[REDACTED_PII]"

# ---------------------------------------------------------------------------
# Regex catalogue
# ---------------------------------------------------------------------------
#
# Each entry is (label, compiled_pattern). Patterns are ordered from most
# specific (Patient ID) to most generic (phone, email) so that overlapping
# matches resolve correctly.

_PII_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # Project-specific identifiers, e.g. "Patient ID: ZEN-T371" or "ID ZEN-T371"
    (
        "patient_id",
        re.compile(
            r"(?i)\b(?:patient\s*id|id|case\s*id|mrn)\s*[:#]?\s*ZEN[-\s]?T\d{3,}\b"
        ),
    ),
    # Standard Indian phone numbers: +91 followed by 10 digits, or 0 followed by
    # 10 digits, or a bare 10-digit number starting 6-9. Tolerates spaces/dashes
    # both after the country/STD prefix and within the 10-digit subscriber
    # number (e.g. "+91 98765 43210", "098765-43210", "9876543210").
    (
        "indian_phone",
        re.compile(
            r"(?:\+91[\s-]?)?(?:0[\s-]?)?[6-9](?:\d[\s-]?){8}\d"
        ),
    ),
    # Generic email addresses
    (
        "email",
        re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    ),
]


class PIIScrubber:
    """Redact PII/PHI from free text before it reaches any external cloud API.

    A fresh instance owns its own in-memory redaction map; the class is
    stateless across instances by default so it is safe to instantiate per
    request.
    """

    def __init__(self) -> None:
        # token_id -> original_value, so results could be re-identified later.
        self._redaction_map: Dict[str, str] = {}
        self._counter: int = 0

    # ------------------------------------------------------------------
    # Anonymization
    # ------------------------------------------------------------------

    def anonymize_payload(self, text: str) -> str:
        """Return a copy of *text* with all matched PII replaced by the
        shared redaction marker.

        Each unique original token is stored in the in-memory map keyed by an
        opaque id, preserving the option to restore the payload later.
        """
        if not text:
            return text

        def _store_and_replace(match: re.Match, label: str) -> str:
            original = match.group(0)
            # Re-use the same token id for identical originals so the mapping
            # stays compact and reversible.
            if original not in self._redaction_map.values():
                self._counter += 1
                token_id = f"{label}_{self._counter}"
                self._redaction_map[token_id] = original
            return REDACTED_MARKER

        scrubbed = text
        for label, pattern in _PII_PATTERNS:
            scrubbed = pattern.sub(
                lambda m, _label=label: _store_and_replace(m, _label),
                scrubbed,
            )
        return scrubbed

    # ------------------------------------------------------------------
    # Restoration (Phase 2 placeholder)
    # ------------------------------------------------------------------

    def restore_payload(self, text: str) -> str:
        """Placeholder — re-identifies a scrubbed payload using the in-memory map.

        NOTE: Full restoration across an LLM round-trip is non-trivial (the
        model may rephrase, reorder, or drop markers) and is intentionally out
        of scope for Phase 1. This stub is reserved for the Phase 2 work so the
        public API is stable today.
        """
        # TODO(Phase 2): walk self._redaction_map and substitute markers back
        # to their originals, handling model-rephrased output.
        return text

    # ------------------------------------------------------------------
    # Introspection (handy for logs / debugging)
    # ------------------------------------------------------------------

    @property
    def redaction_map(self) -> Dict[str, str]:
        """Read-only view of the token_id -> original mapping."""
        return dict(self._redaction_map)