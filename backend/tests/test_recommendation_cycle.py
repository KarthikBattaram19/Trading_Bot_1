"""Supervision-gated autonomous cycle — service-level tests.

Moved from test_recommendations_router.py when the cycle logic was extracted
out of the router into backend/services/recommendation_cycle.py so the
trading scheduler can drive it without importing a router.
"""

from __future__ import annotations

from backend.routers import recommendations as recommendations_router
from backend.services import recommendation_cycle


class _StubResponse:
    def __init__(self, recs):
        self.recommendations = recs

    def model_copy(self, *, update):
        merged = dict(self.__dict__)
        merged.update(update)
        stub = _StubResponse(self.recommendations)
        stub.__dict__.update(merged)
        return stub


def _patch_generate(monkeypatch, recs):
    async def _fake_generate(*, force_refresh=False):
        return _StubResponse(recs)

    monkeypatch.setattr(recommendation_cycle, "generate_recommendations", _fake_generate)


async def test_supervised_mode_skips_autonomous_execution(monkeypatch):
    monkeypatch.setenv("SUPERVISION_MODE", "supervised")
    calls: list[object] = []

    async def _fake_execute(recs, **kwargs):
        calls.append(recs)
        raise AssertionError("must not execute in supervised mode")

    monkeypatch.setattr(
        recommendation_cycle, "execute_autonomous_from_recommendations", _fake_execute
    )
    _patch_generate(monkeypatch, [])

    result = await recommendation_cycle.run_recommendation_cycle(force_refresh=True)

    assert calls == []
    assert result.autonomous_execution.executed is False
    assert "supervision" in result.autonomous_execution.message.lower()


async def test_fully_autonomous_mode_still_executes(monkeypatch):
    monkeypatch.setenv("SUPERVISION_MODE", "fully_autonomous")
    calls: list[object] = []

    async def _fake_execute(recs, **kwargs):
        calls.append(recs)
        from backend.models.trades import AutonomousExecutionResult

        return AutonomousExecutionResult(executed=True, attempts=[], message="ok")

    monkeypatch.setattr(
        recommendation_cycle, "execute_autonomous_from_recommendations", _fake_execute
    )
    _patch_generate(monkeypatch, [object()])

    result = await recommendation_cycle.run_recommendation_cycle(force_refresh=True)

    assert len(calls) == 1
    assert result.autonomous_execution.executed is True


async def test_semi_autonomous_mode_skips_autonomous_execution(monkeypatch):
    monkeypatch.setenv("SUPERVISION_MODE", "semi_autonomous")
    calls: list[object] = []

    async def _fake_execute(recs, **kwargs):
        calls.append(recs)
        raise AssertionError("must not execute in semi_autonomous mode")

    monkeypatch.setattr(
        recommendation_cycle, "execute_autonomous_from_recommendations", _fake_execute
    )
    _patch_generate(monkeypatch, [])

    result = await recommendation_cycle.run_recommendation_cycle(force_refresh=True)

    assert calls == []
    assert result.autonomous_execution.executed is False
    assert "supervision" in result.autonomous_execution.message.lower()


async def test_blank_or_unset_supervision_mode_skips_autonomous_execution(monkeypatch):
    monkeypatch.setenv("SUPERVISION_MODE", "")
    calls: list[object] = []

    async def _fake_execute(recs, **kwargs):
        calls.append(recs)
        raise AssertionError("must not execute with a blank supervision mode")

    monkeypatch.setattr(
        recommendation_cycle, "execute_autonomous_from_recommendations", _fake_execute
    )
    _patch_generate(monkeypatch, [])

    result = await recommendation_cycle.run_recommendation_cycle(force_refresh=True)

    assert calls == []
    assert result.autonomous_execution.executed is False
    assert "supervision" in result.autonomous_execution.message.lower()


async def test_one_trade_lock_blocks_fully_autonomous_execution(monkeypatch):
    monkeypatch.setenv("SUPERVISION_MODE", "fully_autonomous")
    calls: list[object] = []

    async def _fake_execute(recs, **kwargs):
        calls.append(recs)
        raise AssertionError("must not execute while one-trade locked")

    monkeypatch.setattr(
        recommendation_cycle, "execute_autonomous_from_recommendations", _fake_execute
    )
    monkeypatch.setattr(recommendation_cycle, "is_one_trade_locked", lambda: True)
    _patch_generate(monkeypatch, [object()])

    result = await recommendation_cycle.run_recommendation_cycle(force_refresh=True)

    assert calls == []
    assert result.autonomous_execution.executed is False
    assert "lock" in result.autonomous_execution.message.lower()


class _FakeRec:
    """Minimal recommendation stand-in with a `.rank` so a pre-fix router
    that reaches the real (ungated) executor fails on the actual assertion
    below rather than crashing on `sorted(..., key=lambda r: r.rank)` —
    that crash was accidental bypass evidence, not the intended one."""

    rank = 1


def _patch_router_generate(monkeypatch, recs):
    async def _fake_generate(*, force_refresh=False):
        return _StubResponse(recs)

    monkeypatch.setattr(recommendations_router, "generate_recommendations", _fake_generate)


async def test_execute_autonomous_endpoint_respects_supervised_gate(monkeypatch):
    """POST /recommendations/execute-autonomous must not bypass the same
    SUPERVISION_MODE gate that a fresh GET /recommendations?refresh=true
    cycle enforces via autonomous_execution_for."""
    monkeypatch.setenv("SUPERVISION_MODE", "supervised")
    calls: list[object] = []

    async def _fake_execute(recs, **kwargs):
        calls.append(recs)
        raise AssertionError("must not execute in supervised mode")

    monkeypatch.setattr(
        recommendation_cycle, "execute_autonomous_from_recommendations", _fake_execute
    )
    _patch_router_generate(monkeypatch, [_FakeRec()])

    result = await recommendations_router.execute_autonomous_trade()
    body = result.body

    assert calls == []
    import json

    payload = json.loads(body)
    assert payload["executed"] is False
    assert "supervision" in payload["message"].lower()


async def test_execute_autonomous_endpoint_fails_closed_on_blank_mode(monkeypatch):
    monkeypatch.setenv("SUPERVISION_MODE", "")
    calls: list[object] = []

    async def _fake_execute(recs, **kwargs):
        calls.append(recs)
        raise AssertionError("must not execute with a blank supervision mode")

    monkeypatch.setattr(
        recommendation_cycle, "execute_autonomous_from_recommendations", _fake_execute
    )
    _patch_router_generate(monkeypatch, [_FakeRec()])

    result = await recommendations_router.execute_autonomous_trade()
    import json

    payload = json.loads(result.body)

    assert calls == []
    assert payload["executed"] is False
    assert "supervision" in payload["message"].lower()


async def test_execute_autonomous_endpoint_still_executes_fully_autonomous(monkeypatch):
    monkeypatch.setenv("SUPERVISION_MODE", "fully_autonomous")
    calls: list[object] = []

    async def _fake_execute(recs, **kwargs):
        calls.append(recs)
        from backend.models.trades import AutonomousExecutionResult

        return AutonomousExecutionResult(executed=True, attempts=[], message="ok")

    monkeypatch.setattr(
        recommendation_cycle, "execute_autonomous_from_recommendations", _fake_execute
    )
    monkeypatch.setattr(recommendation_cycle, "is_one_trade_locked", lambda: False)
    _patch_router_generate(monkeypatch, [_FakeRec()])

    result = await recommendations_router.execute_autonomous_trade()
    import json

    payload = json.loads(result.body)

    assert len(calls) == 1
    assert payload["executed"] is True
