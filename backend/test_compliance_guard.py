"""Focused tests for the Task 3A zero-trust AI egress guard."""

from __future__ import annotations

import unittest

from agents.compliance_guard import (
    ComplianceBoundaryError,
    assert_raw_document_endpoint_is_local,
    prepare_clinical_payload,
)
from agents.privacy_sandbox import PIIScrubber


class ComplianceGuardTests(unittest.TestCase):
    def test_clinical_allowlist_removes_direct_identifiers(self):
        source = {
            "name": "Ramesh Kumar",
            "email": "ramesh@example.com",
            "phone": "+91 98765 43210",
            "abha_id": "12341234123412",
            "patient_id": "patient-123",
            "mrn": "MRN-7788",
            "uuid": "11111111-1111-4111-8111-111111111111",
            "diagnosis": "Acute bronchitis",
        }

        guarded = prepare_clinical_payload(source)

        self.assertNotIn("name", guarded)
        self.assertNotIn("email", guarded)
        self.assertNotIn("phone", guarded)
        self.assertNotIn("abha_id", guarded)
        self.assertNotIn("patient_id", guarded)
        self.assertNotIn("mrn", guarded)
        self.assertNotIn("uuid", guarded)
        self.assertEqual(guarded["diagnosis"], "Acute bronchitis")

    def test_clinical_fields_survive(self):
        source = {
            "diagnosis": "Acute bronchitis",
            "medications": [{"name": "Amoxicillin", "dosage": "500mg"}],
            "warning_signs": ["Shortness of breath"],
            "safety_flags": [{"severity": "CRITICAL", "message": "Allergy conflict"}],
            "follow_up": "2026-09-15",
        }

        guarded = prepare_clinical_payload(source)

        self.assertEqual(guarded["diagnosis"], source["diagnosis"])
        self.assertEqual(guarded["medications"][0]["dosage"], "500mg")
        self.assertEqual(guarded["warning_signs"], ["Shortness of breath"])
        self.assertEqual(guarded["safety_flags"][0]["severity"], "CRITICAL")
        self.assertEqual(guarded["follow_up"], "2026-09-15")

    def test_generic_clinical_list_drops_nested_arbitrary_mapping(self):
        guarded = prepare_clinical_payload(
            {
                "warning_signs": [
                    "Shortness of breath",
                    {"email": "patient@example.com", "secret": "must not cross"},
                    42,
                    None,
                ]
            }
        )

        self.assertEqual(guarded["warning_signs"], ["Shortness of breath", 42, None])
        self.assertNotIn("patient@example.com", str(guarded))
        self.assertNotIn("must not cross", str(guarded))

    def test_allowlist_returns_new_objects(self):
        source = {"medications": [{"name": "Amoxicillin", "dosage": "500mg"}]}
        guarded = prepare_clinical_payload(source)
        self.assertIsNot(guarded, source)
        self.assertIsNot(guarded["medications"], source["medications"])
        self.assertIsNot(guarded["medications"][0], source["medications"][0])

    def test_allowlisted_free_text_is_scrubbed(self):
        guarded = prepare_clinical_payload(
            {"patient_response": "I am Ramesh Kumar, email ramesh@example.com"},
            names=["Ramesh Kumar"],
        )
        self.assertNotIn("Ramesh Kumar", guarded["patient_response"])
        self.assertNotIn("ramesh@example.com", guarded["patient_response"])

    def test_privacy_sandbox_redacts_abha_uuid_and_labelled_mrn(self):
        scrubber = PIIScrubber()
        text = (
            "ABHA: 12341234123412, patient UUID: 11111111-1111-4111-8111-111111111111, "
            "MRN: MRN-7788"
        )
        scrubbed = scrubber.anonymize_payload(text)
        self.assertNotIn("12341234123412", scrubbed)
        self.assertNotIn("11111111-1111-4111-8111-111111111111", scrubbed)
        self.assertNotIn("MRN-7788", scrubbed)

    def test_raw_document_endpoint_rejects_unclassified_remote_endpoint(self):
        with self.assertRaises(ComplianceBoundaryError):
            assert_raw_document_endpoint_is_local(
                "https://api.example.com/v1",
                ["http://127.0.0.1:11434/v1"],
            )

    def test_explicitly_local_endpoint_is_accepted(self):
        endpoint = assert_raw_document_endpoint_is_local(
            "http://127.0.0.1:11434/v1/",
            ["http://127.0.0.1:11434/v1"],
        )
        self.assertEqual(endpoint, "http://127.0.0.1:11434/v1")


if __name__ == "__main__":
    unittest.main()
