from __future__ import annotations

import pytest

from backend.execution.options_only import OPTIONS_ONLY_REQUIRED
from backend.paper_sim.config import PaperSimConfig
from backend.paper_sim.ledger import PaperLedgerError
from backend.paper_sim.models import PaperLegRequest, PaperOrderRequest, PaperSide
from backend.paper_sim.service import get_paper_engine
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
