"""ICICI Direct adapter unit tests (no live Breeze API calls)."""

from __future__ import annotations

import pytest

from backend.integrations.icici_direct.icici_direct_adapter import IciciDirectBrokerAdapter
from backend.integrations.icici_direct.instrument_master import InstrumentMaster
from backend.integrations.icici_direct.models import IciciDirectConnectionConfig
from backend.integrations.icici_direct.order_mapper import OrderMapper
from backend.integrations.icici_direct.session_manager import SessionManager
from backend.integrations.base import ExecutionMode, InternalOrder, OrderLeg


def test_order_mapper_lot_and_tick():
    mapper = OrderMapper()
    order = InternalOrder(
        internal_order_id="ord_1",
        signal_id="sig_long_name_for_hash",
        legs=[
            OrderLeg(
                leg_id=1,
                symbol="NIFTY28MAR2422000CE",
                side="buy",
                quantity=50,
                order_type="limit",
                limit_price=125.53,
                exchange="NFO",
            )
        ],
    )
    payload = mapper.map_leg(
        order,
        order.legs[0],
        tradingsymbol="NIFTY28MAR2422000CE",
        symboltoken="40123",
        exchange="NFO",
        lotsize=25,
        tick_size=0.05,
        stock_code="NIFTY",
        expiry="28-Mar-2024",
        strike=22000.0,
        right="call",
        instrumenttype="OPTIDX",
    )
    assert payload.quantity == "50"
    assert payload.action == "buy"
    assert payload.order_type == "limit"
    assert payload.exchange_code == "NFO"
    assert payload.product == "options"
    assert payload.user_remark is not None
    assert len(payload.user_remark) <= 50
    # 125.53 snaps to nearest 0.05
    assert float(payload.price) == pytest.approx(125.55, abs=0.01)


def test_order_mapper_rejects_bad_lot():
    mapper = OrderMapper()
    order = InternalOrder(internal_order_id="ord_2", legs=[])
    leg = OrderLeg(
        leg_id=1,
        symbol="NIFTY28MAR2422000CE",
        side="buy",
        quantity=10,
        order_type="market",
    )
    with pytest.raises(ValueError, match="lotsize"):
        mapper.map_leg(
            order,
            leg,
            tradingsymbol="NIFTY28MAR2422000CE",
            symboltoken="40123",
            exchange="NFO",
            lotsize=25,
        )


def test_instrument_master_load_and_resolve():
    master = InstrumentMaster()
    count = master.load_rows(
        [
            {
                "exch_seg": "NSE",
                "symbol": "SBIN-EQ",
                "token": "3045",
                "name": "SBIN",
                "lotsize": "1",
                "tick_size": "0.05",
            },
            {
                "exch_seg": "NFO",
                "symbol": "NIFTY28MAR2422000CE",
                "token": "40123",
                "name": "NIFTY",
                "lotsize": "25",
                "strike": "22000",
            },
        ]
    )
    assert count == 2
    sbin = master.resolve(exchange="NSE", tradingsymbol="SBIN-EQ")
    assert sbin is not None
    assert sbin.symboltoken == "3045"
    nifty = master.resolve(symboltoken="40123")
    assert nifty is not None
    assert nifty.lotsize == 25
    assert nifty.strike == pytest.approx(22000.0)


@pytest.mark.asyncio
async def test_shadow_submit_logs_payload():
    master = InstrumentMaster()
    master.load_rows(
        [
            {
                "exch_seg": "NSE",
                "symbol": "SBIN-EQ",
                "token": "3045",
                "lotsize": "1",
                "tick_size": "0.05",
            }
        ]
    )
    adapter = IciciDirectBrokerAdapter(
        config=IciciDirectConnectionConfig(),
        session_manager=SessionManager(),
        instrument_master=master,
        execution_mode=ExecutionMode.shadow,
    )
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
