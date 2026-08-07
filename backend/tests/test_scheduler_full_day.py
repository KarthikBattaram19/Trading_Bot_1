"""Full-day integration: scheduler opens one trade and flattens it by close.

Simulates Monday 2026-08-10 with a fake clock and fake Breeze feed, driving
TradingScheduler.tick() through the whole session. Everything between the
stubbed recommendation generator and the learning store is REAL: supervision
gate, one-trade lock, trade_executor → PaperEngine.submit_order (multi-leg
expansion), and PaperEngine.close_position → LearningService ledger close.
"""

from __future__ import annotations

from datetime import datetime

from backend.paper_sim.engine import PaperEngine
from backend.paper_sim.freshness import StaleMarksError
from backend.services import learning_service as learning_service_module
from backend.services import recommendation_cycle, trade_executor
from backend.services import trading_scheduler as ts
from backend.services.learning_service import LearningService
from backend.services.market_session import IST
from backend.tests.test_trade_executor import _FakeFeed, _make_recommendation


def _at(hh: int, mm: int) -> datetime:
    return datetime(2026, 8, 10, hh, mm, tzinfo=IST)  # Monday


class _StubResponse:
    def __init__(self, recs):
        self.recommendations = recs

    def model_copy(self, *, update):
        stub = _StubResponse(self.recommendations)
        stub.__dict__.update({**self.__dict__, **update})
        return stub


class _StubAutomation:
    """Stands in for the γ–θ loop so the test spawns no background task."""

    def __init__(self) -> None:
        self.state = "stopped"

    async def start(self):
        self.state = "running"
        return {"state": self.state}


async def test_full_day_opens_and_flattens_one_trade(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISION_MODE", "fully_autonomous")

    svc = LearningService(store_path=tmp_path / "learning_store.json")
    engine = PaperEngine(feed=_FakeFeed())
    engine.automation = _StubAutomation()

    monkeypatch.setattr(trade_executor, "get_learning_service", lambda: svc)
    monkeypatch.setattr(trade_executor, "get_paper_engine", lambda: engine)
    monkeypatch.setattr(learning_service_module, "get_learning_service", lambda: svc)
    monkeypatch.setattr(ts, "get_paper_engine", lambda: engine)

    rec = _make_recommendation(1)

    async def _fake_generate(*, force_refresh=False):
        return _StubResponse([rec])

    monkeypatch.setattr(recommendation_cycle, "generate_recommendations", _fake_generate)

    # First flatten attempt hits stale marks; the retry uses the real close path.
    real_close = engine.close_position
    close_attempts = {"n": 0}

    async def _flaky_close(position_id: str):
        close_attempts["n"] += 1
        if close_attempts["n"] == 1:
            raise StaleMarksError("marks stale at the bell")
        return await real_close(position_id)

    monkeypatch.setattr(engine, "close_position", _flaky_close)

    scheduler = ts.TradingScheduler()

    # 08:00 — before open: nothing happens.
    assert (await scheduler.tick(now=_at(8, 0)))["action"] == "idle"
    # 09:16 — pre-open: still idle.
    assert (await scheduler.tick(now=_at(9, 16)))["action"] == "idle"

    # 09:25 — entry: automation ensured, cycle runs, trade opens autonomously.
    result = await scheduler.tick(now=_at(9, 25))
    assert result["action"] == "generated"
    assert result["executed"] is True
    assert engine.automation.state == "running"
    open_positions = engine.positions(status="open")
    assert len(open_positions) == 1
    trade_id = open_positions[0].position_id
    assert trade_executor.is_one_trade_locked() is True

    # 09:26 — within cadence: no second generation.
    assert (await scheduler.tick(now=_at(9, 26)))["reason"] == "one_trade_locked"
    # 10:00 — locked: still no new entry.
    assert (await scheduler.tick(now=_at(10, 0)))["reason"] == "one_trade_locked"
    assert len(engine.positions(status="open")) == 1

    # 14:45 — no-entry window: hold.
    assert (await scheduler.tick(now=_at(14, 45)))["action"] == "hold"

    # 15:16 — flatten: first close attempt fails on stale marks, is retried.
    result = await scheduler.tick(now=_at(15, 16))
    assert result["action"] == "flatten"
    assert result["failed"] == [trade_id]
    assert len(engine.positions(status="open")) == 1

    # 15:17 — retry succeeds through the real close path.
    result = await scheduler.tick(now=_at(15, 17))
    assert result["closed"] == [trade_id]
    assert engine.positions(status="open") == []
    assert engine.ledger.positions[trade_id].status == "closed"

    # The close fed the learning loop: one REAL (non-seed) outcome.
    assert svc.real_closed_trade_count() == 1
    outcome = [
        o for o in svc._read()["outcomes"] if o.get("trade_id") == trade_id
    ]
    assert len(outcome) == 1
    assert outcome[0]["exit_reason"] == "paper_sim close"

    # Dashboard reports it, and the one-trade lock is released for Tuesday.
    assert svc.dashboard().closed_trade_count == 1
    assert trade_executor.is_one_trade_locked() is False

    # From now on the bootstrap confidence floor reverts to the strict one.
    from backend.services import confidence_floor

    monkeypatch.setattr(confidence_floor, "get_learning_service", lambda: svc)
    monkeypatch.delenv("MIN_RECOMMENDATION_CONFIDENCE", raising=False)
    floor, source = confidence_floor.effective_min_confidence(
        {
            "execution_constraints": {
                "min_recommendation_confidence": 0.80,
                "bootstrap_min_confidence": 0.70,
            }
        }
    )
    assert (floor, source) == (0.80, "config")
