"""PDF page extraction (architecture.md §7.2 Stage 2)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class PageText:
    page: int  # 1-indexed
    text: str


def extract_pages(pdf_path: Path) -> list[PageText]:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"RAG PDF not found: {pdf_path}")

    pages: list[PageText] = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            text = page.get_text("text") or ""
            pages.append(PageText(page=i + 1, text=text))
    return pages
