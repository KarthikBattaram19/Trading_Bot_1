"""App lifespan: boot reconciliation + scheduler autostart (with-block TestClient)."""

from __future__ import annotations

from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import app


class _FakeScheduler:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    async def start(self):
        self.started += 1
        return {"state": "running"}

    async def stop(self):
        self.stopped += 1
        return {"state": "stopped"}


class _FakeAutomation:
    async def stop(self):
        return {"state": "stopped"}


def _patch_common(monkeypatch, scheduler: _FakeScheduler, reconciled: list) -> None:
    monkeypatch.setattr(
        main_module, "reconcile_open_trades", lambda: reconciled.append(True) or []
    )
    monkeypatch.setattr(main_module, "get_trading_scheduler", lambda: scheduler)
    monkeypatch.setattr(
        main_module,
        "get_paper_engine",
        lambda: type("E", (), {"automation": _FakeAutomation()})(),
    )


def test_lifespan_starts_scheduler_and_reconciles(monkeypatch) -> None:
    monkeypatch.delenv("SCHEDULER_AUTOSTART", raising=False)
    scheduler = _FakeScheduler()
    reconciled: list = []
    _patch_common(monkeypatch, scheduler, reconciled)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert reconciled == [True]
    assert scheduler.started == 1
    assert scheduler.stopped == 1


def test_scheduler_autostart_env_disable(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULER_AUTOSTART", "0")
    scheduler = _FakeScheduler()
    reconciled: list = []
    _patch_common(monkeypatch, scheduler, reconciled)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert reconciled == [True]  # reconciliation always runs
    assert scheduler.started == 0


def test_reconciliation_failure_does_not_block_startup(monkeypatch) -> None:
    monkeypatch.delenv("SCHEDULER_AUTOSTART", raising=False)
    scheduler = _FakeScheduler()

    def _boom():
        raise RuntimeError("store corrupt")

    monkeypatch.setattr(main_module, "reconcile_open_trades", _boom)
    monkeypatch.setattr(main_module, "get_trading_scheduler", lambda: scheduler)
    monkeypatch.setattr(
        main_module,
        "get_paper_engine",
        lambda: type("E", (), {"automation": _FakeAutomation()})(),
    )

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert scheduler.started == 1


def test_scheduler_status_route_registered(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULER_AUTOSTART", "0")
    scheduler = _FakeScheduler()
    _patch_common(monkeypatch, scheduler, [])

    with TestClient(app) as client:
        response = client.get("/api/v1/scheduler/status")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] in {"stopped", "running", "degraded"}
    assert "phase" in body
