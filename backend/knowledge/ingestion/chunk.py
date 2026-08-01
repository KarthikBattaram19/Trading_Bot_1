"""Semantic-ish chunking with chapter awareness (architecture.md §7.2 Stages 4–5)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.knowledge.ingestion.extract import PageText
from backend.knowledge.ingestion.normalize import normalize_page_text

# Printed chapter starts for Volatility Trading.pdf (from Summary page).
_VOL_CHAPTERS: list[tuple[int, str]] = [
    (3, "Introduction"),
    (10, "Basics of Derivatives"),
    (13, "Stock Option Properties"),
    (15, "Black-Scholes Model"),
    (17, "Option Greeks"),
    (33, "Forecasting Volatility"),
    (43, "Volatility Trading Rules"),
    (46, "Volatility Trading in Practice"),
    (54, "Conclusion"),
]

_SECTION_BULLET = re.compile(r"(?m)^\s*[•·\-]\s+(.+)$")
_HEADING_LINE = re.compile(
    r"(?m)^(Introduction|Basics of Derivatives|Stock Option Properties|"
    r"Black-Scholes Model|Option Greeks|Forecasting Volatility|"
    r"Volatility Trading Rules|Volatility Trading in Practice|Conclusion|"
    r"Delta|Gamma|Vega|Theta|Delta Hedge|"
    r"Buying Options vs Selling Options|"
    r"Choosing the Options to Trade Volatility|"
    r"Entering the Volatility Trade|Exiting the Trade)\s*$"
)

# ~400–800 tokens ≈ 1600–3200 chars; use ~2200 with ~15% overlap.
_TARGET_CHARS = 2200
_OVERLAP_CHARS = 330


@dataclass
class RawChunk:
    text: str
    page: int
    chapter: str
    section: str
    heading_path: str
    has_equation: bool = False
    concepts: list[str] = field(default_factory=list)


def _chapter_for_page(page: int, chapters: list[tuple[int, str]]) -> str:
    current = chapters[0][1] if chapters else "Unknown"
    for start, title in chapters:
        if page >= start:
            current = title
        else:
            break
    return current


def _detect_section(text: str, chapter: str) -> str:
    bullets = _SECTION_BULLET.findall(text)
    if bullets:
        return bullets[0].strip()[:120]
    headings = _HEADING_LINE.findall(text)
    if headings:
        return headings[-1].strip()
    # First non-empty line as soft section hint
    for line in text.splitlines():
        line = line.strip()
        if len(line) > 3 and not line.isdigit():
            return line[:120]
    return chapter


def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _has_equation(text: str) -> bool:
    return bool(
        re.search(r"[∂νΘΓΔσ]|\\\\frac|Black-Scholes|GARCH\(1,1\)", text)
    )


def _concept_tags(text: str) -> list[str]:
    lower = text.lower()
    tags: list[str] = []
    mapping = {
        "Delta": ("delta",),
        "Gamma": ("gamma",),
        "Vega": ("vega", "implied volatility"),
        "Theta": ("theta", "time decay"),
        "IV": ("implied volatility",),
        "HV": ("historical volatility", "realized volatility"),
        "GARCH": ("garch",),
        "Black-Scholes": ("black-scholes", "black scholes"),
    }
    for label, needles in mapping.items():
        if any(n in lower for n in needles):
            tags.append(label)
    return tags


def chunk_pages(
    pages: list[PageText],
    *,
    document_title: str,
    chapters: list[tuple[int, str]] | None = None,
) -> list[RawChunk]:
    chapter_map = chapters or _VOL_CHAPTERS
    normalized: list[tuple[int, str]] = [
        (p.page, normalize_page_text(p.text)) for p in pages if p.text.strip()
    ]
    # Drop near-empty front-matter watermark pages
    normalized = [(pg, tx) for pg, tx in normalized if len(tx) > 40]

    chunks: list[RawChunk] = []
    buffer = ""
    buf_page = normalized[0][0] if normalized else 1
    buf_chapter = _chapter_for_page(buf_page, chapter_map)

    def flush(force: bool = False) -> None:
        nonlocal buffer, buf_page, buf_chapter
        if not buffer.strip():
            return
        if not force and len(buffer) < _TARGET_CHARS * 0.4:
            return
        section = _detect_section(buffer, buf_chapter)
        heading = f"{document_title} > {buf_chapter} > {section}"
        chunks.append(
            RawChunk(
                text=buffer.strip(),
                page=buf_page,
                chapter=buf_chapter,
                section=section,
                heading_path=heading,
                has_equation=_has_equation(buffer),
                concepts=_concept_tags(buffer),
            )
        )
        # overlap
        if len(buffer) > _OVERLAP_CHARS:
            buffer = buffer[-_OVERLAP_CHARS:]
        else:
            buffer = ""

    for page_no, text in normalized:
        chapter = _chapter_for_page(page_no, chapter_map)
        if chapter != buf_chapter and buffer.strip():
            flush(force=True)
            buffer = ""
            buf_chapter = chapter
            buf_page = page_no

        for para in _split_paragraphs(text):
            candidate = f"{buffer}\n\n{para}".strip() if buffer else para
            if len(candidate) >= _TARGET_CHARS and buffer:
                flush(force=True)
                candidate = f"{buffer}\n\n{para}".strip() if buffer else para
            if not buffer:
                buf_page = page_no
                buf_chapter = chapter
            buffer = candidate

    flush(force=True)
    return chunks
