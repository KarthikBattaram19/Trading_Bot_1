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
from backend.paper_sim.models import PaperOrderRequest, PaperSide
from backend.services import trade_executor
from backend.services.learning_service import LearningService


@pytest.fixture(autouse=True)
def _reset_execution_lock():
    """
    `_execution_lock` binds to whatever event loop first contends on it; reset
    it per test so one test's loop doesn't leak into the next and raise
    "bound to a different event loop" (see
    trade_executor.reset_execution_lock_for_tests docstring).
    """
    trade_executor.reset_execution_lock_for_tests()
    yield


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


async def test_concurrent_executions_do_not_both_open_a_trade(monkeypatch):
    """
    Two overlapping callers (e.g. a scheduler tick and a concurrent HTTP
    request) must not both pass the one-trade lock check. Forces the
    interleave by making `_submit_via_paper_sim` await an event before
    returning, so both coroutines are guaranteed to be mid-submit at the
    same time — reproducing the read (`is_one_trade_locked`) ...
    yield (`await _submit_via_paper_sim`) ... write
    (`register_open_trade`) race described in
    Docs/architecture.md §20.4.11.
    """
    import asyncio

    release = asyncio.Event()
    entered = asyncio.Event()
    call_count = 0

    async def _slow_submit(rec, *, simulate_first_rank_failure=False):
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        return True, f"pos_concurrent_{call_count}", None

    monkeypatch.setattr(trade_executor, "_submit_via_paper_sim", _slow_submit)

    recs = [_make_recommendation(1)]

    async def _runner():
        return await trade_executor.execute_autonomous_from_recommendations(recs)

    task_a = asyncio.create_task(_runner())
    await entered.wait()  # task_a is now inside the submit, lock not yet taken
    task_b = asyncio.create_task(_runner())
    await asyncio.sleep(0)  # let task_b run up to its own submit/lock-check

    release.set()  # allow both submits to complete
    result_a, result_b = await asyncio.gather(task_a, task_b)

    results = [result_a, result_b]
    executed = [r for r in results if r.executed]
    rejected = [r for r in results if not r.executed]
    assert len(executed) == 1, (
        f"expected exactly one execution to succeed, got {len(executed)}: {results}"
    )
    assert len(rejected) == 1
    assert "One-trade scope locked" in (rejected[0].attempts[0].error or "")


async def test_execution_lock_acquire_times_out_instead_of_hanging(monkeypatch):
    """
    A waiter that can't get `_execution_lock` within the timeout must give up
    and return a normal not-executed result rather than block forever — this
    is what lets the scheduler's `_loop` keep advancing toward flatten even
    if the section under the lock (feed calls in `_submit_via_paper_sim`)
    stalls. Force the lock held by a task that never releases within the
    (monkeypatched-tiny) timeout, then assert the second caller returns its
    rejection instead of hanging.
    """
    import asyncio

    monkeypatch.setattr(trade_executor, "EXECUTION_LOCK_TIMEOUT_SEC", 0.05)

    holder_ready = asyncio.Event()

    async def _hold_lock_forever():
        async with trade_executor.acquire_execution_lock() as acquired:
            assert acquired is True
            holder_ready.set()
            # Never releases within the waiter's timeout — sleeps far longer
            # than the 0.05s timeout above, simulating a stalled feed call.
            await asyncio.sleep(10)

    holder_task = asyncio.create_task(_hold_lock_forever())
    await holder_ready.wait()

    recs = [_make_recommendation(1)]
    result = await asyncio.wait_for(
        trade_executor.execute_autonomous_from_recommendations(recs), timeout=5.0
    )

    assert result.executed is False
    assert "lock busy" in result.message.lower()
    assert result.attempts == []

    holder_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder_task


async def test_blocked_when_unregistered_paper_position_open(_isolated_learning_service):
    """
    The blind spot this fix closes: a position opened directly via
    POST /api/v1/paper-sim/orders (bypassing the autonomous executor) is
    never registered with LearningService.register_open_trade, so
    is_one_trade_locked() alone can't see it. execute_autonomous_from_recommendations
    must still refuse to open a second trade on top of it.
    """
    engine = _isolated_learning_service
    rec = _make_recommendation(1)
    rec = rec.model_copy(update={"parameters": rec.parameters.model_copy(update={"und_price": 22010.0})})

    leg = await trade_executor.resolve_atm_ce_leg(rec, engine=engine)
    request = PaperOrderRequest(
        strategy_tag=rec.strategy.selected_strategy.value,
        underlying=rec.underlying_symbol,
        legs=[leg],
        auto_complete_multi_leg=True,
    )
    await engine.submit_order(request)  # opened directly, never registered

    assert trade_executor.is_one_trade_locked() is False  # the blind spot
    assert trade_executor.has_open_paper_position() is True

    result = await trade_executor.execute_autonomous_from_recommendations([rec])

    assert result.executed is False
    error = result.attempts[0].error or ""
    assert "paper" in error.lower() and "position" in error.lower()
    assert "One-trade scope locked" not in error
    # Guards against the leak class where a stale/hoisted paper_position_open
    # value lets a later candidate pile a second position on top instead of
    # being rejected — exactly one position must remain open.
    assert len(engine.positions(status="open")) == 1


async def test_partial_open_from_multi_leg_completion_failure_blocks_next_candidate(
    _isolated_learning_service,
):
    """
    Regression for the hoisting bug: `PaperEngine.submit_order` is not
    atomic — it opens the ledger position *before* attempting
    `complete_multi_leg_structure`, which can raise `PaperLedgerError`
    (bad contract, lotsize, pre-trade gate, stale marks, investment cap).
    When rank 1's multi-leg completion fails that way, its position is
    still open and unregistered when rank 2 is evaluated. A
    `paper_position_open` value computed once before the candidate loop
    would still read `False` at that point (rank 1 hadn't opened anything
    when it was hoisted) and let rank 2 stack a second open position on
    top — defeating the one-trade-at-a-time invariant. Per-candidate
    evaluation must catch it: rank 2 gets rejected with the paper-position
    message, and exactly one position (rank 1's partial open) remains.
    """
    engine = _isolated_learning_service
    rec1 = _make_recommendation(1)
    rec1 = rec1.model_copy(update={"parameters": rec1.parameters.model_copy(update={"und_price": 22010.0})})
    rec2 = _make_recommendation(2)
    rec2 = rec2.model_copy(update={"parameters": rec2.parameters.model_copy(update={"und_price": 22010.0})})

    call_count = 0
    real_complete = engine.complete_multi_leg_structure

    async def _fail_first_completion(position_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise trade_executor.PaperLedgerError("simulated multi-leg completion failure")
        return await real_complete(position_id)

    import types

    engine.complete_multi_leg_structure = types.MethodType(
        lambda self, position_id: _fail_first_completion(position_id), engine
    )

    result = await trade_executor.execute_autonomous_from_recommendations([rec1, rec2])

    assert result.executed is False
    assert result.attempts[0].success is False
    assert "paper_sim reject" in (result.attempts[0].error or "")
    assert result.attempts[1].success is False
    error2 = result.attempts[1].error or ""
    assert "paper" in error2.lower() and "position" in error2.lower()

    open_positions = engine.positions(status="open")
    assert len(open_positions) == 1, (
        f"expected exactly one leaked open position from rank 1's partial "
        f"open, got {len(open_positions)}: {[p.position_id for p in open_positions]}"
    )


async def test_unregistered_paper_position_unblocks_after_close(_isolated_learning_service):
    """Once the unregistered direct position is closed, autonomous execution
    is permitted again — the new check must not stick open forever."""
    engine = _isolated_learning_service
    rec = _make_recommendation(1)
    rec = rec.model_copy(update={"parameters": rec.parameters.model_copy(update={"und_price": 22010.0})})

    leg = await trade_executor.resolve_atm_ce_leg(rec, engine=engine)
    request = PaperOrderRequest(
        strategy_tag=rec.strategy.selected_strategy.value,
        underlying=rec.underlying_symbol,
        legs=[leg],
        auto_complete_multi_leg=True,
    )
    direct_result = await engine.submit_order(request)
    direct_position_id = direct_result["position"]["position_id"]

    blocked = await trade_executor.execute_autonomous_from_recommendations([rec])
    assert blocked.executed is False

    await engine.close_position(direct_position_id)
    assert trade_executor.has_open_paper_position() is False

    result = await trade_executor.execute_autonomous_from_recommendations([rec])
    assert result.executed is True


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
