"""Bot status, kill-switch placeholder, and feed health (Phase 0 shell)."""

from __future__ import annotations

import os

from fastapi import APIRouter

from backend.integrations.registry import (
    get_default_broker_provider,
    get_execution_mode,
    paper_stack_guard_status,
    place_order_enabled,
)
from backend.models.recommendations import FeedSource
from backend.services.feed_health import get_feed_sources
from backend.services.trade_executor import get_active_trade_id, is_one_trade_locked

router = APIRouter(prefix="/api/v1", tags=["bot"])

_kill_switch_armed = False
_scheduler_mode = "active"


def is_kill_switch_armed() -> bool:
    """PS-08 / Phase 1.6 automation gate."""
    return bool(_kill_switch_armed)


@router.get("/bot/status")
async def bot_status():
    supervision = os.getenv("SUPERVISION_MODE", "supervised").strip().lower()
    guard = paper_stack_guard_status()
    return {
        "execution_mode": get_execution_mode().value,
        "requested_execution_mode": guard["requested_execution_mode"],
        "deploy_stack": guard["deploy_stack"],
        "live_blocked": guard["live_blocked"],
        "supervision_mode": supervision,
        "default_broker": get_default_broker_provider(),
        "autonomy": "supervised" if supervision == "supervised" else supervision,
        "scheduler_mode": "paused" if _kill_switch_armed else _scheduler_mode,
        "regime": "mixed_vol",
        "daily_pnl": 0.0,
        "win_rate": 0.0,
        "drawdown_pct": 0.0,
        "portfolio_greeks": {
            "total_delta": 0.0,
            "total_gamma": 0.0,
            "total_theta": 0.0,
            "total_vega": 0.0,
        },
        "circuit_breakers_active": ["kill_switch"] if _kill_switch_armed else [],
        "pending_count": 0,
        "one_trade_locked": is_one_trade_locked(),
        "active_trade_id": get_active_trade_id(),
        "kill_switch_armed": _kill_switch_armed,
        "place_order_enabled": place_order_enabled(),
        "api_health": "ok",
        "phase": "1",
    }


@router.post("/bot/pause")
async def pause_bot():
    """Kill-switch placeholder — pauses scheduler; Phase 2 wires full halt path."""
    global _kill_switch_armed, _scheduler_mode
    _kill_switch_armed = True
    _scheduler_mode = "paused"
    return {
        "status": "paused",
        "kill_switch_armed": True,
        "detail": "Kill-switch placeholder armed (Phase 0); bot loop not yet running",
    }


@router.post("/bot/resume")
async def resume_bot():
    global _kill_switch_armed, _scheduler_mode
    _kill_switch_armed = False
    _scheduler_mode = "active"
    return {"status": "active", "kill_switch_armed": False}


@router.get("/feeds/status")
async def list_feed_status() -> list[FeedSource]:
    """ICICI Direct + Market_News feed health (MCP registry retired — plan §1 / 0.3)."""
    return get_feed_sources()
