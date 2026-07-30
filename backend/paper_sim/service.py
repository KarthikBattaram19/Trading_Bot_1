"""Singleton accessor for the in-house paper simulator."""

from __future__ import annotations

from backend.paper_sim.config import PaperSimConfig
from backend.paper_sim.engine import PaperEngine
from backend.paper_sim.market_feed import MarketQuoteFeed

_engine: PaperEngine | None = None


def get_paper_engine(
    *,
    config: PaperSimConfig | None = None,
    feed: MarketQuoteFeed | None = None,
    reset: bool = False,
) -> PaperEngine:
    """
    Return the process-wide paper engine.

    Pass ``feed`` / ``config`` only on first create or when ``reset=True``.
    """
    global _engine
    if _engine is None or reset:
        _engine = PaperEngine(config=config, feed=feed)
    return _engine
