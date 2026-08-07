"""Boot-time reconciliation: orphaned learning-store open trades vs paper_sim ledger.

The paper_sim ledger is in-memory; a process restart loses open positions
while learning_store.json still lists them open, leaving the one-trade lock
permanently engaged with no closeable position behind it. Reconciliation
closes such orphans at 0 PnL so the bot can trade again.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.services import trade_executor
from backend.services.ledger_reconciliation import reconcile_open_trades
from backend.services.learning_service import LearningService
from backend.tests.test_trade_executor import _make_recommendation


def _svc(tmp_path) -> LearningService:
    return LearningService(store_path=tmp_path / "learning_store.json")


def _engine_with_positions(positions: dict) -> SimpleNamespace:
    return SimpleNamespace(ledger=SimpleNamespace(positions=positions))


def test_orphan_open_trade_closed_zero_pnl_releases_lock(tmp_path, monkeypatch) -> None:
    svc = _svc(tmp_path)
    svc.register_open_trade("pos_dead00000001", _make_recommendation(1))
    monkeypatch.setattr(trade_executor, "get_learning_service", lambda: svc)
    assert trade_executor.is_one_trade_locked() is True

    reconciled = reconcile_open_trades(engine=_engine_with_positions({}), learning=svc)

    assert reconciled == ["pos_dead00000001"]
    assert trade_executor.is_one_trade_locked() is False
    outcomes = [o for o in svc._read()["outcomes"] if o.get("trade_id") == "pos_dead00000001"]
    assert len(outcomes) == 1
    assert outcomes[0]["realized_pnl_inr"] == 0.0
    assert outcomes[0]["exit_reason"] == "orphaned_by_restart"


def test_open_trade_with_live_position_untouched(tmp_path) -> None:
    svc = _svc(tmp_path)
    svc.register_open_trade("pos_live00000001", _make_recommendation(1))
    engine = _engine_with_positions(
        {"pos_live00000001": SimpleNamespace(status="open")}
    )

    reconciled = reconcile_open_trades(engine=engine, learning=svc)

    assert reconciled == []
    assert [t.trade_id for t in svc.list_open_trades()] == ["pos_live00000001"]


def test_closed_ledger_position_is_treated_as_orphan(tmp_path) -> None:
    svc = _svc(tmp_path)
    svc.register_open_trade("pos_done00000001", _make_recommendation(1))
    engine = _engine_with_positions(
        {"pos_done00000001": SimpleNamespace(status="closed")}
    )

    reconciled = reconcile_open_trades(engine=engine, learning=svc)

    assert reconciled == ["pos_done00000001"]


def test_seed_trades_ignored(tmp_path) -> None:
    svc = _svc(tmp_path)  # fresh store ships with trd_seed_open_hdfc_001

    reconciled = reconcile_open_trades(engine=_engine_with_positions({}), learning=svc)

    assert reconciled == []
    # Seed row must remain untouched in the raw store.
    raw_open = svc._read()["open_trades"]
    assert any(t["trade_id"].startswith("trd_seed") for t in raw_open)


def test_no_open_trades_is_a_noop(tmp_path) -> None:
    svc = _svc(tmp_path)
    store = svc._read()
    store["open_trades"] = []
    svc._write(store)

    assert reconcile_open_trades(engine=_engine_with_positions({}), learning=svc) == []
