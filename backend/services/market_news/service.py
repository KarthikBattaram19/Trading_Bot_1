"""Market_News sentiment service — Architecture §8.8 / Trading_Parameters Part U."""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.models.recommendations import (
    FeedHealth,
    FeedSource,
    FeedSourceStatus,
    MarketNewsSummary,
    NewsItem,
)
from backend.services.market_news.classifier import (
    ClassifiedHeadline,
    aggregate_packet_flags,
    classify_headline,
)
from backend.services.market_news.curation import (
    CurationContract,
    load_curation_contract,
    workflow_window_at,
)
from backend.services.market_news.ingest import load_raw_headlines

_lock = threading.Lock()
_cache: MarketNewsSummary | None = None
_cache_at: datetime | None = None
_last_detail: str = ""
_last_contract: CurationContract | None = None


def _stale_threshold_sec() -> float:
    raw = os.getenv("MARKET_NEWS_STALE_SEC", "").strip()
    if raw:
        try:
            return max(30.0, float(raw))
        except ValueError:
            pass
    return 1800.0  # 30 minutes


def _cache_ttl_sec() -> float:
    raw = os.getenv("MARKET_NEWS_CACHE_TTL_SEC", "").strip()
    if raw:
        try:
            return max(5.0, float(raw))
        except ValueError:
            pass
    return 60.0


def reset_market_news_cache() -> None:
    """Test helper — clear in-process news cache."""
    global _cache, _cache_at, _last_detail, _last_contract
    with _lock:
        _cache = None
        _cache_at = None
        _last_detail = ""
        _last_contract = None


def mock_market_news() -> MarketNewsSummary:
    """Deterministic fallback when ingest yields no headlines."""
    return MarketNewsSummary(
        headline_count=2,
        dominant_sentiment="Neutral",
        dominant_tone="neutral",
        earnings_mentions=1,
        macro_risk_flags=[
            "Using simulated news — provide Market_News headlines JSON for live feed"
        ],
        topics=["financial_markets", "earnings"],
        symbol_tags=["NIFTY", "INFY"],
        news_not_blocking=True,
        news_event_imminent=True,
        news_post_shock=False,
        news_impact="none",
        source_freshness={},
        workflow_window=workflow_window_at(),
        interpretation=(
            "Mock news layer active. Sentiment will come from curated India sources "
            "listed in Market_News.txt (Architecture §8.8)."
        ),
        items=[
            NewsItem(
                title="NIFTY options see intraday IV flush on quiet open",
                summary="ATM weekly options printed IV 2.1σ below session mean.",
                source="Simulated Feed",
                time_published="20260705T093000",
                sentiment_label="Neutral",
                sentiment_score=0.02,
                tickers=["NIFTY"],
                topics=["financial_markets"],
                relevance_to_trade="Supports vega scalping candidate",
            ),
            NewsItem(
                title="Major IT name reports earnings tomorrow",
                summary="Implied move elevated; term structure stable at entry window.",
                source="Simulated Feed",
                time_published="20260705T080000",
                sentiment_label="Somewhat-Bullish",
                sentiment_score=0.18,
                tickers=["INFY"],
                topics=["earnings"],
                relevance_to_trade="Gamma earnings_gap_mode candidate",
            ),
        ],
    )


def refresh_market_news(
    *,
    now: datetime | None = None,
    force: bool = True,
) -> MarketNewsSummary:
    """Re-ingest + classify; updates cache. ``force`` ignored except for API clarity."""
    _ = force
    summary = _build_summary(now=now)
    global _cache, _cache_at
    with _lock:
        _cache = summary
        _cache_at = datetime.now(timezone.utc)
    return summary


def get_market_news(*, now: datetime | None = None, force_refresh: bool = False) -> MarketNewsSummary:
    """Return cached MarketNewsSummary, refreshing when stale or forced."""
    global _cache, _cache_at
    with _lock:
        if (
            not force_refresh
            and _cache is not None
            and _cache_at is not None
            and (datetime.now(timezone.utc) - _cache_at).total_seconds() < _cache_ttl_sec()
        ):
            return _cache
    return refresh_market_news(now=now, force=True)


def market_news_feed_status() -> FeedSource:
    """Report news-service freshness for UI / recommendation packets."""
    summary = get_market_news()
    now = datetime.now(timezone.utc)
    ages: list[float] = []
    for ts in summary.source_freshness.values():
        if ts is None:
            continue
        moment = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        ages.append((now - moment.astimezone(timezone.utc)).total_seconds())

    threshold = _stale_threshold_sec()
    detail_text = _last_detail or "Market_News ingest OK"
    using_fixture = "mode=fixture" in detail_text or "sample_headlines.json" in detail_text
    if not summary.source_freshness:
        health = FeedHealth.stale
        status = FeedSourceStatus.stub
        detail = _last_detail or "No source freshness — mock or empty ingest"
    elif using_fixture:
        # Bundled sample is offline fallback — never report as live-fresh.
        health = FeedHealth.stale
        status = FeedSourceStatus.active
        detail = detail_text
    elif ages and max(ages) > threshold:
        health = FeedHealth.stale
        status = FeedSourceStatus.active
        detail = f"Stale vs {threshold:.0f}s threshold; {detail_text}"
    else:
        health = FeedHealth.fresh
        status = FeedSourceStatus.active
        detail = detail_text

    last_fetch = None
    if summary.source_freshness:
        vals = [v for v in summary.source_freshness.values() if v is not None]
        if vals:
            last_fetch = max(vals)

    return FeedSource(
        source_id="market_news",
        source_name="Market_News (India curation)",
        status=status,
        capabilities=["news_sentiment", "event_flags", "workflow_windows"],
        last_fetch_at=last_fetch or now,
        health=health,
        detail=detail,
    )


def paper_news_packet(*, now: datetime | None = None, force_refresh: bool = False) -> dict[str, Any]:
    """
    Paper-sim ``GET /news`` payload (Paper_Simulator.md).

    Exposes dominant_tone, topics, symbol_tags, macro_risk_flags,
    source_freshness, news_impact plus full MarketNewsSummary fields.
    """
    summary = get_market_news(now=now, force_refresh=force_refresh)
    contract = _last_contract or load_curation_contract()
    feed = market_news_feed_status()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "curation_path": str(contract.path),
        "curation_loaded": contract.loaded,
        "bot_priority": list(contract.bot_priority),
        "window_sources": list(contract.sources_for_window(summary.workflow_window)),
        "dominant_tone": summary.dominant_tone,
        "topics": list(summary.topics),
        "symbol_tags": list(summary.symbol_tags),
        "macro_risk_flags": list(summary.macro_risk_flags),
        "source_freshness": {
            k: (v.isoformat() if v is not None else None)
            for k, v in summary.source_freshness.items()
        },
        "news_impact": summary.news_impact,
        "news_not_blocking": summary.news_not_blocking,
        "news_event_imminent": summary.news_event_imminent,
        "news_post_shock": summary.news_post_shock,
        "workflow_window": summary.workflow_window,
        "feed_health": feed.health.value,
        "feed_status": feed.status.value,
        "market_news": summary.model_dump(mode="json"),
    }


def _build_summary(*, now: datetime | None = None) -> MarketNewsSummary:
    global _last_detail, _last_contract
    moment = now or datetime.now(timezone.utc)
    contract = load_curation_contract()
    _last_contract = contract
    window = workflow_window_at(moment)
    raw_items, freshness, detail = load_raw_headlines(contract, workflow_window=window)
    _last_detail = detail

    classified: list[ClassifiedHeadline] = [
        classify_headline(
            title=r.title,
            summary=r.summary,
            source=r.source,
            source_id=r.source_id,
            time_published=r.time_published,
            tickers_hint=r.tickers_hint,
        )
        for r in raw_items
    ]

    if not classified:
        mock = mock_market_news()
        return mock.model_copy(
            update={
                "workflow_window": window,
                "source_freshness": {},
            }
        )

    flags = aggregate_packet_flags(classified)
    news_items = [
        NewsItem(
            title=c.title,
            summary=c.summary,
            source=c.source,
            time_published=c.time_published,
            sentiment_label=c.sentiment_label,
            sentiment_score=c.sentiment_score,
            tickers=c.tickers,
            topics=c.topics,
            relevance_to_trade=c.relevance_to_trade,
        )
        for c in classified
    ]

    # Mark window-mismatched sources as slightly older for S-09 awareness
    window_sources = set(contract.sources_for_window(window))
    adjusted: dict[str, datetime | None] = {}
    for source_id, ts in freshness.items():
        if window_sources and source_id not in window_sources:
            adjusted[source_id] = ts - timedelta(seconds=_stale_threshold_sec() * 0.25)
        else:
            adjusted[source_id] = ts

    return MarketNewsSummary(
        headline_count=len(news_items),
        dominant_sentiment=str(flags["dominant_sentiment"]),
        dominant_tone=str(flags["dominant_tone"]),
        earnings_mentions=int(flags["earnings_mentions"]),
        macro_risk_flags=list(flags["macro_risk_flags"]),  # type: ignore[arg-type]
        topics=list(flags["topics"]),  # type: ignore[arg-type]
        symbol_tags=list(flags["symbol_tags"]),  # type: ignore[arg-type]
        news_not_blocking=bool(flags["news_not_blocking"]),
        news_event_imminent=bool(flags["news_event_imminent"]),
        news_post_shock=bool(flags["news_post_shock"]),
        news_impact=str(flags["news_impact"]),
        source_freshness=adjusted,
        workflow_window=window,
        interpretation=str(flags["interpretation"]),
        items=news_items,
    )
