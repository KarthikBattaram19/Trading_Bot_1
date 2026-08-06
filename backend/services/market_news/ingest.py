"""Ingest curated India headlines for Market_News pipeline.

Priority (Architecture §8.8 — HTTPS / file, no HTML scrapers):
1. Explicit ``path`` / ``MARKET_NEWS_HEADLINES_PATH`` JSON file (ops override)
2. Live HTTPS RSS from Market_News.txt sources (``MARKET_NEWS_LIVE=1``, default)
3. Bundled fixture fallback when live yields nothing (offline / CI)

Sources must still map to Market_News.txt.
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


def resolve_headlines_path(explicit: Path | str | None = None) -> Path | None:
    """Return an explicit JSON path when ops overrides live ingest; else None."""
    if explicit:
        return Path(explicit)
    env = os.getenv("MARKET_NEWS_HEADLINES_PATH", "").strip()
    if env:
        return Path(env)
    return None


def load_raw_headlines(
    contract: CurationContract,
    *,
    path: Path | str | None = None,
    workflow_window: str | None = None,
) -> tuple[list[RawHeadline], dict[str, datetime], str]:
    """
    Load headlines and stamp per-source freshness.

    Ranking is always by trust tier (``bot_priority`` order), then recency —
    ``workflow_window`` no longer biases source selection or ranking; all
    curated sources are in play regardless of time of day (Market_News.txt).
    The parameter is retained only for call-site compatibility.
    """
    override = resolve_headlines_path(path)
    if override is not None:
        items, freshness, detail = _load_from_json_file(override, contract)
        ranked = _rank_for_window(items, contract, workflow_window)
        return ranked, freshness, f"{detail}; curation_loaded={contract.loaded}"

    live_items: list[RawHeadline] = []
    live_freshness: dict[str, datetime] = {}
    live_detail = "mode=live; skipped=disabled"
    if _live_enabled():
        live_items, live_freshness, live_detail = _load_from_live(contract)
        if live_items:
            ranked = _rank_for_window(live_items, contract, workflow_window)
            return (
                ranked,
                live_freshness,
                f"{live_detail}; curation_loaded={contract.loaded}",
            )

    # Offline / CI / live-empty fallback
    items, freshness, detail = _load_from_json_file(_FIXTURE_PATH, contract)
    ranked = _rank_for_window(items, contract, workflow_window)
    fallback = (
        f"mode=fixture_fallback; headlines_path={_FIXTURE_PATH.name}; "
        f"count={len(ranked)}; live={live_detail}; curation_loaded={contract.loaded}"
    )
    if not live_items and _live_enabled():
        return ranked, freshness, fallback
    return (
        ranked,
        freshness,
        f"mode=fixture; headlines_path={_FIXTURE_PATH.name}; "
        f"count={len(ranked)}; curation_loaded={contract.loaded}",
    )


def _live_enabled() -> bool:
    from backend.services.market_news.feeds import live_ingest_enabled

    return live_ingest_enabled()


def _load_from_live(
    contract: CurationContract,
) -> tuple[list[RawHeadline], dict[str, datetime], str]:
    from backend.services.market_news.feeds import fetch_live_headlines

    wanted = set(contract.bot_priority) | set(contract.monitors)
    for window_sources in contract.windows.values():
        wanted.update(window_sources)
    rows, freshness, detail = fetch_live_headlines(source_ids=wanted or None)
    return _rows_to_headlines(rows), freshness, detail


def _load_from_json_file(
    headlines_path: Path,
    contract: CurationContract,
) -> tuple[list[RawHeadline], dict[str, datetime], str]:
    rows = _read_json_rows(headlines_path)
    items, freshness = _rows_to_headlines_with_freshness(rows)
    detail = f"headlines_path={headlines_path.name}; count={len(items)}"
    _ = contract  # contract reserved for future source allow-lists
    return items, freshness, detail


def _rows_to_headlines(rows: list[dict[str, Any]]) -> list[RawHeadline]:
    items, _ = _rows_to_headlines_with_freshness(rows)
    return items


def _rows_to_headlines_with_freshness(
    rows: list[dict[str, Any]],
) -> tuple[list[RawHeadline], dict[str, datetime]]:
    now = datetime.now(timezone.utc)
    freshness: dict[str, datetime] = {}
    items: list[RawHeadline] = []

    for row in rows:
        source_raw = str(row.get("source") or "unknown")
        source_id = normalize_source_id(source_raw)
        display = SOURCE_DISPLAY.get(source_id, source_raw)
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        hint = row.get("tickers_hint") or row.get("tickers") or []
        if not isinstance(hint, list):
            hint = []
        time_published = str(row.get("time_published") or now.strftime("%Y%m%dT%H%M%S"))
        items.append(
            RawHeadline(
                title=title,
                summary=str(row.get("summary") or title).strip(),
                source=display,
                source_id=source_id,
                time_published=time_published,
                tickers_hint=[str(x).upper() for x in hint],
            )
        )
        # File/fixture freshness = load time so refresh cycles update last_fetch_at.
        freshness[source_id] = now

    return items, freshness


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
    """Rank by trust tier (``bot_priority`` order), then recency.

    ``workflow_window`` is accepted for call-site compatibility but no
    longer biases ranking — all curated sources are always in play
    regardless of time of day (Market_News.txt).
    """
    _ = workflow_window
    priority = {sid: idx for idx, sid in enumerate(contract.bot_priority)}

    def sort_key(item: RawHeadline) -> tuple[int, str]:
        pri = priority.get(item.source_id, 100)
        return (pri, item.time_published)

    return sorted(items, key=sort_key)
