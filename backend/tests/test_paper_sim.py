"""Unit + HTTP integration tests for Phase 1.1 paper_sim ledger (no live ICICI Direct)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.integrations.icici_direct.models import InstrumentRecord, NormalizedTick
from backend.paper_sim.config import PaperSimConfig
from backend.paper_sim.engine import PaperEngine
from backend.paper_sim.fill_model import compute_fill_price
from backend.paper_sim.ledger import PaperLedger, PaperLedgerError
from backend.paper_sim.models import PaperLegRequest, PaperOrderRequest, PaperSide
from backend.paper_sim.service import get_paper_engine


class FakeFeed:
    def __init__(self) -> None:
        self.instruments = {
            "40123": InstrumentRecord(
                exchange="NFO",
                tradingsymbol="SBIN28MAR24500CE",
                symboltoken="40123",
                name="SBIN",
                expiry="28MAR2024",
                strike=500.0,
                lotsize=25,
                instrumenttype="OPTSTK",
            ),
            "40124": InstrumentRecord(
                exchange="NFO",
                tradingsymbol="SBIN28MAR24500PE",
                symboltoken="40124",
                name="SBIN",
                expiry="28MAR2024",
                strike=500.0,
                lotsize=25,
                instrumenttype="OPTSTK",
            ),
            "40125": InstrumentRecord(
                exchange="NFO",
                tradingsymbol="SBIN28MAR24480CE",
                symboltoken="40125",
                name="SBIN",
                expiry="28MAR2024",
                strike=480.0,
                lotsize=25,
                instrumenttype="OPTSTK",
            ),
            "3045": InstrumentRecord(
                exchange="NSE",
                tradingsymbol="SBIN",
                symboltoken="3045",
                name="SBIN",
                lotsize=1,
                instrumenttype="EQ",
            ),
            "1594": InstrumentRecord(
                exchange="NSE",
                tradingsymbol="INFY",
                symboltoken="1594",
                name="INFY",
                lotsize=1,
                instrumenttype="EQ",
            ),
            "NIFTY": InstrumentRecord(
                exchange="NSE",
                tradingsymbol="NIFTY",
                symboltoken="NIFTY",
                name="NIFTY",
                lotsize=1,
                instrumenttype="AMXIDX",
            ),
        }
        self.ltps = {
            "40123": 12.0,
            "40124": 11.0,
            "40125": 20.0,
            "3045": 750.0,
            "1594": 1680.0,
            "NIFTY": 22000.0,
        }
        self.stale_tokens: set[str] = set()
        self.age_sec: dict[str, float] = {}
        self.instruments_loaded_at = datetime.now(timezone.utc)

    async def ensure_instruments(self, *, max_age_sec: float | None = None) -> int:
        _ = max_age_sec
        return len(self.instruments)

    async def get_ltp(
        self,
        exchange: str,
        tradingsymbol: str,
        symboltoken: str | None = None,
    ) -> NormalizedTick:
        from datetime import timedelta

        token = symboltoken
        if not token:
            for rec in self.instruments.values():
                if rec.tradingsymbol == tradingsymbol:
                    token = rec.symboltoken
                    break
        assert token is not None
        age = float(self.age_sec.get(token, 0.0))
        ts = datetime.now(timezone.utc) - timedelta(seconds=age)
        return NormalizedTick(
            exchange=exchange,
            symbol=tradingsymbol,
            provider_symbol_id=token,
            ltp=float(self.ltps[token]),
            ts=ts,
            stale=token in self.stale_tokens,
        )

    def list_options(
        self,
        *,
        name: str,
        exchange: str = "NFO",
        expiry: str | None = None,
        limit: int = 500,
    ) -> list[InstrumentRecord]:
        rows = [r for r in self.instruments.values() if (r.name or "").upper() == name.upper()]
        rows = [r for r in rows if (r.exchange or "").upper() == exchange.upper()]
        return rows[:limit]

    def resolve(
        self,
        *,
        exchange: str | None = None,
        tradingsymbol: str | None = None,
        symboltoken: str | None = None,
    ) -> InstrumentRecord | None:
        if symboltoken and symboltoken in self.instruments:
            return self.instruments[symboltoken]
        if tradingsymbol:
            for rec in self.instruments.values():
                if rec.tradingsymbol.upper() == tradingsymbol.upper():
                    if exchange and rec.exchange.upper() != exchange.upper():
                        continue
                    return rec
        return None

    def health(self) -> dict:
        return {
            "feed": "fake",
            "execution_coupled": False,
            "instrument_count": len(self.instruments),
        }


def _simple_vol_order() -> PaperOrderRequest:
    """Long ATM CE+PE pair — simple_vol playbook shape (not a named structure)."""
    return PaperOrderRequest(
        strategy_tag="simple_vol",
        underlying="SBIN",
        legs=[
            PaperLegRequest(
                symbol="SBIN28MAR24500CE",
                side=PaperSide.buy,
                quantity=25,
                exchange="NFO",
                symbol_token="40123",
            ),
            PaperLegRequest(
                symbol="SBIN28MAR24500PE",
                side=PaperSide.buy,
                quantity=25,
                exchange="NFO",
                symbol_token="40124",
            ),
        ],
    )


def test_fill_price_slippage():
    assert compute_fill_price(100.0, PaperSide.buy, 50) == pytest.approx(100.5)
    assert compute_fill_price(100.0, PaperSide.sell, 50) == pytest.approx(99.5)


def test_ledger_open_and_close_long_vol():
    config = PaperSimConfig(total_capital_inr=1_000_000, slippage_bps=0)
    ledger = PaperLedger(config)
    position, fills = ledger.open_position(
        strategy_tag="vega_scalp",
        underlying="SBIN",
        note="test",
        slippage_bps=0,
        legs=[
            {
                "symbol": "SBIN28MAR24500CE",
                "exchange": "NFO",
                "symbol_token": "40123",
                "side": PaperSide.buy,
                "quantity": 25,
                "mark_ltp": 100.0,
                "lotsize": 25,
            },
            {
                "symbol": "SBIN28MAR24500PE",
                "exchange": "NFO",
                "symbol_token": "40124",
                "side": PaperSide.buy,
                "quantity": 25,
                "mark_ltp": 90.0,
                "lotsize": 25,
            },
        ],
    )
    assert len(fills) == 2
    assert position.status == "open"
    assert ledger.cash == pytest.approx(1_000_000 - (100 * 25 + 90 * 25))

    closed, close_fills, pnl = ledger.close_position(
        position.position_id,
        {"40123": 130.0, "40124": 70.0},
        slippage_bps=0,
    )
    assert closed.status == "closed"
    assert len(close_fills) == 2
    # CE +30 * 25 = +750; PE -20 * 25 = -500; net +250
    assert pnl == pytest.approx(250.0)
    assert ledger.realized_pnl == pytest.approx(250.0)


def test_ledger_short_credit_pnl():
    config = PaperSimConfig(total_capital_inr=1_000_000, slippage_bps=0)
    ledger = PaperLedger(config)
    position, _ = ledger.open_position(
        strategy_tag="short_vol_credit",
        underlying="SBIN",
        note=None,
        slippage_bps=0,
        legs=[
            {
                "symbol": "SBIN28MAR24500CE",
                "exchange": "NFO",
                "symbol_token": "40123",
                "side": PaperSide.sell,
                "quantity": 25,
                "mark_ltp": 100.0,
                "lotsize": 25,
            },
            {
                "symbol": "SBIN28MAR24500PE",
                "exchange": "NFO",
                "symbol_token": "40124",
                "side": PaperSide.sell,
                "quantity": 25,
                "mark_ltp": 90.0,
                "lotsize": 25,
            },
        ],
    )
    assert ledger.cash == pytest.approx(1_000_000 + (100 * 25 + 90 * 25))
    _, _, pnl = ledger.close_position(
        position.position_id,
        {"40123": 80.0, "40124": 70.0},
        slippage_bps=0,
    )
    # CE +(100-80)*25 = 500; PE +(90-70)*25 = 500; net +1000
    assert pnl == pytest.approx(1000.0)
    assert ledger.realized_pnl == pytest.approx(1000.0)


def test_ledger_rejects_oversize_leg():
    config = PaperSimConfig(max_leg_investment_inr=1000, slippage_bps=0)
    ledger = PaperLedger(config)
    with pytest.raises(PaperLedgerError, match="max_leg_investment"):
        ledger.open_position(
            strategy_tag=None,
            underlying="SBIN",
            note=None,
            slippage_bps=0,
            legs=[
                {
                    "symbol": "X",
                    "exchange": "NFO",
                    "symbol_token": "1",
                    "side": PaperSide.buy,
                    "quantity": 25,
                    "mark_ltp": 100.0,
                    "lotsize": 25,
                }
            ],
        )


def test_ledger_rejects_oversize_trade():
    config = PaperSimConfig(
        max_trade_investment_inr=1000,
        max_leg_investment_inr=100_000,
        slippage_bps=0,
    )
    ledger = PaperLedger(config)
    with pytest.raises(PaperLedgerError, match="max_trade_investment"):
        ledger.open_position(
            strategy_tag=None,
            underlying="SBIN",
            note=None,
            slippage_bps=0,
            legs=[
                {
                    "symbol": "SBIN28MAR24500CE",
                    "exchange": "NFO",
                    "symbol_token": "40123",
                    "side": PaperSide.buy,
                    "quantity": 25,
                    "mark_ltp": 100.0,
                    "lotsize": 25,
                }
            ],
        )


def test_ledger_rejects_close_without_mark():
    config = PaperSimConfig(slippage_bps=0)
    ledger = PaperLedger(config)
    position, _ = ledger.open_position(
        strategy_tag=None,
        underlying="SBIN",
        note=None,
        slippage_bps=0,
        legs=[
            {
                "symbol": "SBIN28MAR24500CE",
                "exchange": "NFO",
                "symbol_token": "40123",
                "side": PaperSide.buy,
                "quantity": 25,
                "mark_ltp": 10.0,
                "lotsize": 25,
            }
        ],
    )
    with pytest.raises(PaperLedgerError, match="missing mark"):
        ledger.close_position(position.position_id, {}, slippage_bps=0)


@pytest.mark.asyncio
async def test_engine_submit_and_mtm_with_fake_feed():
    engine = get_paper_engine(feed=FakeFeed(), config=PaperSimConfig(slippage_bps=0), reset=True)
    result = await engine.submit_order(_simple_vol_order())
    assert result["success"] is True
    assert result["broker_place_order"] is False
    assert result["path"] == "paper_sim"
    position_id = result["position"]["position_id"]

    # Move marks and refresh MTM
    feed = engine.feed
    assert isinstance(feed, FakeFeed)
    feed.ltps["40123"] = 15.0
    feed.ltps["40124"] = 10.0
    refreshed = await engine.refresh_marks()
    assert refreshed["marks_updated"] == 2
    upnl = refreshed["account"]["unrealized_pnl"]
    # Open @ 12/11; mark @ 15/10 → CE +3*25 + PE -1*25 = 75 - 25 = 50
    assert upnl == pytest.approx(50.0)

    closed = await engine.close_position(position_id)
    assert closed["broker_place_order"] is False
    assert closed["realized_pnl"] == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_engine_rejects_reset_with_open_positions():
    engine = get_paper_engine(feed=FakeFeed(), config=PaperSimConfig(slippage_bps=0), reset=True)
    await engine.submit_order(_simple_vol_order())
    with pytest.raises(PaperLedgerError, match="cannot reset"):
        engine.reset()


@pytest.mark.asyncio
async def test_engine_rejects_index_underlying():
    """Index underlyings are rejected only when the order includes cash/stock legs (T11)."""
    engine = get_paper_engine(feed=FakeFeed(), config=PaperSimConfig(slippage_bps=0), reset=True)
    with pytest.raises(PaperLedgerError, match="index"):
        await engine.submit_order(
            PaperOrderRequest(
                strategy_tag="simple_vol",
                underlying="NIFTY",
                legs=[
                    PaperLegRequest(
                        symbol="SBIN28MAR24500CE",
                        side=PaperSide.buy,
                        quantity=25,
                        exchange="NFO",
                        symbol_token="40123",
                    ),
                    PaperLegRequest(
                        symbol="NIFTY",
                        side=PaperSide.buy,
                        quantity=1,
                        exchange="NSE",
                    ),
                ],
            )
        )


@pytest.mark.asyncio
async def test_engine_rejects_spot_above_cap_with_stock_leg():
    engine = get_paper_engine(feed=FakeFeed(), config=PaperSimConfig(slippage_bps=0), reset=True)
    with pytest.raises(PaperLedgerError, match="Part T cap"):
        await engine.submit_order(
            PaperOrderRequest(
                strategy_tag="gamma_scalping",
                underlying="INFY",
                legs=[
                    PaperLegRequest(
                        symbol="SBIN28MAR24500CE",
                        side=PaperSide.buy,
                        quantity=25,
                        exchange="NFO",
                        symbol_token="40123",
                    ),
                    PaperLegRequest(
                        symbol="INFY",
                        side=PaperSide.buy,
                        quantity=1,
                        exchange="NSE",
                        symbol_token="1594",
                    ),
                ],
            )
        )


@pytest.mark.asyncio
async def test_engine_allows_stock_leg_under_cap():
    engine = get_paper_engine(feed=FakeFeed(), config=PaperSimConfig(slippage_bps=0), reset=True)
    result = await engine.submit_order(
        PaperOrderRequest(
            strategy_tag="gamma_scalping",
            underlying="SBIN",
            legs=[
                PaperLegRequest(
                    symbol="SBIN28MAR24500CE",
                    side=PaperSide.buy,
                    quantity=25,
                    exchange="NFO",
                    symbol_token="40123",
                ),
                PaperLegRequest(
                    symbol="SBIN",
                    side=PaperSide.buy,
                    quantity=1,
                    exchange="NSE",
                    symbol_token="3045",
                ),
            ],
        )
    )
    assert result["success"] is True
    assert len(result["fills"]) == 2


@pytest.mark.asyncio
async def test_option_chain_from_fake_feed():
    engine = PaperEngine(config=PaperSimConfig(), feed=FakeFeed())
    chain = await engine.option_chain(underlying="SBIN", include_ltp=True)
    assert chain["underlying"] == "SBIN"
    assert chain["source"] == "icici_direct_scrip_master"
    assert chain["marks_fresh"] is True
    assert chain["spot_ltp"] == pytest.approx(750.0)
    assert len(chain["contracts"]) >= 2


@pytest.mark.asyncio
async def test_fresh_marks_gate_rejects_stale_tick():
    """MD-01: age > option_stale_threshold_sec blocks the whole paper basket."""
    feed = FakeFeed()
    feed.age_sec["40123"] = 500.0  # > 120s option threshold
    engine = get_paper_engine(
        feed=feed,
        config=PaperSimConfig(slippage_bps=0, option_stale_threshold_sec=120),
        reset=True,
    )
    from backend.paper_sim.freshness import StaleMarksError

    with pytest.raises(StaleMarksError, match="fresh marks gate"):
        await engine.submit_order(_simple_vol_order())


@pytest.mark.asyncio
async def test_fresh_marks_gate_rejects_flagged_stale():
    feed = FakeFeed()
    feed.stale_tokens.add("40124")
    engine = get_paper_engine(feed=feed, config=PaperSimConfig(slippage_bps=0), reset=True)
    from backend.paper_sim.freshness import StaleMarksError

    with pytest.raises(StaleMarksError, match="tick_flagged_stale"):
        await engine.submit_order(_simple_vol_order())


@pytest.mark.asyncio
async def test_fresh_marks_gate_rejects_missing_ltp():
    """PS-03: multi-leg with missing LTP on one leg rejects the whole basket."""
    feed = FakeFeed()
    feed.ltps["40123"] = 0.0
    engine = get_paper_engine(feed=feed, config=PaperSimConfig(slippage_bps=0), reset=True)
    from backend.paper_sim.freshness import StaleMarksError

    with pytest.raises(StaleMarksError, match="missing_or_invalid_ltp"):
        await engine.submit_order(_simple_vol_order())


@pytest.mark.asyncio
async def test_fresh_marks_gate_allows_fresh_ticks():
    feed = FakeFeed()
    engine = get_paper_engine(
        feed=feed,
        config=PaperSimConfig(slippage_bps=0, option_stale_threshold_sec=120),
        reset=True,
    )
    result = await engine.submit_order(_simple_vol_order())
    assert result["success"] is True
    assert result["marks_freshness"]["ok"] is True
    assert result["broker_place_order"] is False


@pytest.mark.asyncio
async def test_refresh_marks_blocked_when_stale():
    feed = FakeFeed()
    engine = get_paper_engine(feed=feed, config=PaperSimConfig(slippage_bps=0), reset=True)
    await engine.submit_order(_simple_vol_order())
    feed.age_sec["40123"] = 999.0
    from backend.paper_sim.freshness import StaleMarksError

    with pytest.raises(StaleMarksError, match="fresh marks gate"):
        await engine.refresh_marks()


def test_http_ledger_pnl_lifecycle(monkeypatch):
    """Phase 1.1 evidence: account / positions / fills / multi-leg / close update local P&L."""
    monkeypatch.setenv("EXECUTION_MODE", "paper")
    monkeypatch.delenv("ALLOW_LIVE_PLACE_ORDER", raising=False)

    feed = FakeFeed()
    engine = get_paper_engine(feed=feed, config=PaperSimConfig(slippage_bps=0), reset=True)
    from backend.main import app

    client = TestClient(app)

    health = client.get("/api/v1/paper-sim/health")
    assert health.status_code == 200
    health_body = health.json()
    assert health_body["phase"] == "1.10"
    assert health_body["status"] == "ready"
    assert health_body["broker_place_order"] is False
    assert health_body["capabilities"]["multi_leg_orders"] is True
    assert health_body["capabilities"]["fresh_marks_gate"] is True
    assert health_body["capabilities"]["option_chain_scrip_master"] is True
    assert health_body["capabilities"]["market_news"] is True
    assert "dominant_tone" in health_body["market_news"]

    account0 = client.get("/api/v1/paper-sim/account").json()
    assert account0["cash_inr"] == pytest.approx(1_000_000.0)
    assert account0["open_positions"] == 0

    # Multi-leg simple_vol (long ATM CE + PE) — playbook shape, not a named structure
    opened = client.post(
        "/api/v1/paper-sim/orders",
        json={
            "strategy_tag": "simple_vol",
            "underlying": "SBIN",
            "legs": [
                {
                    "symbol": "SBIN28MAR24500CE",
                    "side": "buy",
                    "quantity": 25,
                    "exchange": "NFO",
                    "symbol_token": "40123",
                },
                {
                    "symbol": "SBIN28MAR24500PE",
                    "side": "buy",
                    "quantity": 25,
                    "exchange": "NFO",
                    "symbol_token": "40124",
                },
            ],
        },
    )
    assert opened.status_code == 200, opened.text
    open_body = opened.json()
    assert open_body["broker_place_order"] is False
    assert open_body["path"] == "paper_sim"
    assert open_body["marks_freshness"]["ok"] is True
    position_id = open_body["position"]["position_id"]
    debit = 12.0 * 25 + 11.0 * 25
    assert open_body["account"]["cash_inr"] == pytest.approx(1_000_000.0 - debit)
    assert open_body["account"]["open_positions"] == 1

    positions = client.get("/api/v1/paper-sim/positions").json()
    assert len(positions["positions"]) == 1
    assert positions["positions"][0]["position_id"] == position_id
    assert len(positions["positions"][0]["legs"]) == 2

    fills = client.get("/api/v1/paper-sim/fills").json()
    assert len(fills["fills"]) == 2

    blocked_reset = client.post("/api/v1/paper-sim/reset")
    assert blocked_reset.status_code == 400

    feed.ltps["40123"] = 15.0
    feed.ltps["40124"] = 10.0
    refreshed = client.post("/api/v1/paper-sim/marks/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["account"]["unrealized_pnl"] == pytest.approx(50.0)
    assert refreshed.json()["marks_freshness"]["ok"] is True

    status = client.get("/api/v1/paper-sim/marks/status")
    assert status.status_code == 200
    assert status.json()["gate"] == "fresh_marks"
    assert status.json()["enabled"] is True

    chain = client.get("/api/v1/paper-sim/chain", params={"underlying": "SBIN", "include_ltp": True})
    assert chain.status_code == 200
    assert chain.json()["source"] == "icici_direct_scrip_master"

    # MD-01 via HTTP: stale mark → 409
    feed.age_sec["40123"] = 999.0
    stale_refresh = client.post("/api/v1/paper-sim/marks/refresh")
    assert stale_refresh.status_code == 409
    feed.age_sec.pop("40123", None)

    closed = client.post(f"/api/v1/paper-sim/positions/{position_id}/close")
    assert closed.status_code == 200, closed.text
    close_body = closed.json()
    assert close_body["realized_pnl"] == pytest.approx(50.0)
    assert close_body["account"]["open_positions"] == 0
    assert close_body["account"]["realized_pnl"] == pytest.approx(50.0)
    assert close_body["account"]["cash_inr"] == pytest.approx(1_000_000.0 + 50.0)

    account1 = client.get("/api/v1/paper-sim/account").json()
    assert account1["realized_pnl"] == pytest.approx(50.0)
    assert account1["unrealized_pnl"] == pytest.approx(0.0)

    reset = client.post("/api/v1/paper-sim/reset", json={"starting_capital_inr": 1_000_000})
    assert reset.status_code == 200
    assert reset.json()["cash_inr"] == pytest.approx(1_000_000.0)
    assert reset.json()["realized_pnl"] == pytest.approx(0.0)

    # Keep process singleton clean for other tests
    get_paper_engine(feed=FakeFeed(), config=PaperSimConfig(slippage_bps=0), reset=True)
    _ = engine  # silence unused in some linters
