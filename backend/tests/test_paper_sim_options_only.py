from __future__ import annotations

import pytest

from backend.execution.options_only import OPTIONS_ONLY_REQUIRED
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


def test_build_intended_legs_gamma_vega_never_include_cash():
    feed = FakeFeed()
    for tag in ("gamma_scalping", "vega_scalping"):
        intended = build_intended_legs_from_entry(
            strategy_tag=tag,
            underlying="SBIN",
            entry_legs=_single_ce_leg(),
            feed=feed,
        )
        assert all(not _is_cash_leg(lg.exchange, lg.symbol) for lg in intended)
        assert all(lg.exchange.upper() == "NFO" for lg in intended)


@pytest.mark.asyncio
async def test_gamma_auto_complete_succeeds_with_nfo_legs_only():
    feed = FakeFeed()
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
