from collections.abc import Sequence
from pathlib import Path
from typing import Protocol


class DocumentTextProvider(Protocol):
    """Boundary for replacing text extraction with OCR or a vision model."""

    supported_extensions: Sequence[str]

    def extract_pages(self, source: Path) -> list[str]:
        """Return one text value per source page."""