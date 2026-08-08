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
  - Explicit patient names supplied via the `names` parameter (regex cannot
    catch arbitrary names, so callers pass the known patient name(s) and the
    scrubber redacts them whole-word, case-insensitively).

The original tokens are kept in an in-memory mapping so that downstream
results can, in principle, be re-identified via `restore_payload` (placeholder
for now — restoration across the LLM round-trip is a Phase 2 concern).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

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
    # Project-specific identifiers, e.g. "Patient ID: ZEN-T371", "ID ZEN-T371",
    # "MRN: ZEN-T371", or a bare "ZEN-T371". The descriptive prefix is OPTIONAL
    # so a bare project ID is still caught, but the distinctive "ZEN-T###" core
    # is what actually anchors the match — no medication name or English word
    # contains that token, so clinical text is never falsely redacted here.
    (
        "patient_id",
        re.compile(
            r"(?i)\b(?:(?:patient\s*id|case\s*id|mrn|id)\s*[:#]?\s*)?ZEN[-\s]?T\d{3,}\b"
        ),
    ),
    # Standard Indian mobile numbers: an optional +91 or 0 prefix, then a 10-digit
    # subscriber number starting 6-9, with optional single spaces/dashes between
    # digit groups (e.g. "+91 98765 43210", "098765-43210", "9876543210").
    #
    # Tightened with negative lookarounds `(?<!\d)` / `(?!\d)` so the match is
    # confined to a STANDALONE digit run — it can never latch onto a slice of a
    # longer number (MRN, timestamp, order ID, account number). And because the
    # pattern is entirely numeric, it structurally cannot match a medication name
    # (Clopidogrel, Atorvastatin, Metformin), a dosage, or any English word.
    (
        "indian_phone",
        re.compile(
            r"(?<!\d)(?:\+91[\s-]?)?(?:0[\s-]?)?[6-9](?:\d[\s-]?){8}\d(?!\d)"
        ),
    ),
    # Generic email addresses. The trailing `(?![a-zA-Z0-9])` stops the TLD from
    # ending mid-word (so it won't grab "com" out of "x.commercial"). Requires an
    # `@`, so plain drug names / words are never matched.
    (
        "email",
        re.compile(
            r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}(?![a-zA-Z0-9])"
        ),
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
    # Internal: store an original and emit the redaction marker
    # ------------------------------------------------------------------

    def _redact(self, original: str, label: str) -> str:
        """Record *original* in the in-memory map (once per unique value) and
        return the shared redaction marker."""
        if original not in self._redaction_map.values():
            self._counter += 1
            self._redaction_map[f"{label}_{self._counter}"] = original
        return REDACTED_MARKER

    # ------------------------------------------------------------------
    # Anonymization
    # ------------------------------------------------------------------

    def anonymize_payload(self, text: str, names: Optional[List[str]] = None) -> str:
        """Return a copy of *text* with all matched PII replaced by the
        shared redaction marker.

        Args:
            text: The free text to scrub.
            names: Optional list of explicit patient names to redact. Regex
                cannot catch arbitrary names, so callers that know the
                patient's name pass it here; it is redacted whole-word and
                case-insensitively, ahead of the regex patterns.

        Each unique original token is stored in the in-memory map keyed by an
        opaque id, preserving the option to restore the payload later.
        """
        if not text:
            return text

        scrubbed = text

        # 1. Explicit names first — redact whole-word, case-insensitively.
        if names:
            for name in names:
                n = (name or "").strip()
                # Skip trivially short tokens to avoid nuking common words.
                if len(n) < 2:
                    continue
                scrubbed = re.sub(
                    r"\b" + re.escape(n) + r"\b",
                    lambda m: self._redact(m.group(0), "name"),
                    scrubbed,
                    flags=re.IGNORECASE,
                )

        # 2. Regex patterns (patient id, phone, email), most-specific first.
        for label, pattern in _PII_PATTERNS:
            scrubbed = pattern.sub(
                lambda m, _label=label: self._redact(m.group(0), _label),
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