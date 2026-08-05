"""Learning store — seed fixtures must never pollute §12 reporting metrics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.analytics.confidence_calibration import is_seed_outcome
from backend.models.learning import CloseTradeRequest, TradeOutcomeLabel
from backend.services.learning_service import (
    SEED_VERSION,
    LearningService,
    _build_seeded_store,
    _empty_store,
    _seed_failure_memories,
)


def test_fresh_store_dashboard_excludes_seed_metrics(tmp_path: Path) -> None:
    """Bundled demo fixtures may exist on disk, but /learning metrics stay empty."""
    path = tmp_path / "learning_store.json"
    svc = LearningService(store_path=path)
    dash = svc.dashboard()

    assert dash.closed_trade_count == 0
    assert dash.open_trade_count == 0
    assert dash.failure_memory_count == 0
    assert dash.win_rate is None
    assert dash.total_pnl_inr == 0.0
    assert dash.recent_outcomes == []
    assert dash.open_trades == []
    assert dash.failure_memories == []
    assert all(m.trade_count == 0 for m in dash.module_attribution)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["seed_version"] == SEED_VERSION
    # Fixtures may still be present for local UX / migration — just not reported.
    assert len(raw.get("outcomes") or []) == 3
    assert all(is_seed_outcome(o) for o in raw["outcomes"])


def test_seeded_failures_do_not_penalize_confidence(tmp_path: Path) -> None:
    path = tmp_path / "learning_store.json"
    svc = LearningService(store_path=path)
    matches = svc.retrieve_failure_matches(
        symbol="TATASTEEL",
        strategy="vega_scalping",
        entry_mode="standard",
        scenario_tag="Scenario A: Clean Intraday IV Flush",
    )
    assert matches == []


def test_v1_migration_still_backfills_fixtures_but_metrics_stay_clean(
    tmp_path: Path,
) -> None:
    path = tmp_path / "learning_store.json"
    v1 = _empty_store()
    v1["seed_version"] = 1
    v1["failure_memories"] = _seed_failure_memories("2026-01-01T00:00:00+00:00")
    v1["outcomes"] = []
    v1["open_trades"] = []
    path.write_text(json.dumps(v1), encoding="utf-8")

    svc = LearningService(store_path=path)
    dash = svc.dashboard()
    assert dash.closed_trade_count == 0
    assert dash.open_trade_count == 0
    assert dash.failure_memory_count == 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["seed_version"] == SEED_VERSION
    assert len(raw["outcomes"]) == 3


def test_real_outcomes_appear_in_dashboard_alongside_excluded_seeds(
    tmp_path: Path,
) -> None:
    path = tmp_path / "learning_store.json"
    store = _build_seeded_store()
    store["outcomes"].append(
        {
            "outcome_id": "out_real_001",
            "trade_id": "trd_real_001",
            "underlying_symbol": "SBIN",
            "rank": 1,
            "strategy": "simple_volatility",
            "entry_mode": "cheap_vol_mode",
            "scenario_tag": "Scenario A",
            "primary_signal": "IV < GARCH",
            "score_at_entry": 0.8,
            "confidence_at_entry": 0.8,
            "outcome": "win",
            "realized_pnl_inr": 1500.0,
            "exit_reason": "Target",
            "notes": None,
            "recommendation_snapshot": {},
            "opened_at": "2026-01-02T00:00:00+00:00",
            "closed_at": "2026-01-02T01:00:00+00:00",
            "failure_memory_id": None,
            "config_snapshot_id": "defaults",
        }
    )
    store["open_trades"] = []
    path.write_text(json.dumps(store), encoding="utf-8")

    svc = LearningService(store_path=path)
    dash = svc.dashboard()
    assert dash.closed_trade_count == 1
    assert dash.open_trade_count == 0
    assert dash.total_pnl_inr == 1500.0
    assert dash.win_rate == 1.0
    assert len(dash.recent_outcomes) == 1
    assert dash.recent_outcomes[0].trade_id == "trd_real_001"
    # Seeded failures remain on disk but are excluded from reporting.
    assert dash.failure_memory_count == 0


def test_operator_outcomes_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "learning_store.json"
    store = _build_seeded_store()
    store["seed_version"] = 1
    store["outcomes"] = [
        {
            "outcome_id": "out_real_001",
            "trade_id": "trd_real_001",
            "underlying_symbol": "SBIN",
            "rank": 1,
            "strategy": "simple_volatility",
            "entry_mode": "cheap_vol_mode",
            "scenario_tag": "Scenario A",
            "primary_signal": "IV < GARCH",
            "score_at_entry": 0.8,
            "confidence_at_entry": 0.8,
            "outcome": "win",
            "realized_pnl_inr": 1500.0,
            "exit_reason": "Target",
            "notes": None,
            "recommendation_snapshot": {},
            "opened_at": "2026-01-02T00:00:00+00:00",
            "closed_at": "2026-01-02T01:00:00+00:00",
            "failure_memory_id": None,
            "config_snapshot_id": "defaults",
        }
    ]
    store["open_trades"] = []
    path.write_text(json.dumps(store), encoding="utf-8")

    svc = LearningService(store_path=path)
    dash = svc.dashboard()
    assert dash.closed_trade_count == 1
    assert dash.open_trade_count == 0
    assert dash.total_pnl_inr == 1500.0
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["seed_version"] == SEED_VERSION
    assert raw["outcomes"][0]["trade_id"] == "trd_real_001"


def test_module_stats_ignore_seeds_when_updating_weights(tmp_path: Path) -> None:
    path = tmp_path / "learning_store.json"
    svc = LearningService(store_path=path)
    # Register + close three real losses so weight nudge can fire without seeds.
    from backend.tests.test_trade_executor import _make_recommendation

    for i in range(3):
        rec = _make_recommendation(1, symbol=f"SYM{i}")
        tid = f"trd_real_{i:03d}"
        svc.register_open_trade(tid, rec)
        svc.record_outcome(
            CloseTradeRequest(
                trade_id=tid,
                outcome=TradeOutcomeLabel.loss,
                realized_pnl_inr=-1000.0,
                exit_reason="test loss",
            )
        )
    dash = svc.dashboard()
    assert dash.closed_trade_count == 3
    assert dash.failure_memory_count == 3
    # Seeded module weights (0.90/0.92/0.95) must not dominate: only real outcomes count.
    gamma = next(m for m in dash.module_attribution if m.strategy == "gamma_scalping")
    assert gamma.trade_count == 3
    assert gamma.losses == 3


@pytest.mark.asyncio
async def test_paper_sim_close_feeds_learning_outcome(tmp_path: Path, monkeypatch) -> None:
    """Architecture §12.2 / §12.7 — ledger close is the learning input, not Mark Win/Loss."""
    from backend.paper_sim.engine import PaperEngine
    from backend.services import learning_service as learning_mod
    from backend.tests.test_trade_executor import _FakeFeed, _make_recommendation

    store_path = tmp_path / "learning_store.json"
    # Start from an empty (non-seeded) store so metrics are unambiguous.
    store_path.write_text(json.dumps(_empty_store()), encoding="utf-8")
    svc = LearningService(store_path=store_path)
    monkeypatch.setattr(learning_mod, "get_learning_service", lambda: svc)

    engine = PaperEngine(feed=_FakeFeed())
    from backend.services import trade_executor

    monkeypatch.setattr(trade_executor, "get_paper_engine", lambda: engine)
    monkeypatch.setattr(trade_executor, "get_learning_service", lambda: svc)

    result = await trade_executor.execute_autonomous_from_recommendations(
        [_make_recommendation(1, symbol="NIFTY")]
    )
    assert result.executed is True
    trade_id = result.trade_id
    assert trade_id
    assert svc.get_open_trade(trade_id) is not None

    closed = await engine.close_position(trade_id)
    assert closed["success"] is True

    dash = svc.dashboard()
    assert dash.open_trade_count == 0
    assert dash.closed_trade_count == 1
    assert dash.recent_outcomes[0].trade_id == trade_id
    assert dash.recent_outcomes[0].realized_pnl_inr == pytest.approx(
        float(closed["realized_pnl"])
    )
    assert svc.get_open_trade(trade_id) is None
