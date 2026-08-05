from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from backend.integrations.icici_direct.models import InstrumentRecord, NormalizedTick
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
from backend.paper_sim.engine import PaperEngine
from backend.paper_sim.models import PaperSide
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
            und_price=22010.0,
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


class _FakeFeed:
    """Minimal MarketQuoteFeed double: one NIFTY expiry, two strikes, CE+PE each."""

    def __init__(self) -> None:
        self.expiry = (datetime.now(timezone.utc) + timedelta(days=17)).strftime("%d-%b-%Y")
        self.instruments: dict[str, InstrumentRecord] = {
            "1": InstrumentRecord(
                exchange="NFO", tradingsymbol=f"NIFTY{self.expiry.upper()}22000CE",
                symboltoken="1", name="NIFTY", expiry=self.expiry, strike=22000.0,
                lotsize=50, instrumenttype="OPTIDX",
            ),
            "2": InstrumentRecord(
                exchange="NFO", tradingsymbol=f"NIFTY{self.expiry.upper()}22000PE",
                symboltoken="2", name="NIFTY", expiry=self.expiry, strike=22000.0,
                lotsize=50, instrumenttype="OPTIDX",
            ),
            "3": InstrumentRecord(
                exchange="NFO", tradingsymbol=f"NIFTY{self.expiry.upper()}22050CE",
                symboltoken="3", name="NIFTY", expiry=self.expiry, strike=22050.0,
                lotsize=50, instrumenttype="OPTIDX",
            ),
            "4": InstrumentRecord(
                exchange="NFO", tradingsymbol=f"NIFTY{self.expiry.upper()}22050PE",
                symboltoken="4", name="NIFTY", expiry=self.expiry, strike=22050.0,
                lotsize=50, instrumenttype="OPTIDX",
            ),
        }
        self.ltps = {"1": 120.0, "2": 110.0, "3": 100.0, "4": 130.0}
        self.instruments_loaded_at = datetime.now(timezone.utc)

    async def ensure_instruments(self, *, max_age_sec: float | None = None) -> int:
        return len(self.instruments)

    async def get_ltp(self, exchange, tradingsymbol, symboltoken=None) -> NormalizedTick:
        token = symboltoken
        if not token:
            for rec in self.instruments.values():
                if rec.tradingsymbol == tradingsymbol:
                    token = rec.symboltoken
                    break
        return NormalizedTick(
            exchange=exchange, symbol=tradingsymbol, provider_symbol_id=token,
            ltp=float(self.ltps[token]), ts=datetime.now(timezone.utc), stale=False,
        )

    def list_options(self, *, name, exchange="NFO", expiry=None, limit=500):
        rows = [
            r for r in self.instruments.values()
            if (r.name or "").upper() == name.upper() and r.exchange.upper() == exchange.upper()
        ]
        if expiry:
            rows = [r for r in rows if r.expiry == expiry]
        return rows[:limit]

    def resolve(self, *, exchange=None, tradingsymbol=None, symboltoken=None):
        if symboltoken and symboltoken in self.instruments:
            return self.instruments[symboltoken]
        for rec in self.instruments.values():
            if tradingsymbol and rec.tradingsymbol == tradingsymbol:
                return rec
        return None


def _make_engine() -> PaperEngine:
    return PaperEngine(feed=_FakeFeed())


async def test_resolve_atm_ce_leg_picks_nearest_strike_to_und_price():
    engine = _make_engine()
    rec = _make_recommendation(1)  # default und_price=100.0 in existing fixture — override below
    rec = rec.model_copy(update={"parameters": rec.parameters.model_copy(update={"und_price": 22010.0})})

    leg = await trade_executor.resolve_atm_ce_leg(rec, engine=engine)

    assert leg is not None
    assert leg.symbol.endswith("22000CE")
    assert leg.side == PaperSide.buy
    assert leg.quantity == 50
    assert leg.option_type == "CE"


async def test_resolve_atm_ce_leg_returns_none_for_unknown_underlying():
    engine = _make_engine()
    rec = _make_recommendation(1, symbol="NOTAREALSYMBOL")

    leg = await trade_executor.resolve_atm_ce_leg(rec, engine=engine)

    assert leg is None


@pytest.fixture(autouse=True)
def _isolated_learning_service(tmp_path, monkeypatch):
    """Point trade_executor at throwaway learning + paper_sim stores, not the real ones."""
    svc = LearningService(store_path=tmp_path / "learning_store.json")
    monkeypatch.setattr(trade_executor, "get_learning_service", lambda: svc)
    engine = _make_engine()
    monkeypatch.setattr(trade_executor, "get_paper_engine", lambda: engine)
    yield engine


async def test_successful_execution_creates_a_real_paper_sim_position(_isolated_learning_service):
    engine = _isolated_learning_service
    rec = _make_recommendation(1)
    rec = rec.model_copy(update={"parameters": rec.parameters.model_copy(update={"und_price": 22010.0})})

    result = await trade_executor.execute_autonomous_from_recommendations([rec])

    assert result.executed is True
    assert result.trade_id.startswith("pos_")
    position = engine.ledger.positions[result.trade_id]
    assert position.status == "open"
    assert len(position.legs) >= 1


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
    import json

    store_path = tmp_path / "learning_store.json"
    svc = LearningService(store_path=store_path)  # seeds a demo open trade
    monkeypatch.setattr(trade_executor, "get_learning_service", lambda: svc)

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert any(
        str(t.get("trade_id", "")).startswith("trd_seed")
        for t in raw.get("open_trades", [])
    )
    # Public open-trade list excludes seeds so /learning Mark Win/Loss stays real.
    assert svc.list_open_trades() == []

    assert trade_executor.is_one_trade_locked() is False
    assert trade_executor.get_active_trade_id() is None
