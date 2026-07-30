"""Market_News sentiment pipeline stub (Architecture §8.8).

Live ingest from Market_News.txt lands in Phase 1; Phase 0 keeps schema + mock.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.models.recommendations import (
    FeedHealth,
    FeedSource,
    FeedSourceStatus,
    MarketNewsSummary,
    NewsItem,
)


def market_news_feed_status() -> FeedSource:
    """Report news-service freshness for UI / recommendation packets."""
    now = datetime.now(timezone.utc)
    return FeedSource(
        source_id="market_news",
        source_name="Market_News (India curation)",
        status=FeedSourceStatus.stub,
        capabilities=["news_sentiment", "event_flags"],
        last_fetch_at=now,
        health=FeedHealth.stale,
        detail="Curated per Market_News.txt — live ingest pending (Architecture §8.8)",
    )


def mock_market_news() -> MarketNewsSummary:
    """Fallback until Market_News.txt ingest service is live."""
    return MarketNewsSummary(
        headline_count=6,
        dominant_sentiment="Neutral",
        earnings_mentions=2,
        macro_risk_flags=[
            "Using simulated news — wire Market_News.txt ingest for live feed"
        ],
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
