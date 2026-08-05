from __future__ import annotations

from datetime import datetime, timezone

from backend.services.decision_state import DecisionState, DecisionStateStore


def test_set_then_get_round_trips(tmp_path):
    store = DecisionStateStore(store_path=tmp_path / "decision_state.json")
    state = DecisionState(
        status="approved", trade_id="pos_abc123", reason=None,
        acted_at=datetime.now(timezone.utc),
    )

    store.set("dec_nifty_20260804", state)
    loaded = store.get("dec_nifty_20260804")

    assert loaded is not None
    assert loaded.status == "approved"
    assert loaded.trade_id == "pos_abc123"


def test_get_unknown_decision_returns_none(tmp_path):
    store = DecisionStateStore(store_path=tmp_path / "decision_state.json")
    assert store.get("dec_unknown") is None


def test_state_survives_simulated_process_restart(tmp_path):
    store_path = tmp_path / "decision_state.json"
    store = DecisionStateStore(store_path=store_path)
    state = DecisionState(
        status="rejected", trade_id=None, reason="too risky",
        acted_at=datetime.now(timezone.utc),
    )
    store.set("dec_nifty_20260804", state)

    restarted = DecisionStateStore(store_path=store_path)
    loaded = restarted.get("dec_nifty_20260804")

    assert loaded is not None
    assert loaded.status == "rejected"
    assert loaded.reason == "too risky"
