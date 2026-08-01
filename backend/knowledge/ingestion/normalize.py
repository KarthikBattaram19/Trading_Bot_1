"""Document normalization — strip purchase watermarks / collapse whitespace."""

from __future__ import annotations

import re

_WATERMARK = re.compile(
    r"Purchased by .+?, .+?@.+?, \{custom_\d+\}\s*",
    re.IGNORECASE,
)
_PAGE_NUM_ONLY = re.compile(r"^\s*\d+\s*$", re.MULTILINE)
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_MULTI_NL = re.compile(r"\n{3,}")


def normalize_page_text(text: str) -> str:
    cleaned = _WATERMARK.sub("", text)
    cleaned = _PAGE_NUM_ONLY.sub("", cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    # Rejoin soft hyphenation at line breaks: word-\nword → wordword
    cleaned = re.sub(r"(\w)-\n(\w)", r"\1\2", cleaned)
    cleaned = _MULTI_SPACE.sub(" ", cleaned)
    cleaned = _MULTI_NL.sub("\n\n", cleaned)
    return cleaned.strip()
