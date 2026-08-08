"""Bootstrap confidence floor: 0.70 until the first real closed trade, then 0.80."""

from __future__ import annotations

from pathlib import Path

from backend.services import confidence_floor
from backend.services.learning_service import LearningService


def _service(tmp_path: Path) -> LearningService:
    return LearningService(store_path=tmp_path / "learning_store.json")


_CFG = {
    "execution_constraints": {
        "min_recommendation_confidence": 0.80,
        "bootstrap_min_confidence": 0.70,
    }
}


def _record_real_close(svc: LearningService) -> None:
    # Inject a real (non-seed) closed outcome row; the full close flow is
    # exercised by test_learning_seed.py::test_paper_sim_close_feeds_learning_outcome.
    store = svc._read()
    store.setdefault("outcomes", []).append(
        {
            "outcome_id": "out_real_001",
            "trade_id": "pos_abc123def456",
            "realized_pnl_inr": 120.0,
            "recommendation_snapshot": {},
        }
    )
    svc._write(store)


def test_floor_is_bootstrap_while_no_real_closed_trades(tmp_path, monkeypatch) -> None:
    svc = _service(tmp_path)  # fresh store contains only seed fixtures
    monkeypatch.setattr(confidence_floor, "get_learning_service", lambda: svc)
    monkeypatch.delenv("MIN_RECOMMENDATION_CONFIDENCE", raising=False)

    value, source = confidence_floor.effective_min_confidence(_CFG)

    assert value == 0.70
    assert source == "bootstrap"


def test_floor_reverts_after_first_real_close(tmp_path, monkeypatch) -> None:
    svc = _service(tmp_path)
    _record_real_close(svc)
    monkeypatch.setattr(confidence_floor, "get_learning_service", lambda: svc)
    monkeypatch.delenv("MIN_RECOMMENDATION_CONFIDENCE", raising=False)

    value, source = confidence_floor.effective_min_confidence(_CFG)

    assert value == 0.80
    assert source == "config"


def test_seed_outcomes_do_not_count_as_real(tmp_path, monkeypatch) -> None:
    svc = _service(tmp_path)
    monkeypatch.setattr(confidence_floor, "get_learning_service", lambda: svc)
    monkeypatch.delenv("MIN_RECOMMENDATION_CONFIDENCE", raising=False)

    # The freshly seeded store already carries trd_seed_* outcomes.
    assert svc.real_closed_trade_count() == 0
    value, _ = confidence_floor.effective_min_confidence(_CFG)
    assert value == 0.70


def test_env_override_wins_and_is_clamped(tmp_path, monkeypatch) -> None:
    svc = _service(tmp_path)
    monkeypatch.setattr(confidence_floor, "get_learning_service", lambda: svc)

    monkeypatch.setenv("MIN_RECOMMENDATION_CONFIDENCE", "0.65")
    value, source = confidence_floor.effective_min_confidence(_CFG)
    assert value == 0.65
    assert source == "env"

    monkeypatch.setenv("MIN_RECOMMENDATION_CONFIDENCE", "0.10")
    value, _ = confidence_floor.effective_min_confidence(_CFG)
    assert value == 0.5  # clamped low

    monkeypatch.setenv("MIN_RECOMMENDATION_CONFIDENCE", "0.99")
    value, _ = confidence_floor.effective_min_confidence(_CFG)
    assert value == 0.95  # clamped high

    monkeypatch.setenv("MIN_RECOMMENDATION_CONFIDENCE", "not-a-number")
    value, source = confidence_floor.effective_min_confidence(_CFG)
    assert value == 0.70  # falls back to bootstrap path
    assert source == "bootstrap"


def test_learning_service_unavailable_falls_back_to_config_floor(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(confidence_floor, "get_learning_service", _boom)
    monkeypatch.delenv("MIN_RECOMMENDATION_CONFIDENCE", raising=False)

    value, source = confidence_floor.effective_min_confidence(_CFG)

    assert value == 0.80  # fail closed to the stricter floor
    assert source == "config"


def test_learning_service_unavailable_logs_the_failure(monkeypatch, caplog) -> None:
    """
    An unreadable learning store silently moving the floor 0.70 -> 0.80 is a
    trading-threshold change with no operator signal — it must be logged.
    """
    import logging

    def _boom():
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(confidence_floor, "get_learning_service", _boom)
    monkeypatch.delenv("MIN_RECOMMENDATION_CONFIDENCE", raising=False)

    with caplog.at_level(logging.ERROR, logger="backend.services.confidence_floor"):
        value, source = confidence_floor.effective_min_confidence(_CFG)

    assert value == 0.80
    assert source == "config"
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert "unreadable" in record.message.lower() or "failing closed" in record.message.lower()
    assert "store unreadable" in caplog.text
