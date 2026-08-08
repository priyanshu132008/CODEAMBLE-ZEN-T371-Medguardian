"""Agent 2: Safety Cross-Check.

A purely rule-based, deterministic agent that checks a list of extracted
medications against a CSV dataset to find drug interactions and duplicate
therapies, and cross-references the patient's documented allergies against
the prescribed medications to flag contraindicated drugs. No LLM APIs are used.
"""

from __future__ import annotations

import itertools
import os
from typing import Any, Dict, List

import pandas as pd
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Pydantic models (strict JSON contract from context.md)
# ---------------------------------------------------------------------------


class Medication(BaseModel):
    name: str
    dosage: str
    frequency: str
    duration: str


class SafetyFlag(BaseModel):
    type: str  # "interaction" | "duplicate" | "dosage_anomaly"
    medications_involved: List[str]
    severity: str  # "low" | "medium" | "high"
    message: str


# ---------------------------------------------------------------------------
# Load the drug interactions dataset ONCE at import time.
# ---------------------------------------------------------------------------

CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "drug_interactions.csv",
)

# Global in-memory lookup table. Loaded once, not per request.
_interactions_df: pd.DataFrame = pd.read_csv(CSV_PATH)

# Normalise to lowercase for case-insensitive matching.
_interactions_df["drug_a"] = _interactions_df["drug_a"].str.lower()
_interactions_df["drug_b"] = _interactions_df["drug_b"].str.lower()


# ---------------------------------------------------------------------------
# Core rule-based safety check.
# ---------------------------------------------------------------------------


def run_safety_check(medications: List[Medication]) -> List[SafetyFlag]:
    """Check patient medications against the interaction CSV.

    Generates all unique pairs of the patient's medications and looks each
    pair up in the dataset (checking both drug_a/drug_b and drug_b/drug_a
    orderings). Returns a list of SafetyFlag for every match found.
    """
    flags: List[SafetyFlag] = []

    # Extract lowercase medication names.
    names = [med.name.lower() for med in medications if med.name]

    # All unique pairs (order-independent generation).
    for drug_a, drug_b in itertools.combinations(names, 2):
        # Match in either ordering.
        match = _interactions_df[
            (
                (_interactions_df["drug_a"] == drug_a)
                & (_interactions_df["drug_b"] == drug_b)
            )
            | (
                (_interactions_df["drug_a"] == drug_b)
                & (_interactions_df["drug_b"] == drug_a)
            )
        ]

        for _, row in match.iterrows():
            flags.append(
                SafetyFlag(
                    type=row["type"],
                    medications_involved=[drug_a, drug_b],
                    severity=row["severity"],
                    message=row["message"],
                )
            )

    return flags


# ---------------------------------------------------------------------------
# Allergy cross-referencing engine.
#
# The interaction CSV above catches drug-drug conflicts. This layer catches
# drug-ALLERGY conflicts: a documented patient allergy (e.g. "Penicillin")
# against a prescribed medication that belongs to the same drug family
# (e.g. "Amoxicillin", a penicillin-class beta-lactam). These are clinically
# the most dangerous prescribing errors, so any match is emitted as a
# CRITICAL `allergy_conflict` safety flag.
#
# The flag shape differs from the interaction `SafetyFlag` above — it carries
# the singular `medication` and `allergy` it matched, per the shared contract
# — so these are returned as plain dicts rather than SafetyFlag instances.
# ---------------------------------------------------------------------------

# Each family maps an allergen (and its aliases, e.g. "Penicillin" / "PCN") to
# the list of drug-name substrings that belong to that family. Matching is
# case-insensitive substring containment, so "Amoxicillin 500mg" still matches
# the "amoxicillin" entry, and "Sulfa drugs" / "Sulfonamide" both route to the
# sulfa family.
ALLERGY_FAMILIES: List[Dict[str, Any]] = [
    {
        "aliases": ["penicillin", "pcn", "amoxicillin allergy", "ampicillin allergy"],
        "drugs": ["amoxicillin", "ampicillin", "augmentin", "penicillin", "flucloxacillin",
                  "piperacillin", "amoxiclav", "co-amoxiclav"],
    },
    {
        "aliases": ["nsaid", "nsaids", "non-steroidal anti-inflammatory", "aspirin allergy",
                    "ibuprofen allergy"],
        "drugs": ["ibuprofen", "naproxen", "diclofenac", "aspirin", "aceclofenac",
                  "ketorolac", "mefenamic acid", "nimesulide", "indomethacin", "etoricoxib"],
    },
    {
        "aliases": ["sulfa", "sulfa drugs", "sulfonamide", "sulfa allergy", "bactrim allergy",
                    "sulfamethoxazole allergy"],
        "drugs": ["sulfamethoxazole", "bactrim", "cotrimoxazole", "co-trimoxazole",
                  "trimethoprim-sulfamethoxazole", "sulfasalazine", "sulfadiazine"],
    },
]


def _match_family(allergen: str) -> Dict[str, Any]:
    """Return the ALLERGY_FAMILIES entry whose alias matches the allergen, or
    an empty dict if no family is recognized. A recognized allergen alias always
    also implies membership of its own family drugs (e.g. an allergy to
    "Amoxicillin" is a penicillin-family allergy)."""
    a = (allergen or "").strip().lower()
    if not a:
        return {}
    for fam in ALLERGY_FAMILIES:
        for alias in fam["aliases"]:
            if alias in a or a in alias:
                return fam
    return {}


def check_allergy_conflicts(
    medications: List[Medication], allergies: List[str]
) -> List[Dict[str, Any]]:
    """Cross-reference prescribed medications against documented allergies.

    For each documented allergen, resolve its drug family (Penicillin / NSAID /
    Sulfa, etc.) and flag any prescribed medication that belongs to that family —
    or whose name directly contains the allergen itself. Each conflict emits one
    flag dict with the exact contract shape:

        {"type": "allergy_conflict", "severity": "CRITICAL",
         "message": "CRITICAL ALERT: Prescribed medication [Med] conflicts with
                     documented patient allergy to [Allergy]!",
         "medication": "[Med]", "allergy": "[Allergy]"}

    Matching is case-insensitive substring containment so it survives dosage
    suffixes ("Amoxicillin 500mg") and loose phrasing ("Sulfa drugs"). One flag
    is emitted per (medication, allergen) conflict, de-duplicated.
    """
    conflicts: List[Dict[str, Any]] = []
    seen = set()

    med_names = [
        (med.name, (med.name or "").strip().lower())
        for med in medications
        if med and med.name
    ]
    norm_allergies = [
        (a, (a or "").strip().lower()) for a in (allergies or []) if a and a.strip()
    ]

    for allergy_raw, allergy_lower in norm_allergies:
        family = _match_family(allergy_lower)
        family_drugs = family.get("drugs", []) if family else []
        for med_raw, med_lower in med_names:
            hit = False
            # Direct substring match: the allergen name itself appears in the
            # medication name (e.g. allergy "Penicillin" vs "Penicillin V").
            if allergy_lower and allergy_lower in med_lower:
                hit = True
            # Family match: the medication belongs to the allergen's drug family.
            if not hit:
                for drug in family_drugs:
                    if drug in med_lower:
                        hit = True
                        break
            if not hit:
                continue
            key = (med_lower, allergy_lower)
            if key in seen:
                continue
            seen.add(key)
            conflicts.append(
                {
                    "type": "allergy_conflict",
                    "severity": "CRITICAL",
                    "message": (
                        f"CRITICAL ALERT: Prescribed medication {med_raw} conflicts "
                        f"with documented patient allergy to {allergy_raw}!"
                    ),
                    "medication": med_raw,
                    "allergy": allergy_raw,
                }
            )

    return conflicts