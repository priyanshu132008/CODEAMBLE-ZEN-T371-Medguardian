"""Document extraction responsibilities.

This module will eventually handle extraction of structured content from uploaded
files, but it currently exposes only a minimal skeleton for architecture setup.
"""

from __future__ import annotations

from typing import Any


class DocumentExtractor:
    """Responsible for extracting raw document content for downstream processing."""

    def __init__(self) -> None:
        """Initialize the extractor."""
        # TODO: wire in AI client or processing backend.
        pass

    async def extract(self, file_path: str, content_type: str | None = None) -> Any:
        """Extract document content from a file path.

        Args:
            file_path: Path to the uploaded document.
            content_type: Optional MIME type for the source document.

        Returns:
            Placeholder result object for future integration.
        """
        # TODO: implement extraction strategy for supported file types.
        raise NotImplementedError("Extraction logic is not implemented yet.")
