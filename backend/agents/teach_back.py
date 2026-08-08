"""Agent 3: Teach-Back Verification.

Uses OpenRouter (OpenAI-compatible API) with a free Llama 3.3 70B model to
evaluate whether a patient actually understands their discharge instructions
using the Teach-Back method. The model is forced to return structured JSON
matching the `teach_back` contract in context.md via OpenAI tool calling.
"""

from __future__ import annotations

import json
import os
from typing import List

from dotenv import load_dotenv

# Load .env so OPENROUTER_API_KEY is available even when this module is
# imported before main.py (e.g. in tests). Idempotent.
load_dotenv()

from openai import AsyncOpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import openai
from agents.compliance_guard import (
    collect_explicit_names,
    payload_as_json,
    prepare_clinical_payload,
)

# ---------------------------------------------------------------------------
# OpenRouter client (OpenAI-compatible). Key read from the environment.
# ---------------------------------------------------------------------------

client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
# Secondary fallback if the primary free model is unavailable.
FALLBACK_MODEL = "openrouter/free"

SYSTEM_PROMPT = (
    "You are a specialized discharge nurse AI. Your goal is to verify if the "
    "patient understands their discharge instructions using the Teach-Back "
    "method. Compare the patient's statement against the true extracted "
    "medical data. Rate their understanding from 0-100. If they are wrong or "
    "missing key details, provide a gentle, clear correction."
)


# ---------------------------------------------------------------------------
# Output schema (strict JSON contract from context.md)
# ---------------------------------------------------------------------------


class TeachBackResult(BaseModel):
    questions_asked: List[str]
    patient_responses: List[str]
    understanding_score: int
    corrections_given: List[str]


# OpenAI function-calling tool spec derived from the Pydantic schema.
TEACH_BACK_TOOL = {
    "type": "function",
    "function": {
        "name": "record_teach_back",
        "description": (
            "Record the updated Teach-Back verification state, including the "
            "questions asked, the patient's responses, an understanding score "
            "from 0-100, and any gentle corrections given."
        ),
        "parameters": TeachBackResult.model_json_schema(),
    },
}


# ---------------------------------------------------------------------------
# Core teach-back evaluation
# ---------------------------------------------------------------------------


async def evaluate_teach_back(
    extracted_data: dict,
    current_teach_back_state: dict,
    new_patient_response: str,
) -> dict:
    """Evaluate a patient's teach-back response against the true discharge data.

    Args:
        extracted_data: The ground-truth discharge instructions (the `extracted`
            object from context.md).
        current_teach_back_state: The existing teach-back history so far.
        new_patient_response: The patient's latest statement to evaluate.

    Returns:
        A dictionary matching the `teach_back` contract in context.md.
    """
    names = collect_explicit_names(extracted_data)
    names.extend(collect_explicit_names(current_teach_back_state))
    guarded_extracted = prepare_clinical_payload(extracted_data, names=names)
    guarded_state = prepare_clinical_payload(current_teach_back_state, names=names)
    guarded_response = prepare_clinical_payload(
        {"patient_response": new_patient_response},
        names=names,
    ).get("patient_response", new_patient_response)
    user_prompt = (
        "TRUE EXTRACTED MEDICAL DATA (ground truth):\n"
        f"{payload_as_json(guarded_extracted)}\n\n"
        "CURRENT TEACH-BACK STATE (history so far):\n"
        f"{payload_as_json(guarded_state)}\n\n"
        f"NEW PATIENT RESPONSE:\n{guarded_response}\n\n"
        "Evaluate the patient's understanding against the ground truth. Append "
        "this exchange to the existing history (do not discard previous "
        "questions/responses/corrections), assign an understanding_score from "
        "0-100, and if the patient is wrong or missing key details, add a gentle, "
        "clear correction. Then call the record_teach_back tool with the full "
        "updated state."
    )

    # Retried on 429 RateLimitError with exponential backoff (2s..10s, 3 tries).
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(openai.RateLimitError),
        reraise=True,
    )
    async def _call(model: str):
        return await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            tools=[TEACH_BACK_TOOL],
            tool_choice={"type": "function", "function": {"name": "record_teach_back"}},
        )

    # Try the primary model first; fall back to the secondary on any API error
    # (e.g. 404 if the free exp model is deprecated, or upstream 429/500).
    try:
        completion = await _call(MODEL)
    except openai.OpenAIError:
        completion = await _call(FALLBACK_MODEL)

    arguments = completion.choices[0].message.tool_calls[0].function.arguments
    return json.loads(arguments)
