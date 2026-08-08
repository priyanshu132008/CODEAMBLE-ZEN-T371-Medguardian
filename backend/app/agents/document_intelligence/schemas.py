"""Schema definitions for document intelligence data structures.

These classes define the intended shapes for extracted, parsed, and validated
content so the integration layer can evolve in a structured way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedDocument:
    """Represents raw extracted content from an uploaded document."""

    source_path: str
    content_type: str | None = None
    raw_content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    """Represents structured content derived from extracted document data."""

    source_path: str
    structured_data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Represents the outcome of validating parsed document content."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
