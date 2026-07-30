"""Broker / feed integration APIs — Phase 0–1 A0–A3 (A3 = shadow dry-run order payloads)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.integrations.base import ExecutionMode, InternalOrder, OrderLeg
from backend.integrations.credential_vault import load_icici_direct_credentials
from backend.integrations.icici_direct.client import IciciDirectAPIError
from backend.integrations.icici_direct.icici_direct_adapter import IciciDirectBrokerAdapter
from backend.integrations.icici_direct.market_data import get_market_data_adapter
from backend.integrations.icici_direct.session_manager import get_session_manager
from backend.integrations.registry import (
    get_broker_adapter,
    get_execution_mode,
    get_integration_health,
    place_order_enabled,
)

router = APIRouter(prefix="/api/v1/config/integrations", tags=["integrations"])


class BrokerTestResponse(BaseModel):
    ok: bool
    provider: str = "icici_direct"
    detail: str
    profile_exchanges: list[str] = Field(default_factory=list)
    authenticated_at: str | None = None
    place_order_enabled: bool = False


class LtpRequest(BaseModel):
    exchange: str
    tradingsymbol: str
    symboltoken: str | None = None


class WsSubscribeRequest(BaseModel):
    exchange: str
    tradingsymbol: str
    symboltoken: str | None = None


class WsUnsubscribeRequest(BaseModel):
    exchange: str
    symboltoken: str


class ShadowLegRequest(BaseModel):
    leg_id: int = 1
    symbol: str
    exchange: str = "NSE"
    symboltoken: str | None = None
    side: str = "BUY"
    quantity: int = 1
    order_type: str = "LIMIT"
    limit_price: float | None = 100.0
    stop_price: float | None = None
    product: str = "margin"
    type: str | None = None  # call | put | equity
    strike: float | None = None
    expiration: str | None = None


class ShadowOrderRequest(BaseModel):
    """A3 dry-run place_order — single-leg shorthand or multi-leg `legs` basket."""

    internal_order_id: str = "ord_test_001"
    strategy_id: str | None = None
    signal_id: str | None = None
    underlying_symbol: str | None = None
    # Single-leg shorthand (used when `legs` omitted)
    symbol: str | None = None
    exchange: str = "NSE"
    symboltoken: str | None = None
    side: str = "BUY"
    quantity: int = 1
    order_type: str = "LIMIT"
    limit_price: float | None = 100.0
    stop_price: float | None = None
    product: str = "margin"
    type: str | None = None
    strike: float | None = None
    expiration: str | None = None
    legs: list[ShadowLegRequest] | None = None


class ShadowCancelRequest(BaseModel):
    order_id: str
    exchange_code: str = "NSE"


class ShadowStatusRequest(BaseModel):
    order_id: str


def _require_dry_run_mode() -> None:
    if get_execution_mode() == ExecutionMode.live:
        raise HTTPException(
            status_code=400,
            detail="A3 shadow dry-run blocked while EXECUTION_MODE=live",
        )


def _shadow_adapter() -> IciciDirectBrokerAdapter:
    adapter = get_broker_adapter("icici_direct")
    if not isinstance(adapter, IciciDirectBrokerAdapter):
        raise HTTPException(status_code=500, detail="ICICI Direct adapter unavailable")
    return adapter


def _build_internal_order(body: ShadowOrderRequest) -> InternalOrder:
    if body.legs:
        order_legs = [
            OrderLeg(
                leg_id=leg.leg_id,
                symbol=leg.symbol,
                side=leg.side,
                quantity=leg.quantity,
                order_type=leg.order_type,
                limit_price=leg.limit_price,
                stop_price=leg.stop_price,
                exchange=leg.exchange,
                symbol_token=leg.symboltoken,
                product=leg.product,
                type=leg.type,
                strike=leg.strike,
                expiration=leg.expiration,
            )
            for leg in body.legs
        ]
    else:
        if not body.symbol:
            raise HTTPException(
                status_code=400,
                detail="Provide `symbol` (single-leg) or non-empty `legs` (multi-leg)",
            )
        order_legs = [
            OrderLeg(
                leg_id=1,
                symbol=body.symbol,
                side=body.side,
                quantity=body.quantity,
                order_type=body.order_type,
                limit_price=body.limit_price,
                stop_price=body.stop_price,
                exchange=body.exchange,
                symbol_token=body.symboltoken,
                product=body.product,
                type=body.type,
                strike=body.strike,
                expiration=body.expiration,
            )
        ]
    return InternalOrder(
        internal_order_id=body.internal_order_id,
        strategy_id=body.strategy_id,
        signal_id=body.signal_id,
        underlying_symbol=body.underlying_symbol,
        mode=get_execution_mode(),
        legs=order_legs,
    )


@router.get("/health")
async def integrations_health() -> dict[str, Any]:
    return await get_integration_health()


@router.post("/broker/test", response_model=BrokerTestResponse)
async def test_broker_connection() -> BrokerTestResponse:
    """A0 — authenticate against ICICI Direct Breeze using vault/env credentials."""
    load_icici_direct_credentials()
    session_mgr = get_session_manager()
    if not session_mgr.credentials_ready():
        raise HTTPException(
            status_code=400,
            detail=(
                "ICICI Direct credentials missing. Set ICICI_DIRECT_API_KEY, "
                "ICICI_DIRECT_API_SECRET, ICICI_DIRECT_SESSION_TOKEN. "
                + session_mgr.login_hint()
            ),
        )
    try:
        adapter = get_broker_adapter("icici_direct")
        auth = await adapter.authenticate()
        # authenticate() already exchanged API_Session via customerdetails.
        await session_mgr.ensure_session()
        return BrokerTestResponse(
            ok=True,
            detail="ICICI Direct Breeze session established (data-only; place_order disabled)",
            profile_exchanges=[],
            authenticated_at=auth.get("authenticated_at"),
            place_order_enabled=place_order_enabled(),
        )
    except IciciDirectAPIError as exc:
        msg = str(exc)
        status = 400 if "credential" in msg.lower() or "non-ascii" in msg.lower() else 502
        raise HTTPException(status_code=status, detail=msg) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Broker test failed: {exc}") from exc


@router.post("/broker/ltp")
async def fetch_ltp(body: LtpRequest) -> dict[str, Any]:
    """A1 — LTP REST → normalized tick (prefers fresh A2 WS cache when available)."""
    try:
        tick = await get_market_data_adapter().get_ltp(
            body.exchange, body.tradingsymbol, body.symboltoken
        )
        return tick.model_dump(mode="json")
    except IciciDirectAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/broker/instruments/refresh")
async def refresh_instruments() -> dict[str, Any]:
    """A1 — download / refresh Breeze security master."""
    try:
        count = await get_market_data_adapter().ensure_instruments()
        return {"ok": True, "instrument_count": count, "phase": "A1"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/broker/ws/connect")
async def ws_connect() -> dict[str, Any]:
    """A2 — open Breeze livestream Socket.IO (rate refresh) connection."""
    try:
        status = await get_market_data_adapter().connect_ws()
        return {"ok": True, "phase": "A2", "ws": status}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"WS connect failed: {exc}") from exc


@router.post("/broker/ws/disconnect")
async def ws_disconnect() -> dict[str, Any]:
    """A2 — disconnect livestream; marks flagged stale."""
    status = await get_market_data_adapter().disconnect_ws()
    return {"ok": True, "phase": "A2", "ws": status}


@router.get("/broker/ws/status")
async def ws_status() -> dict[str, Any]:
    """A2 — WS connection, subscriptions, and tick freshness."""
    return {"phase": "A2", "ws": get_market_data_adapter().ws_status()}


@router.post("/broker/ws/subscribe")
async def ws_subscribe(body: WsSubscribeRequest) -> dict[str, Any]:
    """A2 — subscribe quotes mode for one token (one mode per token)."""
    try:
        result = await get_market_data_adapter().subscribe_ws(
            exchange=body.exchange,
            tradingsymbol=body.tradingsymbol,
            symboltoken=body.symboltoken,
        )
        return {"ok": True, "phase": "A2", **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"WS subscribe failed: {exc}") from exc


@router.post("/broker/ws/unsubscribe")
async def ws_unsubscribe(body: WsUnsubscribeRequest) -> dict[str, Any]:
    """A2 — leave quotes subscription for a token."""
    try:
        result = await get_market_data_adapter().unsubscribe_ws(
            exchange=body.exchange,
            symboltoken=body.symboltoken,
        )
        return {"ok": True, "phase": "A2", **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"WS unsubscribe failed: {exc}") from exc


@router.post("/broker/shadow-order")
async def shadow_order(body: ShadowOrderRequest) -> dict[str, Any]:
    """A3 — map InternalOrder → Breeze place_order payloads and log only (no live submit)."""
    _require_dry_run_mode()
    adapter = _shadow_adapter()
    order = _build_internal_order(body)
    try:
        result = await adapter.submit_order(order)
        return {"ok": True, "phase": "A3", **result}
    except (IciciDirectAPIError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/broker/shadow-cancel")
async def shadow_cancel(body: ShadowCancelRequest) -> dict[str, Any]:
    """A3 — dry-run cancel_order payload log; never hits Breeze cancel."""
    _require_dry_run_mode()
    adapter = _shadow_adapter()
    try:
        result = await adapter.cancel_order(
            body.order_id, exchange_code=body.exchange_code
        )
        return {"ok": True, "phase": "A3", **result}
    except (IciciDirectAPIError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/broker/shadow-order-status")
async def shadow_order_status(body: ShadowStatusRequest) -> dict[str, Any]:
    """A3 — dry-run get_order_status against the in-memory shadow index."""
    _require_dry_run_mode()
    adapter = _shadow_adapter()
    try:
        result = await adapter.get_order_status(body.order_id)
        return {"ok": True, "phase": "A3", **result}
    except (IciciDirectAPIError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/broker/shadow-orders")
async def list_shadow_orders(
    limit: int = Query(default=50, ge=1, le=500),
    op: str | None = Query(default=None, description="Filter by op: place_order|cancel_order|get_order_status"),
) -> dict[str, Any]:
    """A3 — list logged dry-run order payloads (newest last)."""
    _require_dry_run_mode()
    adapter = _shadow_adapter()
    entries = adapter.shadow_orders
    if op:
        entries = [e for e in entries if e.get("op") == op]
    sliced = entries[-limit:]
    return {
        "ok": True,
        "phase": "A3",
        "count": len(sliced),
        "total_logged": len(adapter.shadow_orders),
        "entries": sliced,
    }


@router.delete("/broker/shadow-orders")
async def clear_shadow_orders() -> dict[str, Any]:
    """A3 — clear in-memory shadow dry-run log (test / operator reset)."""
    _require_dry_run_mode()
    adapter = _shadow_adapter()
    cleared = adapter.clear_shadow_log()
    return {"ok": True, "phase": "A3", "cleared": cleared}
