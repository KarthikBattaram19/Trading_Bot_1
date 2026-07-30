"""Integration registry, EXECUTION_MODE, and aggregate health (Phase 0)."""

from __future__ import annotations

import os
from typing import Any

from backend.integrations.base import BrokerAdapter, ExecutionMode
from backend.integrations.icici_direct.icici_direct_adapter import get_icici_direct_adapter
from backend.integrations.icici_direct.market_data import get_market_data_adapter
from backend.integrations.icici_direct.session_manager import get_session_manager


def get_execution_mode() -> ExecutionMode:
    """Default shadow for Phase 0 — never live on Railway paper stack."""
    raw = os.getenv("EXECUTION_MODE", "shadow").strip().lower()
    try:
        return ExecutionMode(raw)
    except ValueError:
        return ExecutionMode.shadow


def place_order_enabled() -> bool:
    """
    Breeze place_order is disabled through Phase 4.
    Requires EXECUTION_MODE=live and explicit ALLOW_LIVE_PLACE_ORDER=true (Phase 5 / GCP).
    """
    if get_execution_mode() != ExecutionMode.live:
        return False
    return os.getenv("ALLOW_LIVE_PLACE_ORDER", "").strip().lower() in {"1", "true", "yes"}


def get_default_broker_provider() -> str:
    return os.getenv("DEFAULT_BROKER", "icici_direct").strip().lower()


def get_broker_adapter(provider: str | None = None) -> BrokerAdapter:
    name = (provider or get_default_broker_provider()).lower()
    if name in {"icici_direct", "icicidirect", "icici", "breeze"}:
        adapter = get_icici_direct_adapter()
        adapter.set_execution_mode(get_execution_mode())
        return adapter
    raise ValueError(f"Unsupported broker provider: {name}")


async def get_integration_health() -> dict[str, Any]:
    adapter = get_icici_direct_adapter()
    adapter.set_execution_mode(get_execution_mode())
    market = get_market_data_adapter()
    session = get_session_manager()
    return {
        "execution_mode": get_execution_mode().value,
        "place_order_enabled": place_order_enabled(),
        "default_broker": get_default_broker_provider(),
        "icici_direct": {
            "broker": await adapter.health(),
            "market_data": market.health(),
            "session": session.health(),
        },
    }
