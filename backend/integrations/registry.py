"""Integration registry, EXECUTION_MODE, and paper-stack live gate (Phase 1.10)."""

from __future__ import annotations

import logging
import os
from typing import Any

from backend.integrations.base import BrokerAdapter, ExecutionMode
from backend.integrations.icici_direct.icici_direct_adapter import get_icici_direct_adapter
from backend.integrations.icici_direct.market_data import get_market_data_adapter
from backend.integrations.icici_direct.session_manager import get_session_manager

logger = logging.getLogger(__name__)

_LIVE_ON_PAPER_ALERTED = False

_PAPER_STACK_VALUES = frozenset({"paper", "railway"})
_NON_PAPER_STACK_VALUES = frozenset({"gcp", "live", "cloud_run", "local"})


def is_paper_deploy_stack() -> bool:
    """
    True on the Railway paper host (Phase 1.10) or when DEPLOY_STACK=paper|railway.

    Railway injects RAILWAY_* variables into every service; live ICICI Direct
    orders are GCP-only (Phase 5) and must never run on this stack (M-01).
    """
    stack = os.getenv("DEPLOY_STACK", "").strip().lower()
    if stack in _PAPER_STACK_VALUES:
        return True
    if stack in _NON_PAPER_STACK_VALUES:
        return False
    return bool(
        os.getenv("RAILWAY_ENVIRONMENT")
        or os.getenv("RAILWAY_PROJECT_ID")
        or os.getenv("RAILWAY_SERVICE_ID")
        or os.getenv("RAILWAY_STATIC_URL")
    )


def get_requested_execution_mode() -> ExecutionMode:
    """Raw EXECUTION_MODE from the environment (before paper-stack coercion)."""
    default = "paper" if is_paper_deploy_stack() else "shadow"
    raw = os.getenv("EXECUTION_MODE", default).strip().lower() or default
    try:
        return ExecutionMode(raw)
    except ValueError:
        return ExecutionMode.paper if is_paper_deploy_stack() else ExecutionMode.shadow


def _alert_live_blocked_on_paper() -> None:
    global _LIVE_ON_PAPER_ALERTED
    msg = (
        "M-01 / Phase 1.10: EXECUTION_MODE=live rejected on paper stack "
        "(Railway). Coercing effective mode to paper; place_order remains "
        "disabled. Live orders require GCP (Phase 5)."
    )
    if not _LIVE_ON_PAPER_ALERTED:
        logger.error(msg)
        _LIVE_ON_PAPER_ALERTED = True


def get_execution_mode() -> ExecutionMode:
    """
    Effective submit-path mode.

    Default shadow for local Phase 0. On Railway / DEPLOY_STACK=paper, live is
    coerced to paper (plan §1.10, edge case M-01) — never live on this stack.
    """
    mode = get_requested_execution_mode()
    if mode == ExecutionMode.live and is_paper_deploy_stack():
        _alert_live_blocked_on_paper()
        return ExecutionMode.paper
    return mode


def place_order_enabled() -> bool:
    """
    Breeze place_order is disabled through Phase 4 and always on the paper stack.

    Requires non-paper deploy, EXECUTION_MODE=live, and ALLOW_LIVE_PLACE_ORDER=true
    (Phase 5 / GCP only).
    """
    if is_paper_deploy_stack():
        requested = get_requested_execution_mode()
        allow = os.getenv("ALLOW_LIVE_PLACE_ORDER", "").strip().lower() in {"1", "true", "yes"}
        if requested == ExecutionMode.live or allow:
            _alert_live_blocked_on_paper()
        return False
    if get_execution_mode() != ExecutionMode.live:
        return False
    return os.getenv("ALLOW_LIVE_PLACE_ORDER", "").strip().lower() in {"1", "true", "yes"}


def paper_stack_guard_status() -> dict[str, Any]:
    """Health / bot fields for Phase 1.10 config confirmation and M-01 alerts."""
    paper = is_paper_deploy_stack()
    requested = get_requested_execution_mode()
    effective = get_execution_mode()
    allow_env = os.getenv("ALLOW_LIVE_PLACE_ORDER", "").strip().lower() in {"1", "true", "yes"}
    live_blocked = paper and (requested == ExecutionMode.live or allow_env)
    explicit = os.getenv("DEPLOY_STACK", "").strip().lower()
    if paper:
        deploy_stack = "paper"
    elif explicit:
        deploy_stack = explicit
    else:
        deploy_stack = "local"
    return {
        "deploy_stack": deploy_stack,
        "requested_execution_mode": requested.value,
        "execution_mode": effective.value,
        "live_blocked": live_blocked,
        "place_order_enabled": place_order_enabled(),
        "allow_live_place_order": allow_env,
        "paper_stack_never_live": True,
    }


def reset_paper_stack_alert_for_tests() -> None:
    global _LIVE_ON_PAPER_ALERTED
    _LIVE_ON_PAPER_ALERTED = False


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
    guard = paper_stack_guard_status()
    return {
        "execution_mode": guard["execution_mode"],
        "requested_execution_mode": guard["requested_execution_mode"],
        "deploy_stack": guard["deploy_stack"],
        "live_blocked": guard["live_blocked"],
        "place_order_enabled": guard["place_order_enabled"],
        "default_broker": get_default_broker_provider(),
        "icici_direct": {
            "broker": await adapter.health(),
            "market_data": market.health(),
            "session": session.health(),
        },
    }
