"""Broker / feed integration APIs — Phase 0 A0–A1 (+ optional A3 shadow dry-run)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.integrations.base import ExecutionMode, InternalOrder, OrderLeg
from backend.integrations.credential_vault import load_icici_direct_credentials
from backend.integrations.icici_direct.client import IciciDirectAPIError
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


class ShadowOrderRequest(BaseModel):
    internal_order_id: str = "ord_test_001"
    symbol: str
    exchange: str = "NSE"
    symboltoken: str | None = None
    side: str = "BUY"
    quantity: int = 1
    order_type: str = "LIMIT"
    limit_price: float | None = 100.0
    product: str = "margin"


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
    """A1 — LTP REST → normalized tick."""
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


@router.post("/broker/shadow-order")
async def shadow_order(body: ShadowOrderRequest) -> dict[str, Any]:
    """Optional A3 dry-run — logs place_order payloads; never hits Breeze place_order."""
    if get_execution_mode() == ExecutionMode.live:
        raise HTTPException(
            status_code=400,
            detail="shadow-order blocked while EXECUTION_MODE=live",
        )
    adapter = get_broker_adapter("icici_direct")
    order = InternalOrder(
        internal_order_id=body.internal_order_id,
        legs=[
            OrderLeg(
                leg_id=1,
                symbol=body.symbol,
                side=body.side,
                quantity=body.quantity,
                order_type=body.order_type,
                limit_price=body.limit_price,
                exchange=body.exchange,
                symbol_token=body.symboltoken,
                product=body.product,
            )
        ],
    )
    try:
        result = await adapter.submit_order(order)
        return result
    except (IciciDirectAPIError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
