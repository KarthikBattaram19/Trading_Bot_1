"""Bot status, feed health, and global index marks."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.integrations.registry import (
    get_default_broker_provider,
    get_execution_mode,
    paper_stack_guard_status,
    place_order_enabled,
)
from backend.models.recommendations import FeedSource
from backend.services.feed_health import get_feed_sources
from backend.services.supervision_mode import get_supervision_mode
from backend.services.trade_executor import get_active_trade_id, is_one_trade_locked

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["bot"])


@router.get("/bot/status")
async def bot_status():
    supervision = get_supervision_mode()
    guard = paper_stack_guard_status()
    metrics: dict = {
        "daily_pnl": 0.0,
        "win_rate": 0.0,
        "drawdown_pct": 0.0,
        "portfolio_greeks": {
            "total_delta": 0.0,
            "total_gamma": 0.0,
            "total_theta": 0.0,
            "total_vega": 0.0,
        },
        "circuit_breakers_active": [],
    }
    try:
        from backend.services.risk_snapshot import bot_metrics_from_risk

        metrics.update(bot_metrics_from_risk())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Bot status risk metrics unavailable: %s", exc)

    return {
        "execution_mode": get_execution_mode().value,
        "requested_execution_mode": guard["requested_execution_mode"],
        "deploy_stack": guard["deploy_stack"],
        "live_blocked": guard["live_blocked"],
        "supervision_mode": supervision,
        "default_broker": get_default_broker_provider(),
        "autonomy": "supervised" if supervision == "supervised" else supervision,
        "scheduler_mode": "active",
        "regime": "mixed_vol",
        "daily_pnl": metrics["daily_pnl"],
        "win_rate": metrics["win_rate"],
        "drawdown_pct": metrics["drawdown_pct"],
        "portfolio_greeks": metrics["portfolio_greeks"],
        "circuit_breakers_active": metrics["circuit_breakers_active"],
        "pending_count": 0,
        "one_trade_locked": is_one_trade_locked(),
        "active_trade_id": get_active_trade_id(),
        "place_order_enabled": place_order_enabled(),
        "api_health": "ok",
        "phase": "1",
    }


async def _ensure_ws_for_feed_ui() -> None:
    """Best-effort A2 connect when ICICI credentials/session can open livestream."""
    try:
        from backend.integrations.icici_direct.market_data import get_market_data_adapter
        from backend.integrations.icici_direct.session_manager import get_session_manager

        health = get_session_manager().health()
        if health.get("authenticated") or health.get("credentials_ready"):
            await get_market_data_adapter().ensure_ws_connected()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Feed UI WS ensure skipped: %s", exc)


@router.get("/feeds/status")
async def list_feed_status() -> list[FeedSource]:
    """ICICI Direct + Market_News feed health (MCP registry retired — plan §1 / 0.3)."""
    await _ensure_ws_for_feed_ui()
    return get_feed_sources()


@router.get("/market/indices")
async def market_indices():
    """NIFTY 50 + India VIX marks for the situational bar (ICICI Direct quotes)."""
    from backend.integrations.icici_direct.market_data import get_market_data_adapter

    await _ensure_ws_for_feed_ui()
    marks = await get_market_data_adapter().get_global_indices()
    return {
        "as_of": marks[0].ts.isoformat() if marks and marks[0].ts else None,
        "indices": [m.model_dump(mode="json") for m in marks],
    }
