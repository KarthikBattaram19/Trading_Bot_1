"""TradingScheduler — phase-gated cycle driver + EOD flatten (fake clock, fake engine)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from backend.paper_sim.freshness import StaleMarksError
from backend.services import trading_scheduler as ts
from backend.services.market_session import IST


def _at(hh: int, mm: int) -> datetime:
    return datetime(2026, 8, 10, hh, mm, tzinfo=IST)  # Monday


class _FakeAutomation:
    def __init__(self) -> None:
        self.state = "stopped"
        self.start_calls = 0

    async def start(self):
        self.start_calls += 1
        self.state = "running"
        return {"state": self.state}


class _FakePosition(SimpleNamespace):
    pass


class _FakeEngine:
    def __init__(self, open_positions=None, close_errors=None) -> None:
        self.automation = _FakeAutomation()
        self._open = list(open_positions or [])
        self.close_calls: list[str] = []
        self._close_errors = list(close_errors or [])

    def positions(self, *, status="open"):
        return list(self._open)

    async def close_position(self, position_id: str):
        self.close_calls.append(position_id)
        if self._close_errors:
            raise self._close_errors.pop(0)
        self._open = [p for p in self._open if p.position_id != position_id]
        return {"position_id": position_id, "realized_pnl": 42.0}


@pytest.fixture()
def scheduler(monkeypatch):
    engine = _FakeEngine()
    generations: list[datetime] = []

    async def _fake_cycle(*, force_refresh=False):
        generations.append(datetime.now())
        return SimpleNamespace(
            recommendations=[],
            autonomous_execution=SimpleNamespace(executed=False, message="test"),
        )

    monkeypatch.setattr(ts, "get_paper_engine", lambda: engine)
    monkeypatch.setattr(ts, "run_recommendation_cycle", _fake_cycle)
    monkeypatch.setattr(ts, "is_one_trade_locked", lambda: False)
    sched = ts.TradingScheduler()
    sched._test_engine = engine  # convenience handle for assertions
    sched._test_generations = generations
    return sched


async def test_idle_outside_market_hours(scheduler) -> None:
    result = await scheduler.tick(now=_at(2, 0))
    assert result["phase"] == "closed"
    assert scheduler._test_engine.automation.start_calls == 0
    assert scheduler._test_generations == []


async def test_idle_pre_open(scheduler) -> None:
    result = await scheduler.tick(now=_at(9, 16))
    assert result["phase"] == "pre_open"
    assert scheduler._test_engine.automation.start_calls == 0
    assert scheduler._test_generations == []


async def test_entry_phase_starts_automation_and_generates(scheduler) -> None:
    result = await scheduler.tick(now=_at(9, 25))
    assert result["phase"] == "entry"
    assert scheduler._test_engine.automation.state == "running"
    assert len(scheduler._test_generations) == 1


async def test_generation_respects_cadence(scheduler) -> None:
    await scheduler.tick(now=_at(9, 25))
    await scheduler.tick(now=_at(9, 26))  # within 600s cadence
    assert len(scheduler._test_generations) == 1
    await scheduler.tick(now=_at(9, 36))  # past cadence
    assert len(scheduler._test_generations) == 2


async def test_generation_skipped_when_one_trade_locked(scheduler, monkeypatch) -> None:
    monkeypatch.setattr(ts, "is_one_trade_locked", lambda: True)
    result = await scheduler.tick(now=_at(9, 25))
    assert result["phase"] == "entry"
    assert scheduler._test_generations == []
    # automation still ensured — an open position needs marks/re-hedge
    assert scheduler._test_engine.automation.state == "running"


async def test_no_entry_phase_keeps_automation_but_stops_generation(scheduler) -> None:
    result = await scheduler.tick(now=_at(14, 45))
    assert result["phase"] == "no_entry"
    assert scheduler._test_engine.automation.state == "running"
    assert scheduler._test_generations == []


async def test_flatten_closes_open_positions(scheduler, monkeypatch) -> None:
    engine = _FakeEngine(open_positions=[_FakePosition(position_id="pos_x", status="open")])
    monkeypatch.setattr(ts, "get_paper_engine", lambda: engine)

    result = await scheduler.tick(now=_at(15, 16))

    assert result["phase"] == "flatten"
    assert engine.close_calls == ["pos_x"]
    assert scheduler.status()["flatten_closed"] == 1


async def test_flatten_retries_on_stale_marks(scheduler, monkeypatch) -> None:
    engine = _FakeEngine(
        open_positions=[_FakePosition(position_id="pos_x", status="open")],
        close_errors=[StaleMarksError("marks stale")],
    )
    monkeypatch.setattr(ts, "get_paper_engine", lambda: engine)

    await scheduler.tick(now=_at(15, 16))  # fails
    assert scheduler.status()["flatten_closed"] == 0
    assert scheduler.status()["flatten_attempts"] == 1

    await scheduler.tick(now=_at(15, 17))  # retry succeeds
    assert engine.close_calls == ["pos_x", "pos_x"]
    assert scheduler.status()["flatten_closed"] == 1


async def test_status_payload_shape(scheduler) -> None:
    await scheduler.tick(now=_at(9, 25))
    status = scheduler.status()
    for key in (
        "state",
        "phase",
        "ticks",
        "generations",
        "last_generation_at",
        "flatten_attempts",
        "flatten_closed",
        "last_error",
        "last_actions",
        "config",
    ):
        assert key in status
    assert status["ticks"] == 1
    assert status["generations"] == 1
