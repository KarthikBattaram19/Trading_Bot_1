"""ICICI Direct A2 WebSocket Streaming 2.0 unit tests (no live Breeze network)."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from backend.integrations.icici_direct.instrument_master import InstrumentMaster
from backend.integrations.icici_direct.market_data import (
    decode_breeze_tick,
    make_test_market_data_with_fake_ws,
)
from backend.integrations.icici_direct.models import NormalizedTick
from backend.integrations.icici_direct.ws_stream import (
    BreezeMarketStream,
    FakeStreamTransport,
    decode_breeze_ws_auth,
    stock_token_for_quotes,
)


def _session_token(user: str = "AF296713", feed: str = "66987976") -> str:
    return base64.b64encode(f"{user}:{feed}".encode("ascii")).decode("ascii")


def test_decode_breeze_ws_auth():
    token = _session_token()
    user, feed = decode_breeze_ws_auth(token)
    assert user == "AF296713"
    assert feed == "66987976"


def test_decode_breeze_ws_auth_rejects_bad():
    with pytest.raises(ValueError):
        decode_breeze_ws_auth("")
    with pytest.raises(ValueError):
        decode_breeze_ws_auth("not-base64!!!")
    with pytest.raises(ValueError):
        decode_breeze_ws_auth(base64.b64encode(b"nouser").decode("ascii"))


def test_stock_token_for_quotes():
    assert stock_token_for_quotes("NSE", "3045") == "4.1!3045"
    assert stock_token_for_quotes("NFO", "40123") == "4.1!40123"
    assert stock_token_for_quotes("BSE", "500209") == "1.1!500209"
    with pytest.raises(ValueError, match="Unsupported exchange"):
        stock_token_for_quotes("XYZ", "1")


def test_decode_breeze_tick_quotes():
    # Matches Breeze docs sample shape (NSE equity quotes)
    payload = [
        "4.1!3045",
        1240,
        1236.2,
        1244.8,
        1229.75,
        -0.18,
        1236.0,
        63,
        1236.55,
        18,
        100,
        1235.13,
    ]
    meta = {"4.1!3045": ("NSE", "SBIN-EQ", "3045")}
    tick = decode_breeze_tick(payload, meta=meta)
    assert tick is not None
    assert tick.exchange == "NSE"
    assert tick.symbol == "SBIN-EQ"
    assert tick.provider_symbol_id == "3045"
    assert tick.ltp == pytest.approx(1236.2)
    assert tick.bid == pytest.approx(1236.0)
    assert tick.ask == pytest.approx(1236.55)
    assert tick.stale is False
    assert tick.provider == "icici_direct"


@pytest.mark.asyncio
async def test_ws_connect_subscribe_and_tick_cache():
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
    adapter, transport = make_test_market_data_with_fake_ws(instrument_master=master)

    # Inject session token without full Breeze login
    class _Client:
        session_token = _session_token()

    adapter.session_manager.ensure_session = AsyncMock(return_value=_Client())  # type: ignore[method-assign]

    status = await adapter.connect_ws()
    assert status["connected"] is True
    assert transport.connect_calls == 1
    assert transport.last_auth == {"user": "AF296713", "token": "66987976"}

    sub = await adapter.subscribe_ws(
        exchange="NSE", tradingsymbol="SBIN-EQ", symboltoken="3045"
    )
    assert sub["subscribed"] == "4.1!3045"
    assert ("join", ["4.1!3045"]) in transport.emitted

    await transport.simulate_stock(
        [
            "4.1!3045",
            800,
            801.5,
            805,
            795,
            1.5,
            801.0,
            10,
            802.0,
            12,
            1,
            800.5,
        ]
    )
    cached = adapter.get_cached_tick("NSE", "3045")
    assert cached is not None
    assert cached.ltp == pytest.approx(801.5)
    assert cached.stale is False
    assert adapter.ws_status()["sub_second_fresh"] is True

    # get_ltp must prefer WS cache (no REST) when sub-second fresh
    adapter.session_manager.ensure_session = AsyncMock(
        side_effect=AssertionError("REST should not be called when WS tick is fresh")
    )  # type: ignore[method-assign]
    tick = await adapter.get_ltp("NSE", "SBIN-EQ", "3045")
    assert tick.ltp == pytest.approx(801.5)


@pytest.mark.asyncio
async def test_ws_disconnect_marks_ticks_stale():
    master = InstrumentMaster()
    master.load_rows(
        [
            {
                "exch_seg": "NSE",
                "symbol": "SBIN-EQ",
                "token": "3045",
                "lotsize": "1",
            }
        ]
    )
    adapter, transport = make_test_market_data_with_fake_ws(instrument_master=master)

    class _Client:
        session_token = _session_token()

    adapter.session_manager.ensure_session = AsyncMock(return_value=_Client())  # type: ignore[method-assign]
    await adapter.connect_ws()
    await adapter.subscribe_ws(exchange="NSE", tradingsymbol="SBIN-EQ", symboltoken="3045")
    await transport.simulate_stock(
        ["4.1!3045", 800, 801.5, 805, 795, 0, 801, 1, 802, 1, 1, 800]
    )
    assert adapter.get_cached_tick("NSE", "3045").stale is False

    await adapter.disconnect_ws()
    assert adapter.ws_connected is False
    assert adapter.get_cached_tick("NSE", "3045").stale is True


@pytest.mark.asyncio
async def test_ensure_ws_connected_opens_when_authenticated():
    adapter, transport = make_test_market_data_with_fake_ws()

    class _Client:
        session_token = _session_token()

    adapter.session_manager.ensure_session = AsyncMock(return_value=_Client())  # type: ignore[method-assign]
    adapter.session_manager.health = lambda: {  # type: ignore[method-assign]
        "authenticated": True,
        "credentials_ready": True,
    }
    status = await adapter.ensure_ws_connected()
    assert status["connected"] is True
    assert transport.connect_calls == 1
    # Probe joins so feed UI is not stuck at subscriptions=0
    assert status["subscription_count"] >= 1
    assert any(
        e[0] == "join" and "4.1!NIFTY 50" in (e[1] if isinstance(e[1], list) else [e[1]])
        for e in transport.emitted
    )

    # No-op reconnect; probes already present
    again = await adapter.ensure_ws_connected()
    assert again["connected"] is True
    assert transport.connect_calls == 1
    assert again["subscription_count"] >= 1


@pytest.mark.asyncio
async def test_ensure_ws_connected_seeds_probes_when_already_connected():
    adapter, transport = make_test_market_data_with_fake_ws()

    class _Client:
        session_token = _session_token()

    adapter.session_manager.ensure_session = AsyncMock(return_value=_Client())  # type: ignore[method-assign]
    await adapter.connect_ws()
    assert adapter.ws_status()["subscription_count"] == 0

    adapter.session_manager.health = lambda: {  # type: ignore[method-assign]
        "authenticated": True,
        "credentials_ready": True,
    }
    status = await adapter.ensure_ws_connected()
    assert status["connected"] is True
    assert status["subscription_count"] >= 1
    assert "4.1!NIFTY 50" in adapter.stream.subscriptions


@pytest.mark.asyncio
async def test_ensure_ws_connected_skips_when_not_authenticated():
    adapter, transport = make_test_market_data_with_fake_ws()
    adapter.session_manager.health = lambda: {  # type: ignore[method-assign]
        "authenticated": False,
        "credentials_ready": False,
    }
    status = await adapter.ensure_ws_connected()
    assert status["connected"] is False
    assert transport.connect_calls == 0


@pytest.mark.asyncio
async def test_ensure_ws_connected_authenticates_when_credentials_ready():
    adapter, transport = make_test_market_data_with_fake_ws()

    class _Client:
        session_token = _session_token()

    adapter.session_manager.health = lambda: {  # type: ignore[method-assign]
        "authenticated": False,
        "credentials_ready": True,
    }
    adapter.session_manager.ensure_session = AsyncMock(return_value=_Client())  # type: ignore[method-assign]
    status = await adapter.ensure_ws_connected()
    assert status["connected"] is True
    assert transport.connect_calls == 1
    assert status["subscription_count"] >= 1
    adapter.session_manager.ensure_session.assert_awaited()


@pytest.mark.asyncio
async def test_ws_probe_tick_marks_feed_sub_second():
    adapter, transport = make_test_market_data_with_fake_ws()

    class _Client:
        session_token = _session_token()

    adapter.session_manager.ensure_session = AsyncMock(return_value=_Client())  # type: ignore[method-assign]
    adapter.session_manager.health = lambda: {  # type: ignore[method-assign]
        "authenticated": True,
        "credentials_ready": True,
    }
    await adapter.ensure_ws_connected()
    await transport.simulate_stock(
        [
            "4.1!NIFTY 50",
            24748.7,
            25006.2,
            25029.5,
            24671.45,
            1.03,
            None,
            None,
            None,
            None,
            None,
            None,
        ]
    )
    status = adapter.ws_status()
    assert status["sub_second_fresh"] is True
    assert status["freshest_tick_age_sec"] is not None
    assert status["freshest_tick_age_sec"] < 1.0
    cached = adapter.get_cached_tick("NSE", "NIFTY 50")
    assert cached is not None
    assert cached.ltp == pytest.approx(25006.2)


@pytest.mark.asyncio
async def test_reconnect_backoff_schedules_after_disconnect():
    transport = FakeStreamTransport()
    stream = BreezeMarketStream(
        transport=transport,
        auto_reconnect=True,
        backoff_base_sec=0.01,
        backoff_max_sec=0.05,
    )
    await stream.connect(session_token_b64=_session_token())
    assert stream.connected is True
    await stream.subscribe("4.1!3045")

    await transport.simulate_disconnect()
    assert stream.connected is False
    assert stream._reconnect_task is not None  # noqa: SLF001

    # Allow reconnect task to fire
    import asyncio

    await asyncio.sleep(0.05)
    # Fake transport reconnects successfully
    assert transport.connect_calls >= 2
    assert stream.connected is True
    # Resubscribe on reconnect
    joins = [e for e in transport.emitted if e[0] == "join"]
    assert any("4.1!3045" in (j[1] if isinstance(j[1], list) else [j[1]]) for j in joins)

    await stream.disconnect()


@pytest.mark.asyncio
async def test_stale_ws_tick_falls_back_past_prefer_window():
    master = InstrumentMaster()
    master.load_rows(
        [
            {
                "exch_seg": "NSE",
                "symbol": "SBIN-EQ",
                "token": "3045",
                "lotsize": "1",
            }
        ]
    )
    adapter, transport = make_test_market_data_with_fake_ws(instrument_master=master)
    adapter.ws_prefer_max_age_sec = 0.05

    class _Client:
        session_token = _session_token()

        async def get_quotes(self, **_kwargs):
            return {"Success": [{"ltp": 999.0, "best_bid_price": 998.0, "best_ask_price": 1000.0}]}

    client = _Client()
    adapter.session_manager.ensure_session = AsyncMock(return_value=client)  # type: ignore[method-assign]
    await adapter.connect_ws()
    await adapter.subscribe_ws(exchange="NSE", tradingsymbol="SBIN-EQ", symboltoken="3045")

    # Inject an old WS tick beyond prefer window
    old = NormalizedTick(
        exchange="NSE",
        symbol="SBIN-EQ",
        provider_symbol_id="3045",
        ltp=801.5,
        ts=datetime.now(timezone.utc) - timedelta(seconds=5),
        stale=False,
    )
    adapter._last_ticks["NSE:3045"] = old  # noqa: SLF001

    tick = await adapter.get_ltp("NSE", "SBIN-EQ", "3045")
    assert tick.ltp == pytest.approx(999.0)


def test_feed_health_includes_ws_capability(monkeypatch):
    from backend.services import feed_health as fh

    class _Sess:
        def health(self):
            return {"authenticated": True, "credentials_ready": True}

    class _Md:
        def ws_status(self):
            return {
                "connected": True,
                "freshest_tick_age_sec": 0.2,
                "subscription_count": 1,
            }

    monkeypatch.setattr(
        "backend.integrations.icici_direct.session_manager.get_session_manager",
        lambda: _Sess(),
    )
    monkeypatch.setattr(
        "backend.integrations.icici_direct.market_data.get_market_data_adapter",
        lambda: _Md(),
    )
    # Import path used inside function
    monkeypatch.setattr(fh, "_icici_direct_feed_status", fh._icici_direct_feed_status)
    source = fh._icici_direct_feed_status()
    assert source.source_id == "icici_direct"
    assert "ws_streaming" in source.capabilities
    assert source.health.value == "fresh"
    assert "sub-second" in (source.detail or "")
