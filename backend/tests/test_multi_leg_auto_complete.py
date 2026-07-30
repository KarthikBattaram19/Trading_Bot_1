"""Phase 1: auto-complete intended multi-leg opening without operator consent."""

from __future__ import annotations

import pytest

from backend.paper_sim.config import PaperSimConfig
from backend.paper_sim.ledger import PaperLedgerError
from backend.paper_sim.models import PaperLegRequest, PaperOrderRequest, PaperSide
from backend.paper_sim.service import get_paper_engine
from backend.tests.test_paper_sim import FakeFeed


def _ce_only_order(**kwargs) -> PaperOrderRequest:
    return PaperOrderRequest(
        strategy_tag=kwargs.get("strategy_tag", "simple_vol"),
        underlying="SBIN",
        auto_complete_multi_leg=kwargs.get("auto_complete_multi_leg", True),
        intended_legs=kwargs.get("intended_legs"),
        legs=[
            PaperLegRequest(
                symbol="SBIN28MAR24500CE",
                side=PaperSide.buy,
                quantity=25,
                exchange="NFO",
                symbol_token="40123",
            )
        ],
    )


@pytest.mark.asyncio
async def test_auto_complete_simple_vol_adds_matching_pe_without_consent():
    feed = FakeFeed()
    engine = get_paper_engine(
        feed=feed, config=PaperSimConfig(slippage_bps=0), reset=True
    )
    result = await engine.submit_order(_ce_only_order())
    assert result["success"] is True
    assert result["operator_consent_required_for_completion"] is False
    completion = result["multi_leg_completion"]
    assert completion is not None
    assert completion["action"] == "complete_multi_leg"
    assert completion["operator_consent_required"] is False
    assert completion["structure_complete"] is True
    assert completion["added_legs"] == 1

    position = result["position"]
    symbols = {leg["symbol"] for leg in position["legs"]}
    assert "SBIN28MAR24500CE" in symbols
    assert "SBIN28MAR24500PE" in symbols
    assert position["structure_complete"] is True
    # Opening investment = CE 12*25 + PE 11*25
    assert position["opening_investment_inr"] == pytest.approx(12.0 * 25 + 11.0 * 25)


@pytest.mark.asyncio
async def test_auto_complete_respects_same_trade_cap_as_open():
    feed = FakeFeed()
    # Tiny trade cap so CE opens but PE completion must fail under same rules.
    engine = get_paper_engine(
        feed=feed,
        config=PaperSimConfig(
            slippage_bps=0,
            max_trade_investment_inr=320.0,  # CE alone = 300; PE would push over
            max_leg_investment_inr=100_000.0,
        ),
        reset=True,
    )
    with pytest.raises(PaperLedgerError, match="max_trade_investment"):
        await engine.submit_order(_ce_only_order())


@pytest.mark.asyncio
async def test_auto_complete_disabled_leaves_incomplete_structure():
    feed = FakeFeed()
    engine = get_paper_engine(
        feed=feed, config=PaperSimConfig(slippage_bps=0), reset=True
    )
    result = await engine.submit_order(
        _ce_only_order(auto_complete_multi_leg=False)
    )
    assert result["multi_leg_completion"] is None
    assert result["position"]["structure_complete"] is False
    assert len(result["position"]["legs"]) == 1


@pytest.mark.asyncio
async def test_explicit_intended_legs_used_for_completion():
    feed = FakeFeed()
    engine = get_paper_engine(
        feed=feed, config=PaperSimConfig(slippage_bps=0), reset=True
    )
    intended = [
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
    ]
    result = await engine.submit_order(
        _ce_only_order(intended_legs=intended, strategy_tag="simple_vol")
    )
    assert result["position"]["structure_complete"] is True
    assert len(result["position"]["legs"]) == 2


@pytest.mark.asyncio
async def test_full_basket_entry_marks_structure_complete_without_extra_completion():
    feed = FakeFeed()
    engine = get_paper_engine(
        feed=feed, config=PaperSimConfig(slippage_bps=0), reset=True
    )
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
    assert result["multi_leg_completion"] is None
    assert result["position"]["structure_complete"] is True
    assert len(result["position"]["legs"]) == 2


@pytest.mark.asyncio
async def test_automation_tick_completes_incomplete_multi_leg():
    feed = FakeFeed()
    engine = get_paper_engine(
        feed=feed, config=PaperSimConfig(slippage_bps=0), reset=True
    )
    opened = await engine.submit_order(
        _ce_only_order(auto_complete_multi_leg=False)
    )
    position_id = opened["position"]["position_id"]
    assert opened["position"]["structure_complete"] is False

    # Re-enable auto-complete on the open position for the automation path.
    pos = engine.ledger.positions[position_id]
    pos.auto_complete_multi_leg = True

    tick = await engine.automation.tick()
    actions = tick["actions"]
    assert any(a.get("action") == "multi_leg_auto_complete" for a in actions)
    assert engine.ledger.positions[position_id].structure_complete is True
    assert len(engine.ledger.positions[position_id].legs) == 2


@pytest.mark.asyncio
async def test_completion_rejects_stale_marks_same_as_open():
    feed = FakeFeed()
    engine = get_paper_engine(
        feed=feed, config=PaperSimConfig(slippage_bps=0), reset=True
    )
    opened = await engine.submit_order(
        _ce_only_order(auto_complete_multi_leg=False)
    )
    position_id = opened["position"]["position_id"]
    feed.stale_tokens.add("40124")
    from backend.paper_sim.freshness import StaleMarksError

    with pytest.raises(StaleMarksError):
        await engine.complete_multi_leg_structure(position_id, force=True)
