from __future__ import annotations

import pytest

from backend.routers import recommendations as recommendations_router


class _StubResponse:
    def __init__(self, recs):
        self.recommendations = recs

    def model_copy(self, *, update):
        merged = dict(self.__dict__)
        merged.update(update)
        stub = _StubResponse(self.recommendations)
        stub.__dict__.update(merged)
        return stub


async def test_supervised_mode_skips_autonomous_execution(monkeypatch):
    monkeypatch.setenv("SUPERVISION_MODE", "supervised")
    calls: list[object] = []

    async def _fake_execute(recs, **kwargs):
        calls.append(recs)
        raise AssertionError("must not execute in supervised mode")

    monkeypatch.setattr(
        recommendations_router, "execute_autonomous_from_recommendations", _fake_execute
    )

    async def _fake_generate(*, force_refresh=False):
        return _StubResponse([])

    monkeypatch.setattr(recommendations_router, "generate_recommendations", _fake_generate)

    result = await recommendations_router._recommendations_with_autonomous_execution(
        force_refresh=True
    )

    assert calls == []
    assert result.autonomous_execution.executed is False
    assert "supervision" in result.autonomous_execution.message.lower()


async def test_autonomous_mode_still_executes(monkeypatch):
    monkeypatch.setenv("SUPERVISION_MODE", "autonomous")
    calls: list[object] = []

    async def _fake_execute(recs, **kwargs):
        calls.append(recs)
        from backend.models.trades import AutonomousExecutionResult

        return AutonomousExecutionResult(executed=True, attempts=[], message="ok")

    monkeypatch.setattr(
        recommendations_router, "execute_autonomous_from_recommendations", _fake_execute
    )

    async def _fake_generate(*, force_refresh=False):
        # Return stub with at least one recommendation so execute is called
        return _StubResponse([object()])

    monkeypatch.setattr(recommendations_router, "generate_recommendations", _fake_generate)

    result = await recommendations_router._recommendations_with_autonomous_execution(
        force_refresh=True
    )

    assert len(calls) == 1
    assert result.autonomous_execution.executed is True
