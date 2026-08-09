"""Deterministic medication schedule parser.

Turns a medication's ``frequency`` + ``duration`` (the normalized values Agent 1
extracts from a discharge summary) into concrete reminder times + a bounded
iCal RRULE — without any wall-clock or random dependence, so tests are stable.

The parser is intentionally pure: ``today`` is injected by the caller (never
``date.today()`` inside) and only the parsed frequency/duration drive the result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# Default time-of-day tables (24h "HH:MM")
# ---------------------------------------------------------------------------
COUNT_TIMES: dict[int, list[str]] = {
    1: ["09:00"],
    2: ["09:00", "21:00"],
    3: ["08:00", "14:00", "20:00"],
    4: ["08:00", "12:00", "16:00", "20:00"],
}

MEAL_TIMES = {
    "before_meals": ["08:00", "12:00", "18:00"],  # AC — before meals
    "after_meals": ["09:00", "13:00", "19:00"],   # PC — after meals
}

TIME_OF_DAY = {
    "morning": "09:00",
    "afternoon": "14:00",
    "evening": "20:00",
    "night": "22:00",
    "bedtime": "22:00",
}

# Default fallback duration (days) when none is stated or it is ambiguous.
_DEFAULT_DURATION_DAYS = 7


@dataclass
class ScheduleTime:
    """One reminder time-of-day with a human label."""

    time: str  # "HH:MM"
    label: str


@dataclass
class ScheduleResult:
    """The fully parsed schedule for one medication."""

    times: list[ScheduleTime]
    recurring: bool
    prn: bool
    one_time: bool
    needs_review: bool
    duration_days: int
    rrule: str | None
    frequency_normalized: str
    start_date: date
    schedule: list[str] = field(default_factory=list)


def _label_for(time_str: str) -> str:
    hour = int(time_str.split(":")[0])
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 21:
        return "evening"
    return "night"


def _dedup_preserve(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def normalize_frequency(frequency: str | None) -> str:
    """Lowercase, strip sigils/punctuation to a canonical token string.

    Used both internally and as the canonical form fed into the schedule hash.
    """
    if not frequency:
        return ""
    value = frequency.lower().strip()
    # Collapse the common Latin sigils into their plain-English equivalents so
    # "OD" and "once daily" hash identically.
    replacements = {
        "q.d.": "once daily",
        "qd": "once daily",
        "od": "once daily",
        "b.d.": "twice daily",
        "bd": "twice daily",
        "bid": "twice daily",
        "t.d.": "three times daily",
        "tds": "three times daily",
        "tid": "three times daily",
        "q.i.d.": "four times daily",
        "qid": "four times daily",
        "qds": "four times daily",
        "qhs": "bedtime",
        "hs": "bedtime",
        "a.c.": "before meals",
        "ac": "before meals",
        "p.c.": "after meals",
        "pc": "after meals",
        "prn": "as needed",
        "stat": "immediately",
    }
    # Replace whole-word tokens only so "pc" inside another word is untouched.
    for sigil, plain in replacements.items():
        value = re.sub(r"\b" + re.escape(sigil) + r"\b", plain, value)
    # Collapse whitespace + strip the dot-run form leftovers.
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _detect_count(text: str) -> int | None:
    """Detect a daily dose count (1–4) from a normalized frequency string."""
    if re.search(r"\b(twice|2x|2 time|two time)\b", text):
        return 2
    if re.search(r"\b(three times|thrice|3x|3 time)\b", text):
        return 3
    if re.search(r"\b(four times|4x|4 time)\b", text):
        return 4
    if re.search(r"\b(once|1x|1 time|one time)\b", text):
        return 1
    # "daily" with no other count qualifier = once daily.
    if "daily" in text and not re.search(r"\btimes\b", text):
        return 1
    return None


def parse_frequency(frequency: str | None) -> tuple[list[str], bool, bool, bool, bool]:
    """Return (times, prn, one_time, recurring, needs_review) for a frequency.

    ``times`` is a list of "HH:MM" strings (empty for PRN). ``needs_review`` is
    True when no recognizable instruction was found.
    """
    normalized = normalize_frequency(frequency)
    if not normalized:
        # Nothing to go on — default to a single morning reminder flagged review.
        return (["09:00"], False, False, True, True)

    if "as needed" in normalized:
        return ([], True, False, False, False)
    if "immediately" in normalized:
        return (["09:00"], False, True, False, False)

    needs_review = False
    times: list[str] = []

    count = _detect_count(normalized)
    if count is not None:
        times = list(COUNT_TIMES[count])
    elif "bedtime" in normalized:
        times = ["22:00"]
    elif "before meals" in normalized:
        times = list(MEAL_TIMES["before_meals"])
    elif "after meals" in normalized:
        times = list(MEAL_TIMES["after_meals"])
    else:
        # Time-of-day fragments (morning/afternoon/evening/night).
        for word, t in TIME_OF_DAY.items():
            if word in normalized:
                times.append(t)
        if not times:
            needs_review = True
            times = ["09:00"]

    times = _dedup_preserve(times)
    recurring = bool(times)
    return (times, False, False, recurring, needs_review)


def parse_duration(duration: str | None) -> tuple[int, bool]:
    """Return (duration_days, needs_review).

    Honours explicit days/weeks; converts months to 30-day units with a review
    flag (month→day is approximate). Missing or unparseable durations fall back
    to a short, safe 7-day window with a review flag — we never invent a long
    duration.
    """
    if not duration:
        return (_DEFAULT_DURATION_DAYS, True)
    text = duration.lower().strip()

    m = re.search(r"(\d+)\s*day", text)
    if m:
        return (max(1, int(m.group(1))), False)
    m = re.search(r"(\d+)\s*week", text)
    if m:
        return (max(1, int(m.group(1)) * 7), False)
    m = re.search(r"(\d+)\s*month", text)
    if m:
        # A month ≈ 30 days; mark for review since the conversion is approximate.
        return (max(1, int(m.group(1)) * 30), True)
    # Bare integer or anything else → treat as days but flag for review.
    m = re.search(r"(\d+)", text)
    if m:
        return (max(1, int(m.group(1))), True)
    return (_DEFAULT_DURATION_DAYS, True)


def parse_schedule(medication: Any, *, today: date) -> ScheduleResult:
    """Parse one medication dict into a complete, deterministic ScheduleResult.

    ``medication`` is a mapping (or pydantic model) exposing ``frequency`` and
    ``duration``; ``today`` is injected so no wall-clock dependence exists.
    """
    freq = _get(medication, "frequency")
    duration = _get(medication, "duration")

    times_str, prn, one_time, recurring, freq_review = parse_frequency(freq)
    duration_days, dur_review = parse_duration(duration)

    # PRN and one-time (STAT) reminders are never recurring and never get a RRULE.
    if prn or one_time:
        recurring = False
        # Duration is irrelevant for non-recurring reminders, so a missing
        # duration must not flag PRN/STAT for review.
        needs_review = freq_review
    else:
        needs_review = freq_review or dur_review

    times = [ScheduleTime(time=t, label=_label_for(t)) for t in times_str]

    rrule: str | None = None
    if recurring:
        rrule = f"FREQ=DAILY;COUNT={duration_days}"

    return ScheduleResult(
        times=times,
        recurring=recurring,
        prn=prn,
        one_time=one_time,
        needs_review=needs_review,
        duration_days=duration_days,
        rrule=rrule,
        frequency_normalized=normalize_frequency(freq),
        start_date=today,
        schedule=times_str,
    )


def _get(obj: Any, key: str) -> str | None:
    """Read a string field from a dict or pydantic model, tolerating either."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        value = obj.get(key)
    else:
        value = getattr(obj, key, None)
    if value is None:
        return None
    return str(value)