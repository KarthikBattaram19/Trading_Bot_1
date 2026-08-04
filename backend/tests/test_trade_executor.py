from __future__ import annotations

import pytest

from backend.models.recommendations import (
    GateResult,
    HedgeInsight,
    InstrumentRecommendation,
    ParameterSnapshot,
    ScoreBreakdown,
    StrategySelectionLogic,
    StrategyType,
    TradeEconomicsInsight,
)
from backend.services import trade_executor
from backend.services.learning_service import LearningService


def _make_recommendation(rank: int, symbol: str = "NIFTY") -> InstrumentRecommendation:
    return InstrumentRecommendation(
        rank=rank,
        underlying_symbol=symbol,
        score=0.9,
        confidence=0.85,
        strategy=StrategySelectionLogic(
            selected_strategy=StrategyType.gamma_scalping,
            scenario_tag="test",
            cross_strategy_matrix_ref="SH-4",
            primary_signal="test",
        ),
        parameters=ParameterSnapshot(
            und_price=100.0,
            iv_annualized=0.2,
            garch_forecast=0.18,
            atm_premium_inr=50.0,
            volume=1000,
            open_interest=5000,
            spread_pct=1.0,
            dte=15,
        ),
        parameter_gates=[GateResult(gate_id="T1", label="test gate", passed=True)],
        market_summary="test",
        entry_rationale="test",
        complete_logic=["test"],
        score_breakdown=ScoreBreakdown(
            base=0.5, strategy_boost=0.2, liquidity_boost=0.1, spread_penalty=0.0, total=0.9
        ),
        hedge=HedgeInsight(method="test", greek_targets="test", structure_note="test"),
        economics=TradeEconomicsInsight(
            margin_estimate_inr=10000.0,
            atm_premium_inr=50.0,
            estimated_slippage_pct=0.5,
            net_edge_note="test",
        ),
        exit_plan="test",
        event_risks=[],
        failure_modes=[],
        why_this_rank="test",
    )


@pytest.fixture(autouse=True)
def _isolated_learning_service(tmp_path, monkeypatch):
    """Point trade_executor at a throwaway learning store, not the real one."""
    svc = LearningService(store_path=tmp_path / "learning_store.json")
    monkeypatch.setattr(trade_executor, "get_learning_service", lambda: svc)
    yield


async def test_default_never_simulates_rank_1_failure():
    """Production default: no injected failure, no env var read at all."""
    recs = [_make_recommendation(1), _make_recommendation(2)]
    result = await trade_executor.execute_autonomous_from_recommendations(recs)
    assert result.executed is True
    assert result.selected_rank == 1


async def test_env_var_no_longer_influences_behavior(monkeypatch):
    """SIMULATE_FIRST_RANK_FAILURE must be inert — the flag was removed, not just defaulted off."""
    monkeypatch.setenv("SIMULATE_FIRST_RANK_FAILURE", "true")
    recs = [_make_recommendation(1), _make_recommendation(2)]
    result = await trade_executor.execute_autonomous_from_recommendations(recs)
    assert result.executed is True
    assert result.selected_rank == 1


async def test_injected_failure_falls_through_to_rank_2():
    """Test-only DI path: rank 1 rejected, rank 2 opened instead."""
    recs = [_make_recommendation(1), _make_recommendation(2)]
    result = await trade_executor.execute_autonomous_from_recommendations(
        recs, simulate_first_rank_failure=True
    )
    assert result.executed is True
    assert result.selected_rank == 2
    assert result.attempts[0].success is False
    assert "Broker reject" in (result.attempts[0].error or "")


async def test_second_entry_blocked_while_one_trade_locked():
    """The circuit breaker (§11.4.1) rejects a new entry while one is open."""
    recs = [_make_recommendation(1)]
    first = await trade_executor.execute_autonomous_from_recommendations(recs)
    assert first.executed is True
    assert trade_executor.is_one_trade_locked() is True

    second = await trade_executor.execute_autonomous_from_recommendations(recs)
    assert second.executed is False
    assert "One-trade scope locked" in (second.attempts[0].error or "")


async def test_lock_survives_simulated_process_restart(tmp_path, monkeypatch):
    """
    Lock state must be re-derivable from the on-disk ledger alone — a fresh
    LearningService instance (standing in for a restarted process, since the
    fixture's monkeypatched getter is the only thing trade_executor reads)
    must see the same lock the original process set, per
    Docs/bot_health/BACKLOG.md P0.
    """
    store_path = tmp_path / "learning_store.json"
    svc = LearningService(store_path=store_path)
    monkeypatch.setattr(trade_executor, "get_learning_service", lambda: svc)

    recs = [_make_recommendation(1)]
    result = await trade_executor.execute_autonomous_from_recommendations(recs)
    assert result.executed is True
    trade_id = result.trade_id

    # Simulate a restart: brand new service object reading the same file,
    # with no shared Python state from the process that opened the trade.
    restarted_svc = LearningService(store_path=store_path)
    monkeypatch.setattr(trade_executor, "get_learning_service", lambda: restarted_svc)

    assert trade_executor.is_one_trade_locked() is True
    assert trade_executor.get_active_trade_id() == trade_id


async def test_seeded_demo_open_trade_does_not_lock(tmp_path, monkeypatch):
    """The bundled demo fixture trade (trade_id 'trd_seed_...') must never
    block real autonomous entries — only genuine open trades count."""
    store_path = tmp_path / "learning_store.json"
    svc = LearningService(store_path=store_path)  # seeds a demo open trade
    monkeypatch.setattr(trade_executor, "get_learning_service", lambda: svc)

    seeded = svc.list_open_trades()
    assert any(t.trade_id.startswith("trd_seed") for t in seeded)

    assert trade_executor.is_one_trade_locked() is False
    assert trade_executor.get_active_trade_id() is None
