"""Feed health for ICICI Direct marks + Market_News (no MCP registry)."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.models.recommendations import FeedHealth, FeedSource, FeedSourceStatus
from backend.services.market_news import market_news_feed_status


def _icici_direct_feed_status() -> FeedSource:
    """Reflect ICICI Direct Breeze session / credential readiness for marks."""
    now = datetime.now(timezone.utc)
    try:
        from backend.integrations.icici_direct.session_manager import get_session_manager

        session = get_session_manager()
        health = session.health()
        if health.get("authenticated"):
            return FeedSource(
                source_id="icici_direct",
                source_name="ICICI Direct Breeze",
                status=FeedSourceStatus.active,
                capabilities=["quotes", "ltp", "historical", "option_chain"],
                last_fetch_at=now,
                health=FeedHealth.fresh,
                detail="ICICI Direct session active — LTP/quotes via Breeze API",
            )
        if health.get("credentials_ready"):
            return FeedSource(
                source_id="icici_direct",
                source_name="ICICI Direct Breeze",
                status=FeedSourceStatus.active,
                capabilities=["quotes", "ltp", "historical", "option_chain"],
                last_fetch_at=None,
                health=FeedHealth.stale,
                detail="Credentials present — call POST /api/v1/config/integrations/broker/test",
            )
        return FeedSource(
            source_id="icici_direct",
            source_name="ICICI Direct Breeze",
            status=FeedSourceStatus.unavailable,
            capabilities=["quotes", "ltp", "historical", "option_chain"],
            health=FeedHealth.error,
            detail="Set ICICI_DIRECT_* env secrets to enable broker feed",
        )
    except Exception as exc:  # noqa: BLE001
        return FeedSource(
            source_id="icici_direct",
            source_name="ICICI Direct Breeze",
            status=FeedSourceStatus.unavailable,
            capabilities=["quotes", "ltp", "historical", "option_chain"],
            health=FeedHealth.error,
            detail=f"ICICI Direct feed error: {exc}",
        )


def get_feed_sources() -> list[FeedSource]:
    """Return ICICI Direct + Market_News feed health (Architecture §8.9.3)."""
    return [_icici_direct_feed_status(), market_news_feed_status()]
