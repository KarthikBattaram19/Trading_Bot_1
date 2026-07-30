"""Market_News sentiment pipeline (Architecture §8.8).

Curation contract: project-root ``Market_News.txt``.
Consumers: recommendations ``market_news``, paper-sim ``GET /news``.
"""

from __future__ import annotations

from backend.services.market_news.service import (
    get_market_news,
    market_news_feed_status,
    mock_market_news,
    paper_news_packet,
    refresh_market_news,
    reset_market_news_cache,
)

__all__ = [
    "get_market_news",
    "market_news_feed_status",
    "mock_market_news",
    "paper_news_packet",
    "refresh_market_news",
    "reset_market_news_cache",
]
