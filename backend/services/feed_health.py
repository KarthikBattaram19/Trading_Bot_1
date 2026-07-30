"""Feed health for ICICI Direct marks + Market_News (no MCP registry)."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.models.recommendations import FeedHealth, FeedSource, FeedSourceStatus
from backend.services.market_news import market_news_feed_status

_ICICI_CAPS = ["quotes", "ltp", "historical", "option_chain", "ws_streaming"]


def _icici_direct_feed_status() -> FeedSource:
    """Reflect ICICI Direct Breeze session / WS freshness for marks (§8.9)."""
    now = datetime.now(timezone.utc)
    try:
        from backend.integrations.icici_direct.market_data import get_market_data_adapter
        from backend.integrations.icici_direct.session_manager import get_session_manager

        session = get_session_manager()
        health = session.health()
        market = get_market_data_adapter()
        ws = market.ws_status()
        freshest = ws.get("freshest_tick_age_sec")
        ws_connected = bool(ws.get("connected"))

        if health.get("authenticated"):
            if ws_connected and freshest is not None and float(freshest) < 1.0:
                detail = (
                    f"ICICI Direct WS Streaming 2.0 active — "
                    f"freshest tick age {float(freshest):.3f}s (sub-second)"
                )
                feed_health = FeedHealth.fresh
                last_fetch = now
            elif ws_connected:
                detail = (
                    "ICICI Direct WS connected — awaiting ticks "
                    f"(subscriptions={ws.get('subscription_count', 0)})"
                )
                feed_health = FeedHealth.fresh
                last_fetch = now
            else:
                detail = (
                    "ICICI Direct session active — REST LTP/quotes; "
                    "WS Streaming 2.0 not connected"
                )
                feed_health = FeedHealth.fresh
                last_fetch = now
            return FeedSource(
                source_id="icici_direct",
                source_name="ICICI Direct Breeze",
                status=FeedSourceStatus.active,
                capabilities=list(_ICICI_CAPS),
                last_fetch_at=last_fetch,
                health=feed_health,
                detail=detail,
            )
        if health.get("credentials_ready"):
            return FeedSource(
                source_id="icici_direct",
                source_name="ICICI Direct Breeze",
                status=FeedSourceStatus.active,
                capabilities=list(_ICICI_CAPS),
                last_fetch_at=None,
                health=FeedHealth.stale,
                detail="Credentials present — call POST /api/v1/config/integrations/broker/test",
            )
        return FeedSource(
            source_id="icici_direct",
            source_name="ICICI Direct Breeze",
            status=FeedSourceStatus.unavailable,
            capabilities=list(_ICICI_CAPS),
            health=FeedHealth.error,
            detail="Set ICICI_DIRECT_* env secrets to enable broker feed",
        )
    except Exception as exc:  # noqa: BLE001
        return FeedSource(
            source_id="icici_direct",
            source_name="ICICI Direct Breeze",
            status=FeedSourceStatus.unavailable,
            capabilities=list(_ICICI_CAPS),
            health=FeedHealth.error,
            detail=f"ICICI Direct feed error: {exc}",
        )


def get_feed_sources() -> list[FeedSource]:
    """Return ICICI Direct + Market_News feed health (Architecture §8.9.3)."""
    return [_icici_direct_feed_status(), market_news_feed_status()]
