"""Deterministic zero-trust guard for outbound AI payloads.

This module is deliberately small and policy-oriented.  It creates new,
allowlisted clinical payloads and rejects raw-document inference unless the
destination is explicitly configured as a local endpoint.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

from agents.privacy_sandbox import PIIScrubber


class ComplianceBoundaryError(ValueError):
    """Raised when an outbound AI request violates the configured boundary."""


REDACTED_MARKER = "[REDACTED_PII]"

# These are the only top-level fields copied into a generic clinical payload.
# Identity, transport, and arbitrary caller-supplied fields are intentionally
# absent.  ``name`` is only allowed inside a medication object below.
_CLINICAL_FIELDS = frozenset(
    {
        "diagnosis",
        "medications",
        "precautions",
        "follow_up",
        "follow_up_date",
        "warning_signs",
        "allergies",
        "safety_flags",
        "clinical_findings",
        "findings",
        "symptoms",
        "dosage",
        "dose",
        "frequency",
        "duration",
        "route",
        "instructions",
        "medication_names",
        "clinical_terms",
        "teach_back_comprehension_score",
        "understanding_score",
        "questions_asked",
        "patient_responses",
        "corrections_given",
        "patient_response",
        "extracted",
        "teach_back",
        "current_teach_back",
        "current_teach_back_state",
        "language",
    }
)

_MEDICATION_FIELDS = frozenset(
    {"name", "dosage", "dose", "frequency", "duration", "route", "instructions"}
)
_SAFETY_FLAG_FIELDS = frozenset(
    {
        "type",
        "severity",
        "medication",
        "allergy",
        "message",
        "detail",
        "description",
        "interaction",
        "action",
    }
)
_TEACH_BACK_FIELDS = frozenset(
    {"questions_asked", "patient_responses", "understanding_score", "corrections_given"}
)
_NAME_KEYS = frozenset({"patient_name", "full_name", "patient"})


def collect_explicit_names(value: object, *, _parent_key: str = "") -> list[str]:
    """Collect explicitly labelled patient names without treating drug names as names."""

    names: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in _NAME_KEYS and isinstance(item, str) and item.strip():
                names.append(item.strip())
            elif key_lower == "name" and _parent_key not in {"medications", "medication"}:
                if isinstance(item, str) and item.strip():
                    names.append(item.strip())
            names.extend(collect_explicit_names(item, _parent_key=key_lower))
    elif isinstance(value, list):
        for item in value:
            names.extend(collect_explicit_names(item, _parent_key=_parent_key))
    return list(dict.fromkeys(names))


def _scrub_string(value: str, scrubber: PIIScrubber, names: list[str]) -> str:
    return scrubber.anonymize_payload(value, names=names)


def _scrub_scalar(value: object, scrubber: PIIScrubber, names: list[str]) -> object:
    if isinstance(value, str):
        return _scrub_string(value, scrubber, names)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _scrub_string(str(value), scrubber, names)


def _copy_list(value: object, scrubber: PIIScrubber, names: list[str]) -> list[object]:
    if not isinstance(value, list):
        return []
    result: list[object] = []
    for item in value:
        if isinstance(item, Mapping):
            # Generic clinical lists have no safe structure for mappings. Do
            # not stringify them, since that could carry unknown fields across
            # the boundary. Dedicated structured lists are handled separately.
            continue
        if isinstance(item, str):
            result.append(_scrub_string(item, scrubber, names))
        elif isinstance(item, (bool, int, float)) or item is None:
            result.append(item)
        # Arbitrary objects are dropped rather than converted to strings.
    return result


def _copy_medications(value: object, scrubber: PIIScrubber, names: list[str]) -> list[dict]:
    if not isinstance(value, list):
        return []
    result: list[dict] = []
    for medication in value:
        if not isinstance(medication, Mapping):
            result.append({"name": _scrub_scalar(medication, scrubber, names)})
            continue
        result.append(
            {
                str(key): _scrub_scalar(item, scrubber, names)
                for key, item in medication.items()
                if str(key).lower() in _MEDICATION_FIELDS
            }
        )
    return result


def _copy_safety_flags(value: object, scrubber: PIIScrubber, names: list[str]) -> list[object]:
    if not isinstance(value, list):
        return []
    result: list[object] = []
    for flag in value:
        if not isinstance(flag, Mapping):
            result.append(_scrub_scalar(flag, scrubber, names))
            continue
        result.append(
            {
                str(key): _scrub_scalar(item, scrubber, names)
                for key, item in flag.items()
                if str(key).lower() in _SAFETY_FLAG_FIELDS
            }
        )
    return result


def _copy_teach_back(value: object, scrubber: PIIScrubber, names: list[str]) -> dict:
    if not isinstance(value, Mapping):
        return {}
    result: dict = {}
    for key, item in value.items():
        key_lower = str(key).lower()
        if key_lower not in _TEACH_BACK_FIELDS:
            continue
        if key_lower == "understanding_score":
            result[str(key)] = item if isinstance(item, (int, float)) else 0
        else:
            result[str(key)] = _copy_list(item, scrubber, names)
    return result


def prepare_clinical_payload(
    payload: Mapping[str, object] | None,
    *,
    names: Iterable[str] | None = None,
    scrubber: PIIScrubber | None = None,
) -> dict:
    """Return a new, strictly allowlisted and deterministically scrubbed dict.

    The input object is never returned or mutated.  Unknown fields, including
    identity fields such as ``patient_id``, ``mrn``, ``email``, ``phone``,
    ``abha_id``, and UUIDs, are excluded rather than merely scrubbed.
    """

    if not isinstance(payload, Mapping):
        return {}

    active_scrubber = scrubber or PIIScrubber()
    known_names = [str(name).strip() for name in names or [] if str(name).strip()]
    known_names.extend(collect_explicit_names(payload))
    known_names = list(dict.fromkeys(known_names))

    result: dict = {}
    for key, value in payload.items():
        key_text = str(key)
        key_lower = key_text.lower()
        if key_lower not in _CLINICAL_FIELDS:
            continue

        if key_lower in {"medications"}:
            result[key_text] = _copy_medications(value, active_scrubber, known_names)
        elif key_lower in {"safety_flags"}:
            result[key_text] = _copy_safety_flags(value, active_scrubber, known_names)
        elif key_lower in {"teach_back", "current_teach_back", "current_teach_back_state"}:
            result[key_text] = _copy_teach_back(value, active_scrubber, known_names)
        elif key_lower == "extracted":
            result[key_text] = prepare_clinical_payload(
                value if isinstance(value, Mapping) else {},
                names=known_names,
                scrubber=active_scrubber,
            )
        elif isinstance(value, list):
            result[key_text] = _copy_list(value, active_scrubber, known_names)
        elif isinstance(value, Mapping):
            # Nested arbitrary objects are not trusted.  Recursing through the
            # same allowlist retains only known clinical keys.
            result[key_text] = prepare_clinical_payload(
                value,
                names=known_names,
                scrubber=active_scrubber,
            )
        else:
            result[key_text] = _scrub_scalar(value, active_scrubber, known_names)

    return result


def prepare_agent_context(
    patient_data: Mapping[str, object] | None,
    *,
    names: Iterable[str] | None = None,
    scrubber: PIIScrubber | None = None,
) -> dict:
    """Prepare the subset of shared Agent 1–5 state needed by an AI prompt."""

    return prepare_clinical_payload(patient_data, names=names, scrubber=scrubber)


def _normalise_endpoint(endpoint: str) -> str:
    parsed = urlsplit(str(endpoint).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ComplianceBoundaryError("AI endpoint must be an absolute HTTP(S) URL.")
    if parsed.username or parsed.password:
        raise ComplianceBoundaryError("AI endpoint credentials are not permitted.")
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def _is_local_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def assert_raw_document_endpoint_is_local(
    endpoint: str,
    explicitly_local_endpoints: Iterable[str],
) -> str:
    """Fail closed unless *endpoint* is explicitly allowlisted and local.

    The endpoint name itself is not trusted.  Both explicit configuration and
    a local/private destination are required before raw document bytes may be
    sent to an AI inference service.
    """

    normalised_endpoint = _normalise_endpoint(endpoint)
    configured = {
        _normalise_endpoint(item)
        for item in explicitly_local_endpoints
        if str(item).strip()
    }
    if not configured:
        raise ComplianceBoundaryError(
            "Raw document inference is disabled: no explicitly local AI endpoint is configured."
        )
    if normalised_endpoint not in configured:
        raise ComplianceBoundaryError(
            "Raw document inference endpoint is not explicitly classified as local."
        )

    host = urlsplit(normalised_endpoint).hostname or ""
    if not _is_local_host(host):
        raise ComplianceBoundaryError(
            "Raw document inference endpoint is not a local/private destination."
        )
    return normalised_endpoint


def configured_local_ai_endpoints(value: str | None) -> list[str]:
    """Parse the comma-separated explicit local endpoint allowlist."""

    return [item.strip() for item in (value or "").split(",") if item.strip()]


def payload_as_json(payload: Mapping[str, object]) -> str:
    """Serialize an already-guarded payload for prompt construction."""

    return json.dumps(payload, ensure_ascii=False, indent=2)
