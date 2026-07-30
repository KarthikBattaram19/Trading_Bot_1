"""Ingest curated India headlines for Market_News pipeline.

Default path: bundled fixture (offline / CI). Ops can drop a JSON file via
``MARKET_NEWS_HEADLINES_PATH`` — sources must still map to Market_News.txt.
No hard-coded vendor HTML scrapers (Architecture §8.8.3 non-goal).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.market_news.curation import (
    SOURCE_DISPLAY,
    CurationContract,
    normalize_source_id,
)

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_headlines.json"


@dataclass
class RawHeadline:
    title: str
    summary: str
    source: str
    source_id: str
    time_published: str
    tickers_hint: list[str] = field(default_factory=list)


def resolve_headlines_path(explicit: Path | str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.getenv("MARKET_NEWS_HEADLINES_PATH", "").strip()
    if env:
        return Path(env)
    return _FIXTURE_PATH


def load_raw_headlines(
    contract: CurationContract,
    *,
    path: Path | str | None = None,
    workflow_window: str | None = None,
) -> tuple[list[RawHeadline], dict[str, datetime], str]:
    """
    Load headlines and stamp per-source freshness.

    When ``workflow_window`` is set, prefer window sources first, then fill from
    bot_priority (edge case S-09: wrong-window sources still allowed but ranked lower).
    """
    headlines_path = resolve_headlines_path(path)
    rows = _read_json_rows(headlines_path)
    now = datetime.now(timezone.utc)
    freshness: dict[str, datetime] = {}
    items: list[RawHeadline] = []

    for row in rows:
        source_raw = str(row.get("source") or "unknown")
        source_id = normalize_source_id(source_raw)
        # Prefer display name from contract aliases when possible
        display = SOURCE_DISPLAY.get(source_id, source_raw)
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        hint = row.get("tickers_hint") or row.get("tickers") or []
        if not isinstance(hint, list):
            hint = []
        items.append(
            RawHeadline(
                title=title,
                summary=str(row.get("summary") or title).strip(),
                source=display,
                source_id=source_id,
                time_published=str(row.get("time_published") or now.strftime("%Y%m%dT%H%M%S")),
                tickers_hint=[str(x).upper() for x in hint],
            )
        )
        freshness[source_id] = now

    ranked = _rank_for_window(items, contract, workflow_window)
    detail = (
        f"headlines_path={headlines_path.name}; count={len(ranked)}; "
        f"curation_loaded={contract.loaded}"
    )
    return ranked, freshness, detail


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _rank_for_window(
    items: list[RawHeadline],
    contract: CurationContract,
    workflow_window: str | None,
) -> list[RawHeadline]:
    window_sources = set(contract.sources_for_window(workflow_window or ""))
    priority = {sid: idx for idx, sid in enumerate(contract.bot_priority)}

    def sort_key(item: RawHeadline) -> tuple[int, int, str]:
        in_window = 0 if item.source_id in window_sources else 1
        pri = priority.get(item.source_id, 100)
        return (in_window, pri, item.time_published)

    return sorted(items, key=sort_key)
