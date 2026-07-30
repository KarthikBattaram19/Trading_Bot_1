"""ICICI Direct A3 shadow dry-run order payload tests (no live Breeze place_order)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.integrations.base import ExecutionMode, InternalOrder, OrderLeg
from backend.integrations.icici_direct.icici_direct_adapter import (
    IciciDirectBrokerAdapter,
    reset_icici_direct_adapter_for_tests,
)
from backend.integrations.icici_direct.instrument_master import InstrumentMaster
from backend.integrations.icici_direct.models import IciciDirectConnectionConfig
from backend.integrations.icici_direct.session_manager import SessionManager


def _master_with_equity_and_options() -> InstrumentMaster:
    master = InstrumentMaster()
    master.load_rows(
        [
            {
                "exch_seg": "NSE",
                "symbol": "SBIN-EQ",
                "token": "3045",
                "lotsize": "1",
                "tick_size": "0.05",
            },
            {
                "exch_seg": "NFO",
                "symbol": "SBIN28MAR24500CE",
                "token": "50001",
                "name": "SBIN",
                "lotsize": "25",
                "tick_size": "0.05",
                "strike": "500",
            },
            {
                "exch_seg": "NFO",
                "symbol": "SBIN28MAR24500PE",
                "token": "50002",
                "name": "SBIN",
                "lotsize": "25",
                "tick_size": "0.05",
                "strike": "500",
            },
        ]
    )
    return master


def _adapter(mode: ExecutionMode = ExecutionMode.shadow) -> IciciDirectBrokerAdapter:
    return IciciDirectBrokerAdapter(
        config=IciciDirectConnectionConfig(),
        session_manager=SessionManager(),
        instrument_master=_master_with_equity_and_options(),
        execution_mode=mode,
    )


@pytest.mark.asyncio
async def test_shadow_submit_logs_payload():
    adapter = _adapter()
    order = InternalOrder(
        internal_order_id="ord_shadow_1",
        legs=[
            OrderLeg(
                leg_id=1,
                symbol="SBIN-EQ",
                side="buy",
                quantity=1,
                order_type="limit",
                limit_price=800.0,
                exchange="NSE",
                symbol_token="3045",
                product="INTRADAY",
            )
        ],
    )
    result = await adapter.submit_order(order)
    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["phase"] == "A3"
    assert result["payloads"][0]["stock_code"] == "SBIN-EQ"
    assert result["payloads"][0]["exchange_code"] == "NSE"
    assert result["payloads"][0]["action"] == "buy"
    assert result["payloads"][0]["order_type"] == "limit"
    assert len(adapter.shadow_orders) == 1
    assert adapter.shadow_orders[0]["op"] == "place_order"
    assert adapter.shadow_orders[0]["phase"] == "A3"


@pytest.mark.asyncio
async def test_shadow_multi_leg_logs_sequential_payloads():
    adapter = _adapter()
    order = InternalOrder(
        internal_order_id="ord_straddle_1",
        strategy_id="simple_vol",
        signal_id="sig_a3",
        underlying_symbol="SBIN",
        legs=[
            OrderLeg(
                leg_id=1,
                symbol="SBIN28MAR24500CE",
                side="buy",
                quantity=25,
                order_type="limit",
                limit_price=12.0,
                exchange="NFO",
                symbol_token="50001",
                type="call",
                strike=500.0,
                expiration="28-Mar-2024",
            ),
            OrderLeg(
                leg_id=2,
                symbol="SBIN28MAR24500PE",
                side="buy",
                quantity=25,
                order_type="limit",
                limit_price=11.5,
                exchange="NFO",
                symbol_token="50002",
                type="put",
                strike=500.0,
                expiration="28-Mar-2024",
            ),
        ],
    )
    result = await adapter.submit_order(order)
    assert result["dry_run"] is True
    assert len(result["order_ids"]) == 2
    assert len(result["payloads"]) == 2
    assert result["payloads"][0]["product"] == "options"
    assert result["payloads"][0]["right"] == "call"
    assert result["payloads"][1]["right"] == "put"
    assert all(oid.startswith("shadow_ord_straddle_1_") for oid in result["order_ids"])


@pytest.mark.asyncio
async def test_shadow_cancel_and_status_logged():
    adapter = _adapter()
    placed = await adapter.submit_order(
        InternalOrder(
            internal_order_id="ord_cx",
            legs=[
                OrderLeg(
                    leg_id=1,
                    symbol="SBIN-EQ",
                    side="buy",
                    quantity=1,
                    order_type="limit",
                    limit_price=800.0,
                    exchange="NSE",
                    symbol_token="3045",
                    product="INTRADAY",
                )
            ],
        )
    )
    oid = placed["order_ids"][0]
    status = await adapter.get_order_status(oid)
    assert status["dry_run"] is True
    assert status["status"] == "complete"

    cancelled = await adapter.cancel_order(oid, exchange_code="NSE")
    assert cancelled["dry_run"] is True
    assert cancelled["shadow_logged"] is True

    status2 = await adapter.get_order_status(oid)
    assert status2["status"] == "cancelled"

    ops = [e["op"] for e in adapter.shadow_orders]
    assert ops.count("place_order") == 1
    assert ops.count("cancel_order") == 1
    assert ops.count("get_order_status") == 2


@pytest.mark.asyncio
async def test_shadow_never_calls_client_place_order():
    adapter = _adapter()
    fake_client = MagicMock()
    fake_client.place_order = AsyncMock(
        side_effect=AssertionError("live place_order must not be called in A3")
    )
    adapter.session_manager.ensure_session = AsyncMock(return_value=fake_client)  # type: ignore[method-assign]

    await adapter.submit_order(
        InternalOrder(
            internal_order_id="ord_no_live",
            legs=[
                OrderLeg(
                    leg_id=1,
                    symbol="SBIN-EQ",
                    side="buy",
                    quantity=1,
                    order_type="limit",
                    limit_price=100.0,
                    exchange="NSE",
                    symbol_token="3045",
                )
            ],
        )
    )
    fake_client.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_paper_mode_also_dry_runs():
    adapter = _adapter(ExecutionMode.paper)
    result = await adapter.submit_order(
        InternalOrder(
            internal_order_id="ord_paper_dry",
            legs=[
                OrderLeg(
                    leg_id=1,
                    symbol="SBIN-EQ",
                    side="sell",
                    quantity=1,
                    order_type="limit",
                    limit_price=801.0,
                    exchange="NSE",
                    symbol_token="3045",
                    product="INTRADAY",
                )
            ],
        )
    )
    assert result["dry_run"] is True
    assert adapter.shadow_orders[0]["mode"] == "paper"


def test_shadow_order_api_single_and_multi_leg(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    monkeypatch.delenv("ALLOW_LIVE_PLACE_ORDER", raising=False)
    reset_icici_direct_adapter_for_tests()

    # Seed instrument master on the singleton adapter used by the API
    from backend.integrations.icici_direct.icici_direct_adapter import get_icici_direct_adapter

    adapter = get_icici_direct_adapter()
    adapter.set_execution_mode(ExecutionMode.shadow)
    adapter.instruments = _master_with_equity_and_options()
    adapter.clear_shadow_log()

    from backend.main import app

    client = TestClient(app)

    single = client.post(
        "/api/v1/config/integrations/broker/shadow-order",
        json={
            "internal_order_id": "api_ord_1",
            "symbol": "SBIN-EQ",
            "exchange": "NSE",
            "symboltoken": "3045",
            "side": "buy",
            "quantity": 1,
            "order_type": "limit",
            "limit_price": 800.0,
            "product": "INTRADAY",
        },
    )
    assert single.status_code == 200, single.text
    body = single.json()
    assert body["ok"] is True
    assert body["phase"] == "A3"
    assert body["dry_run"] is True
    assert len(body["payloads"]) == 1

    multi = client.post(
        "/api/v1/config/integrations/broker/shadow-order",
        json={
            "internal_order_id": "api_straddle",
            "underlying_symbol": "SBIN",
            "legs": [
                {
                    "leg_id": 1,
                    "symbol": "SBIN28MAR24500CE",
                    "exchange": "NFO",
                    "symboltoken": "50001",
                    "side": "buy",
                    "quantity": 25,
                    "order_type": "limit",
                    "limit_price": 12.0,
                    "type": "call",
                    "strike": 500,
                    "expiration": "28-Mar-2024",
                },
                {
                    "leg_id": 2,
                    "symbol": "SBIN28MAR24500PE",
                    "exchange": "NFO",
                    "symboltoken": "50002",
                    "side": "buy",
                    "quantity": 25,
                    "order_type": "limit",
                    "limit_price": 11.5,
                    "type": "put",
                    "strike": 500,
                    "expiration": "28-Mar-2024",
                },
            ],
        },
    )
    assert multi.status_code == 200, multi.text
    multi_body = multi.json()
    assert len(multi_body["order_ids"]) == 2

    listed = client.get("/api/v1/config/integrations/broker/shadow-orders?op=place_order")
    assert listed.status_code == 200
    listed_body = listed.json()
    assert listed_body["count"] >= 2

    oid = multi_body["order_ids"][0]
    status = client.post(
        "/api/v1/config/integrations/broker/shadow-order-status",
        json={"order_id": oid},
    )
    assert status.status_code == 200
    assert status.json()["dry_run"] is True

    cancel = client.post(
        "/api/v1/config/integrations/broker/shadow-cancel",
        json={"order_id": oid, "exchange_code": "NFO"},
    )
    assert cancel.status_code == 200
    assert cancel.json()["dry_run"] is True

    cleared = client.delete("/api/v1/config/integrations/broker/shadow-orders")
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] >= 1


def test_shadow_order_blocked_in_live(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("ALLOW_LIVE_PLACE_ORDER", "false")
    reset_icici_direct_adapter_for_tests()
    from backend.main import app

    client = TestClient(app)
    res = client.post(
        "/api/v1/config/integrations/broker/shadow-order",
        json={"symbol": "SBIN-EQ", "symboltoken": "3045", "quantity": 1},
    )
    assert res.status_code == 400
    assert "live" in res.json()["detail"].lower()
