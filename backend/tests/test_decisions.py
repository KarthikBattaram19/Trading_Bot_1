from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.decisions import DecisionStatus
from backend.services import decision_log


@pytest.fixture
def client():
    return TestClient(app)


def _make_pending_decision(decision_id: str, symbol: str = "NIFTY"):
    from backend.tests.test_trade_executor import _make_recommendation

    rec = _make_recommendation(1, symbol=symbol)
    rec = rec.model_copy(
        update={"parameters": rec.parameters.model_copy(update={"und_price": 22010.0})}
    )
    return rec


async def test_approve_unknown_decision_returns_404(client, monkeypatch):
    async def _fake_list_decisions():
        return []

    monkeypatch.setattr(decision_log, "list_decisions", _fake_list_decisions)

    response = client.post("/api/v1/decisions/dec_unknown/approve")

    assert response.status_code == 404


async def test_reject_persists_without_executing(client, monkeypatch, tmp_path):
    from backend.services.decision_state import DecisionStateStore
    import backend.routers.decisions as decisions_router

    store = DecisionStateStore(store_path=tmp_path / "decision_state.json")
    monkeypatch.setattr(decisions_router, "get_decision_state_store", lambda: store)

    rec = _make_pending_decision("dec_nifty_test")
    decision = decision_log._to_decision(
        rec, decision_id="dec_nifty_test", status=DecisionStatus.pending,
        created_at=datetime.now(timezone.utc),
    )

    async def _fake_list_decisions():
        return [decision]

    monkeypatch.setattr(decision_log, "list_decisions", _fake_list_decisions)

    executed = {"called": False}

    async def _fake_execute(recs, **kwargs):
        executed["called"] = True
        raise AssertionError("reject must not execute")

    monkeypatch.setattr(decisions_router, "execute_autonomous_from_recommendations", _fake_execute)

    response = client.post(
        "/api/v1/decisions/dec_nifty_test/reject", json={"reason": "too risky"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert executed["called"] is False
    assert store.get("dec_nifty_test").status == "rejected"
    assert store.get("dec_nifty_test").reason == "too risky"


async def test_approve_on_already_acted_decision_returns_409(client, monkeypatch, tmp_path):
    from backend.services.decision_state import DecisionState, DecisionStateStore
    import backend.routers.decisions as decisions_router

    store = DecisionStateStore(store_path=tmp_path / "decision_state.json")
    store.set(
        "dec_nifty_test",
        DecisionState(status="rejected", trade_id=None, acted_at=datetime.now(timezone.utc)),
    )
    monkeypatch.setattr(decisions_router, "get_decision_state_store", lambda: store)

    rec = _make_pending_decision("dec_nifty_test")
    decision = decision_log._to_decision(
        rec, decision_id="dec_nifty_test", status=DecisionStatus.pending,
        created_at=datetime.now(timezone.utc),
    )

    async def _fake_list_decisions():
        return [decision]

    monkeypatch.setattr(decision_log, "list_decisions", _fake_list_decisions)

    response = client.post("/api/v1/decisions/dec_nifty_test/approve")

    assert response.status_code == 409


async def test_approve_happy_path_creates_real_position(client, monkeypatch, tmp_path):
    import backend.routers.decisions as decisions_router
    import backend.services.trade_executor as trade_executor
    from backend.paper_sim.engine import PaperEngine
    from backend.services.decision_state import DecisionStateStore
    from backend.services.learning_service import LearningService
    from backend.tests.test_trade_executor import _FakeFeed

    store = DecisionStateStore(store_path=tmp_path / "decision_state.json")
    monkeypatch.setattr(decisions_router, "get_decision_state_store", lambda: store)

    engine = PaperEngine(feed=_FakeFeed())
    monkeypatch.setattr(trade_executor, "get_paper_engine", lambda: engine)

    # Isolate from the real on-disk learning store (backend/data/learning_store.json)
    # the same way test_trade_executor.py's autouse fixture does — otherwise the
    # one-trade-scope lock reflects whatever real state happens to be on disk and
    # this test becomes order-dependent / flaky.
    learning_svc = LearningService(store_path=tmp_path / "learning_store.json")
    monkeypatch.setattr(trade_executor, "get_learning_service", lambda: learning_svc)

    rec = _make_pending_decision("dec_nifty_test")
    decision = decision_log._to_decision(
        rec, decision_id="dec_nifty_test", status=DecisionStatus.pending,
        created_at=datetime.now(timezone.utc),
    )

    async def _fake_list_decisions():
        return [decision]

    monkeypatch.setattr(decision_log, "list_decisions", _fake_list_decisions)

    class _Cached:
        generated_at = decision.created_at
        recommendations = [rec]

    monkeypatch.setattr(decisions_router, "peek_cached_recommendations", lambda: _Cached())

    response = client.post("/api/v1/decisions/dec_nifty_test/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["execution"]["executed"] is True
    trade_id = body["execution"]["trade_id"]
    assert trade_id in engine.ledger.positions
    assert store.get("dec_nifty_test").status == "approved"
