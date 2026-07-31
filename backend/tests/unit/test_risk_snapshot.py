"""Risk snapshot + circuit breaker unit/API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.execution.circuit_breakers import (
    CircuitBreakerThresholds,
    evaluate_circuit_breakers,
)
from backend.main import app
from backend.paper_sim.service import get_paper_engine
from backend.services.risk_snapshot import build_risk_snapshot


def test_evaluate_circuit_breakers_safe_by_default():
    rows = evaluate_circuit_breakers(
        drawdown_pct=0.0,
        daily_loss_inr=0.0,
        equity_inr=1_000_000.0,
        consecutive_losses=0,
        feed_age_sec=1.0,
        thresholds=CircuitBreakerThresholds(),
    )
    assert len(rows) == 4
    assert all(r.tone == "safe" for r in rows)
    daily = next(r for r in rows if r.id == "max_daily_loss")
    assert daily.limit == 20_000.0


def test_evaluate_circuit_breakers_warn_and_breach():
    rows = evaluate_circuit_breakers(
        drawdown_pct=9.0,
        daily_loss_inr=19_000.0,
        equity_inr=1_000_000.0,
        consecutive_losses=5,
        feed_age_sec=70.0,
        thresholds=CircuitBreakerThresholds(warn_utilization_pct=80.0),
    )
    by_id = {r.id: r for r in rows}
    assert by_id["max_drawdown"].tone == "warn"
    assert by_id["max_daily_loss"].tone == "warn"
    assert by_id["consecutive_losses"].tone == "danger"
    assert by_id["feed_staleness"].tone == "danger"


def test_risk_snapshot_flat_account():
    get_paper_engine(reset=True)
    snap = build_risk_snapshot()
    assert snap["equity_inr"] == 1_000_000.0
    assert snap["reserved_margin_inr"] == 0.0
    assert snap["drawdown_pct"] == 0.0
    assert snap["greeks_within_limits"] is True
    assert len(snap["circuit_breakers"]) == 4
    assert len(snap["greek_limits"]) == 4
    assert len(snap["shared_kill_conditions"]) >= 5
    # Idle ledger: no quote age → feed breaker stays safe (kill_switch only if armed)
    assert all(
        b["id"] != "feed_staleness" or b["tone"] == "safe"
        for b in snap["circuit_breakers"]
    )
    assert set(snap["circuit_breakers_active"]).issubset({"kill_switch"})


def test_risk_snapshot_api():
    get_paper_engine(reset=True)
    client = TestClient(app)
    res = client.get("/api/v1/risk/snapshot")
    assert res.status_code == 200
    body = res.json()
    assert body["equity_inr"] == 1_000_000.0
    assert body["limits"]["max_consecutive_losses"] == 5
    assert body["limits"]["max_daily_loss_pct"] == 2.0
    assert body["greek_limits"][0]["greek"] == "Delta"

    bot = client.get("/api/v1/bot/status")
    assert bot.status_code == 200
    status = bot.json()
    assert "drawdown_pct" in status
    assert "portfolio_greeks" in status
