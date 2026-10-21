from pathlib import Path

import pymupdf


class PyMuPDFTextProvider:
    """Extract text from PDFs; replace with OCR for scanned drawings later."""

    supported_extensions = (".pdf",)

    def extract_pages(self, source: Path) -> list[str]:
        with pymupdf.open(source) as document:
            return [page.get_text() for page in document]


class SvgTextProvider:
    """Read text from SVG sample drawings without requiring an OCR service."""

    supported_extensions = (".svg",)

    def extract_pages(self, source: Path) -> list[str]:
        return [source.read_text(encoding="utf-8")]