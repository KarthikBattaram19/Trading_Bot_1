"""HTTPS RSS ingest for Market_News.txt curated India sources (Architecture §8.8).

Uses official RSS where available; Google News site-filtered RSS as a fallback
when a source blocks direct bots (Moneycontrol / Reuters / NSE). No HTML scrapers.
"""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (compatible; BhaleBulloduNewsBot/1.0; +https://github.com/KarthikBattaram19/Trading_Bot_1)"
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class FeedEndpoint:
    source_id: str
    url: str
    label: str


# Curated endpoints — ids must match curation.SOURCE_ALIASES / Market_News.txt.
_FEED_ENDPOINTS: tuple[FeedEndpoint, ...] = (
    FeedEndpoint(
        "reuters",
        "https://news.google.com/rss/search?q=site:reuters.com+(India+OR+Nifty+OR+NSE+OR+Sensex)&hl=en-IN&gl=IN&ceid=IN:en",
        "reuters(google)",
    ),
    FeedEndpoint(
        "moneycontrol",
        "https://news.google.com/rss/search?q=site:moneycontrol.com+(markets+OR+stocks+OR+Nifty)&hl=en-IN&gl=IN&ceid=IN:en",
        "moneycontrol(google)",
    ),
    FeedEndpoint(
        "economic_times",
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "economic_times",
    ),
    FeedEndpoint(
        "nse",
        "https://news.google.com/rss/search?q=site:nseindia.com+(announcement+OR+circular+OR+corporate)&hl=en-IN&gl=IN&ceid=IN:en",
        "nse(google)",
    ),
    FeedEndpoint(
        "sebi",
        "https://www.sebi.gov.in/sebirss.xml",
        "sebi",
    ),
    FeedEndpoint(
        "pulse",
        "https://pulse.zerodha.com/feed.php",
        "pulse",
    ),
    FeedEndpoint(
        "cnbc_tv18",
        "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
        "cnbc_tv18",
    ),
)


def live_ingest_enabled() -> bool:
    raw = os.getenv("MARKET_NEWS_LIVE", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def fetch_live_headlines(
    *,
    source_ids: set[str] | None = None,
    per_source: int | None = None,
    timeout_sec: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, datetime], str]:
    """
    Pull RSS for curated sources. Returns (row dicts, freshness_by_source, detail).

    ``freshness`` is the successful fetch time per source (feed health), not
    individual article ages. Row shape matches the JSON fixture schema.
    """
    limit = per_source if per_source is not None else _env_int("MARKET_NEWS_PER_SOURCE", 5, minimum=1)
    timeout = timeout_sec if timeout_sec is not None else _env_float(
        "MARKET_NEWS_HTTP_TIMEOUT_SEC", 12.0, minimum=3.0
    )
    wanted = source_ids
    endpoints = [e for e in _FEED_ENDPOINTS if wanted is None or e.source_id in wanted]
    if not endpoints:
        return [], {}, "mode=live; error=no_endpoints"

    items: list[dict[str, Any]] = []
    freshness: dict[str, datetime] = {}
    ok_labels: list[str] = []
    errors: list[str] = []

    def _one(endpoint: FeedEndpoint) -> tuple[FeedEndpoint, list[dict[str, Any]], str | None]:
        try:
            rows = _fetch_endpoint(endpoint, limit=limit, timeout=timeout)
            return endpoint, rows, None
        except Exception as exc:  # noqa: BLE001
            return endpoint, [], f"{endpoint.label}:{type(exc).__name__}"

    workers = min(6, max(1, len(endpoints)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, ep) for ep in endpoints]
        for fut in as_completed(futures):
            endpoint, rows, err = fut.result()
            if err:
                errors.append(err)
                logger.warning("Market_News feed failed %s: %s", endpoint.label, err)
                continue
            if not rows:
                errors.append(f"{endpoint.label}:empty")
                continue
            now = datetime.now(timezone.utc)
            freshness[endpoint.source_id] = now
            items.extend(rows)
            ok_labels.append(endpoint.label)

    # De-dupe by normalized title; keep first seen.
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        title = str(item.get("title") or "")
        key = re.sub(r"\W+", " ", title.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    detail_parts = [
        "mode=live",
        f"sources={','.join(ok_labels) if ok_labels else '-'}",
        f"count={len(deduped)}",
    ]
    if errors:
        detail_parts.append(f"errors={','.join(errors[:4])}")
    return deduped, freshness, "; ".join(detail_parts)


def _fetch_endpoint(endpoint: FeedEndpoint, *, limit: int, timeout: float) -> list[dict[str, Any]]:
    headers = {
        "User-Agent": _UA,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(endpoint.url)
        response.raise_for_status()
        payload = response.content

    return _parse_rss_items(payload, source_id=endpoint.source_id, limit=limit)


def _parse_rss_items(payload: bytes, *, source_id: str, limit: int) -> list[dict[str, Any]]:
    from backend.services.market_news.curation import SOURCE_DISPLAY

    root = ET.fromstring(payload)
    channel_items = root.findall("./channel/item")
    if not channel_items:
        channel_items = root.findall(".//item")

    display = SOURCE_DISPLAY.get(source_id, source_id)
    out: list[dict[str, Any]] = []
    for node in channel_items:
        title = _clean_text(node.findtext("title") or "")
        if not title:
            continue
        title = _strip_google_source_suffix(title, source_id)
        summary = _clean_text(node.findtext("description") or "") or title
        pub_raw = (
            node.findtext("pubDate")
            or node.findtext("{http://purl.org/dc/elements/1.1/}date")
            or ""
        )
        published = parse_pubdate(pub_raw) or datetime.now(timezone.utc)
        out.append(
            {
                "title": title,
                "summary": summary[:500],
                "source": display,
                "time_published": published.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S"),
                "tickers_hint": [],
            }
        )
        if len(out) >= limit:
            break
    return out


def parse_pubdate(raw: str) -> datetime | None:
    """Parse common RSS / SEBI pubDate strings to UTC."""
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass

    # SEBI: "30 Jul, 2026 +0530"
    match = re.match(
        r"^(?P<d>\d{1,2})\s+(?P<mon>[A-Za-z]{3}),?\s+(?P<y>\d{4})\s+(?P<tz>[+-]\d{4})$",
        text,
    )
    if match:
        rebuilt = (
            f"{match.group('d')} {match.group('mon')} {match.group('y')} "
            f"00:00:00 {match.group('tz')}"
        )
        try:
            dt = datetime.strptime(rebuilt, "%d %b %Y %H:%M:%S %z")
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass

    compact = re.match(r"^(\d{8})T(\d{6})$", text)
    if compact:
        try:
            dt = datetime.strptime(text, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _strip_google_source_suffix(title: str, source_id: str) -> str:
    """Google News titles often end with ' - Moneycontrol.com'."""
    suffixes = {
        "moneycontrol": (" - Moneycontrol.com", " - Moneycontrol"),
        "reuters": (" - Reuters", " - reuters.com"),
        "nse": (" - NSE India", " - nseindia.com", " - National Stock Exchange of India"),
        "economic_times": (" - The Economic Times", " - Economic Times"),
        "sebi": (" - SEBI", " - sebi.gov.in"),
        "pulse": (" - Pulse by Zerodha", " - Zerodha"),
        "cnbc_tv18": (" - CNBC TV18", " - CNBCTV18"),
    }
    cleaned = title
    for suffix in suffixes.get(source_id, ()):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].rstrip(" .")
            break
    else:
        # Generic " - Publisher" tail
        if " - " in cleaned:
            head, _, tail = cleaned.rpartition(" - ")
            if 0 < len(tail) <= 40 and not tail.endswith("..."):
                cleaned = head.rstrip(" .")
    return cleaned


def _clean_text(value: str) -> str:
    text = unescape(_HTML_TAG_RE.sub(" ", value or ""))
    return _WS_RE.sub(" ", text).strip()


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


def feed_registry() -> list[dict[str, Any]]:
    """Test / ops helper — list configured HTTPS endpoints."""
    return [
        {"source_id": e.source_id, "url": e.url, "label": e.label}
        for e in _FEED_ENDPOINTS
    ]
