from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.execution.options_only import OPTIONS_ONLY_REQUIRED
from backend.integrations.icici_direct.models import InstrumentRecord
from backend.paper_sim.config import PaperSimConfig
from backend.paper_sim.ledger import PaperLedgerError
from backend.paper_sim.models import PaperLegRequest, PaperOrderRequest, PaperSide
from backend.paper_sim.service import get_paper_engine
from backend.paper_sim.structure_builder import (
    _is_cash_leg,
    build_intended_legs_from_entry,
)
from backend.tests.test_paper_sim import FakeFeed


@pytest.mark.asyncio
async def test_open_rejects_cash_underlying_leg_with_options_only_code():
    engine = get_paper_engine(
        feed=FakeFeed(),
        config=PaperSimConfig(slippage_bps=0),
        reset=True,
    )

    with pytest.raises(PaperLedgerError, match=OPTIONS_ONLY_REQUIRED):
        await engine.submit_order(
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


@pytest.mark.asyncio
async def test_open_rejects_cash_symbol_token_even_when_exchange_mislabeled():
    engine = get_paper_engine(
        feed=FakeFeed(),
        config=PaperSimConfig(slippage_bps=0),
        reset=True,
    )

    with pytest.raises(PaperLedgerError, match=OPTIONS_ONLY_REQUIRED):
        await engine.submit_order(
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
                        exchange="NFO",
                        symbol_token="3045",
                    ),
                ],
            )
        )


@pytest.mark.asyncio
async def test_open_rejects_cash_equity_even_when_option_type_is_set():
    engine = get_paper_engine(
        feed=FakeFeed(),
        config=PaperSimConfig(slippage_bps=0),
        reset=True,
    )

    with pytest.raises(PaperLedgerError, match=OPTIONS_ONLY_REQUIRED):
        await engine.submit_order(
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
                        option_type="CE",
                    ),
                ],
            )
        )


def _single_ce_leg() -> list[PaperLegRequest]:
    return [
        PaperLegRequest(
            symbol="SBIN28MAR24500CE",
            side=PaperSide.buy,
            quantity=25,
            exchange="NFO",
            symbol_token="40123",
        )
    ]


@pytest.mark.asyncio
async def test_build_intended_legs_gamma_vega_never_include_cash():
    feed = FakeFeed()
    for tag in ("gamma_scalping", "vega_scalping"):
        intended = await build_intended_legs_from_entry(
            strategy_tag=tag,
            underlying="SBIN",
            entry_legs=_single_ce_leg(),
            feed=feed,
        )
        assert all(not _is_cash_leg(lg.exchange, lg.symbol) for lg in intended)
        assert all(lg.exchange.upper() == "NFO" for lg in intended)


def _relative_expiry(days_from_now: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=days_from_now)
    return dt.strftime("%d-%b-%Y")


class _GammaCalendarFeed(FakeFeed):
    """FakeFeed + a real near/far expiry pair for SBIN 500-strike options,
    so the gamma_scalping vega-solve path has real data to work with."""

    def __init__(self) -> None:
        super().__init__()
        near = _relative_expiry(30)
        far = _relative_expiry(30 + 30)
        # gamma_scalping is an ATM strategy (option_selection.moneyness: "atm").
        # The base FakeFeed's SBIN spot of 750 against these 500-strike legs is
        # deep ITM, whose near-leg vega rounds to ~0 — which now (correctly)
        # trips the degenerate-near-vega guard. Put spot at the strike so this
        # fixture exercises the real vega solve, not a degenerate one.
        self.ltps["3045"] = 500.0
        # Override the shared near-dated 500-strike CE/PE with a real DTE
        # (the base FakeFeed's literal "28MAR2024" doesn't parse as a real
        # date and is long past regardless).
        self.instruments["40123"] = self.instruments["40123"].model_copy(
            update={"expiry": near}
        )
        self.instruments["40124"] = self.instruments["40124"].model_copy(
            update={"expiry": near}
        )
        self.instruments["50001"] = InstrumentRecord(
            exchange="NFO",
            tradingsymbol="SBIN" + far.replace("-", "").upper() + "500CE",
            symboltoken="50001",
            name="SBIN",
            expiry=far,
            strike=500.0,
            lotsize=25,
            instrumenttype="OPTSTK",
        )
        self.instruments["50002"] = InstrumentRecord(
            exchange="NFO",
            tradingsymbol="SBIN" + far.replace("-", "").upper() + "500PE",
            symboltoken="50002",
            name="SBIN",
            expiry=far,
            strike=500.0,
            lotsize=25,
            instrumenttype="OPTSTK",
        )
        self.ltps["50001"] = 25.0
        self.ltps["50002"] = 24.0


@pytest.mark.asyncio
async def test_gamma_auto_complete_succeeds_with_nfo_legs_only():
    feed = _GammaCalendarFeed()
    engine = get_paper_engine(
        feed=feed,
        config=PaperSimConfig(slippage_bps=0),
        reset=True,
    )
    result = await engine.submit_order(
        PaperOrderRequest(
            strategy_tag="gamma_scalping",
            underlying="SBIN",
            auto_complete_multi_leg=True,
            legs=_single_ce_leg(),
        )
    )
    assert result["success"] is True
    completion = result["multi_leg_completion"]
    assert completion is not None
    assert completion["structure_complete"] is True
    position = result["position"]
    assert position["structure_complete"] is True
    assert len(position["legs"]) == 4
    for leg in position["legs"]:
        assert leg["exchange"] == "NFO"
    symbols = {leg["symbol"] for leg in position["legs"]}
    assert "SBIN" not in symbols
    sides = {leg["symbol"]: leg["side"] for leg in position["legs"]}
    near_legs = [s for s, side in sides.items() if s in {"SBIN28MAR24500CE", "SBIN28MAR24500PE"}]
    far_legs = [s for s in sides if s not in near_legs]
    assert len(near_legs) == 2
    assert all(sides[s] == "buy" for s in near_legs)
    assert len(far_legs) == 2
    assert all(sides[s] == "sell" for s in far_legs)


@pytest.mark.asyncio
async def test_vega_auto_complete_succeeds_with_straddle_nfo_only():
    feed = FakeFeed()
    engine = get_paper_engine(
        feed=feed,
        config=PaperSimConfig(slippage_bps=0),
        reset=True,
    )
    result = await engine.submit_order(
        PaperOrderRequest(
            strategy_tag="vega_scalping",
            underlying="SBIN",
            auto_complete_multi_leg=True,
            legs=_single_ce_leg(),
        )
    )
    assert result["success"] is True
    assert result["multi_leg_completion"]["structure_complete"] is True
    position = result["position"]
    assert len(position["legs"]) == 2
    symbols = {leg["symbol"] for leg in position["legs"]}
    assert symbols == {"SBIN28MAR24500CE", "SBIN28MAR24500PE"}
