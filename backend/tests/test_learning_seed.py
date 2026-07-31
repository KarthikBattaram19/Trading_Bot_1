"""Learning store seed + migration — /learning must not stay empty on paper."""

from __future__ import annotations

import json
from pathlib import Path

from backend.services.learning_service import (
    SEED_VERSION,
    LearningService,
    _build_seeded_store,
    _empty_store,
    _seed_failure_memories,
)


def test_fresh_store_has_outcomes_and_open_trade(tmp_path: Path) -> None:
    path = tmp_path / "learning_store.json"
    svc = LearningService(store_path=path)
    dash = svc.dashboard()
    assert dash.closed_trade_count == 3
    assert dash.open_trade_count == 1
    assert dash.failure_memory_count == 3
    assert dash.win_rate == 0.0
    assert dash.total_pnl_inr < 0
    assert any(m.trade_count > 0 for m in dash.module_attribution)
    assert dash.open_trades[0].underlying_symbol == "HDFCBANK"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["seed_version"] == SEED_VERSION


def test_v1_store_migrates_without_wiping_failures(tmp_path: Path) -> None:
    path = tmp_path / "learning_store.json"
    v1 = _empty_store()
    v1["seed_version"] = 1
    v1["failure_memories"] = _seed_failure_memories("2026-01-01T00:00:00+00:00")
    v1["outcomes"] = []
    v1["open_trades"] = []
    path.write_text(json.dumps(v1), encoding="utf-8")

    svc = LearningService(store_path=path)
    dash = svc.dashboard()
    assert dash.closed_trade_count == 3
    assert dash.open_trade_count == 1
    assert dash.failure_memory_count == 3
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["seed_version"] == SEED_VERSION


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
