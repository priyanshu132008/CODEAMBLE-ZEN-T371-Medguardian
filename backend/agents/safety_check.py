"""Agent 2: Safety Cross-Check.

A purely rule-based, deterministic agent that checks a list of extracted
medications against a CSV dataset to find drug interactions and duplicate
therapies. No LLM APIs are used.
"""

from __future__ import annotations

import itertools
import os
from typing import List

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