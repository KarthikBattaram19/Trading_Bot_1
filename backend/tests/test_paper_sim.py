"""Unit tests for in-house paper simulator (no live ICICI Direct calls)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
        }
        self.ltps = {"40123": 12.0, "40124": 11.0}

    async def ensure_instruments(self) -> int:
        return len(self.instruments)

    async def get_ltp(
        self,
        exchange: str,
        tradingsymbol: str,
        symboltoken: str | None = None,
    ) -> NormalizedTick:
        token = symboltoken
        if not token:
            for rec in self.instruments.values():
                if rec.tradingsymbol == tradingsymbol:
                    token = rec.symboltoken
                    break
        assert token is not None
        return NormalizedTick(
            exchange=exchange,
            symbol=tradingsymbol,
            provider_symbol_id=token,
            ltp=float(self.ltps[token]),
            ts=datetime.now(timezone.utc),
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
                    return rec
        return None

    def health(self) -> dict:
        return {"feed": "fake", "execution_coupled": False}


def test_fill_price_slippage():
    assert compute_fill_price(100.0, PaperSide.buy, 50) == pytest.approx(100.5)
    assert compute_fill_price(100.0, PaperSide.sell, 50) == pytest.approx(99.5)


def test_ledger_open_and_close_straddle():
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


@pytest.mark.asyncio
async def test_engine_submit_and_mtm_with_fake_feed():
    engine = get_paper_engine(feed=FakeFeed(), config=PaperSimConfig(slippage_bps=0), reset=True)
    result = await engine.submit_order(
        PaperOrderRequest(
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
    )
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
async def test_option_chain_from_fake_feed():
    engine = PaperEngine(config=PaperSimConfig(), feed=FakeFeed())
    chain = await engine.option_chain(underlying="SBIN", include_ltp=True)
    assert chain["underlying"] == "SBIN"
    assert chain["source"] == "icici_direct_data_only"
    assert len(chain["contracts"]) == 2
