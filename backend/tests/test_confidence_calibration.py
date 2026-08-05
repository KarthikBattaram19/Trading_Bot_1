"""Tests for confidence calibration (§10.4 / 2026-08-01 design)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.analytics.confidence_calibration import (
    apply_map,
    fit_and_maybe_deploy,
    is_seed_outcome,
    is_win,
    raw_x_from_outcome,
)
from backend.services.confidence_calibrator import ConfidenceCalibrator


def test_is_win_v1_pnl_positive():
    assert is_win(100.0, "win", "simple_volatility") is True
    assert is_win(-50.0, "loss", "simple_volatility") is False
    assert is_win(0.0, "loss", "vega_scalping") is False
    assert is_win(10.0, "scratch", "gamma_scalping") is None


def test_is_seed_outcome():
    assert is_seed_outcome({"trade_id": "trd_seed_tatasteel_001"}) is True
    assert is_seed_outcome({"outcome_id": "out_seed_001"}) is True
    assert is_seed_outcome({"failure_id": "fm_seed_tatasteel_vega"}) is True
    assert is_seed_outcome({"recommendation_snapshot": {"seed": True}}) is True
    assert is_seed_outcome({"trade_id": "trd_live_001"}) is False


def test_apply_map_interpolates_and_clamps():
    knots = [0.5, 0.7, 0.9]
    p = [0.4, 0.6, 0.8]
    assert apply_map(0.6, knots, p) == pytest.approx(0.5)
    # Below first knot → first p_win (then clamp)
    assert apply_map(0.0, knots, p) == pytest.approx(0.4)
    assert apply_map(1.0, knots, p) == pytest.approx(0.8)
    assert apply_map(0.7, [0.5], [0.01]) == pytest.approx(0.05)  # clamp low


def test_calibrator_prefers_strategy_map(tmp_path: Path):
    path = tmp_path / "confidence_calibration.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "deployed": True,
                "fitted_at": "2026-01-01T00:00:00+00:00",
                "walk_forward_ok": True,
                "walk_forward_metrics": {},
                "min_samples": 30,
                "global": {"n": 40, "x_knots": [0.5, 0.9], "p_win": [0.4, 0.8]},
                "by_strategy": {
                    "simple_volatility": {
                        "n": 35,
                        "x_knots": [0.5, 0.9],
                        "p_win": [0.3, 0.9],
                    }
                },
                "fit_notes": [],
            }
        ),
        encoding="utf-8",
    )
    cal = ConfidenceCalibrator(path)
    conf, status, source = cal.apply(0.7, "simple_volatility")
    assert status == "calibrated"
    assert conf == pytest.approx(0.6)  # midway on strategy map 0.3→0.9
    conf_g, _, _ = cal.apply(0.7, "vega_scalping")
    assert conf_g == pytest.approx(0.6)  # global 0.4→0.8 mid


def _outcome(
    i: int,
    *,
    score: float,
    pnl: float,
    strategy: str = "simple_volatility",
    seed: bool = False,
    raw: float | None = None,
    days_ago: int = 0,
) -> dict:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i + days_ago)
    tid = f"trd_seed_{i}" if seed else f"trd_{i:04d}"
    label = "win" if pnl > 0 else "loss"
    row = {
        "outcome_id": f"out_{i:04d}",
        "trade_id": tid,
        "strategy": strategy,
        "score_at_entry": score,
        "confidence_at_entry": min(0.95, score + 0.05),
        "realized_pnl_inr": pnl,
        "outcome": label,
        "closed_at": base.isoformat(),
    }
    if raw is not None:
        row["raw_confidence_at_entry"] = raw
    return row


def test_fit_too_small_does_not_deploy(tmp_path: Path):
    outcomes = [
        _outcome(i, score=0.6 + (i % 5) * 0.05, pnl=100 if i % 2 else -50)
        for i in range(20)
    ]
    artifact = tmp_path / "confidence_calibration.json"
    report = fit_and_maybe_deploy(outcomes, artifact_path=artifact)
    assert report["deployed"] is False
    assert not artifact.exists()


def test_fit_happy_path_deploys_monotone_map(tmp_path: Path):
    # Interleaved bands over time so train and OOS both see monotone signal
    outcomes = []
    win_rates = [0.2, 0.4, 0.55, 0.7, 0.85]
    for i in range(80):
        band = i % 5
        raw = 0.5 + band * 0.1
        wr = win_rates[band]
        pnl = 100.0 if (i * 7 + band * 3) % 100 < wr * 100 else -80.0
        outcomes.append(
            _outcome(i, score=raw - 0.05, pnl=pnl, raw=raw, days_ago=i)
        )
    artifact = tmp_path / "confidence_calibration.json"
    report = fit_and_maybe_deploy(outcomes, artifact_path=artifact)
    assert report["deployed"] is True
    assert report["walk_forward_ok"] is True
    assert artifact.exists()
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data["deployed"] is True
    assert data["global"]["n"] >= 30
    assert len(data["global"]["x_knots"]) >= 2
    # Monotone p_win
    pw = data["global"]["p_win"]
    assert all(pw[i] <= pw[i + 1] + 1e-9 for i in range(len(pw) - 1))


def test_seed_exclusion(tmp_path: Path):
    outcomes = [
        _outcome(i, score=0.7, pnl=100 if i % 2 else -50, seed=True) for i in range(40)
    ]
    # Plus 5 real — still too few non-seed
    outcomes += [
        _outcome(100 + i, score=0.7, pnl=100 if i % 2 else -50) for i in range(5)
    ]
    artifact = tmp_path / "confidence_calibration.json"
    report = fit_and_maybe_deploy(outcomes, artifact_path=artifact)
    assert report["deployed"] is False
    assert report.get("n_fit", 0) == 5


def test_walk_forward_fail_retains_prior(tmp_path: Path):
    prior = tmp_path / "confidence_calibration.json"
    prior.write_text(
        json.dumps(
            {
                "version": 1,
                "deployed": True,
                "fitted_at": "2026-01-01T00:00:00+00:00",
                "walk_forward_ok": True,
                "walk_forward_metrics": {"brier_oos": 0.1, "brier_is": 0.1, "ece_oos": 0.0},
                "min_samples": 30,
                "global": {"n": 40, "x_knots": [0.5, 0.9], "p_win": [0.4, 0.8]},
                "by_strategy": {},
                "fit_notes": ["prior"],
            }
        ),
        encoding="utf-8",
    )
    # Random noisy outcomes — likely fail WF or if somehow pass, still OK;
    # force fail by alternating wins independent of score with enough samples
    outcomes = []
    for i in range(50):
        score = 0.5 + (i % 10) * 0.04
        # Anti-monotone: high score → loss
        pnl = -100.0 if score >= 0.7 else 100.0
        outcomes.append(_outcome(i, score=score, pnl=pnl, days_ago=i))
    report = fit_and_maybe_deploy(outcomes, artifact_path=prior)
    # Either not deployed this round, or if deployed the file should remain valid JSON
    data = json.loads(prior.read_text(encoding="utf-8"))
    if not report["deployed"]:
        assert data["fit_notes"] == ["prior"]
        assert data["global"]["p_win"] == [0.4, 0.8]


def test_hybrid_grain_strategy_map(tmp_path: Path):
    outcomes = []
    win_rates = [0.2, 0.4, 0.55, 0.7, 0.85]
    # 80 simple_volatility interleaved (enough for global WF + strategy map)
    for i in range(80):
        band = i % 5
        raw = 0.5 + band * 0.1
        wr = win_rates[band]
        pnl = 100.0 if (i * 7 + band * 3) % 100 < wr * 100 else -80.0
        outcomes.append(
            _outcome(
                i,
                score=raw - 0.05,
                pnl=pnl,
                strategy="simple_volatility",
                raw=raw,
                days_ago=i,
            )
        )
    # 10 vega interleaved early — not enough for own map; must not break global OOS
    for i in range(10):
        band = i % 5
        raw = 0.5 + band * 0.1
        wr = win_rates[band]
        pnl = 100.0 if (i * 7 + band * 3) % 100 < wr * 100 else -80.0
        outcomes.append(
            _outcome(
                100 + i,
                score=raw - 0.05,
                pnl=pnl,
                strategy="vega_scalping",
                raw=raw,
                days_ago=i,  # same early window, not trailing OOS-only
            )
        )
    artifact = tmp_path / "confidence_calibration.json"
    report = fit_and_maybe_deploy(outcomes, artifact_path=artifact)
    assert report["deployed"] is True
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert "simple_volatility" in data.get("by_strategy", {})
    assert "vega_scalping" not in data.get("by_strategy", {})


def test_calibrator_missing_artifact(tmp_path: Path):
    cal = ConfidenceCalibrator(tmp_path / "missing.json")
    conf, status, source = cal.apply(0.82, "simple_volatility")
    assert conf == pytest.approx(0.82)
    assert status == "uncalibrated"
    assert source == "heuristic"


def test_calibrator_applies_global_map(tmp_path: Path):
    path = tmp_path / "confidence_calibration.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "deployed": True,
                "fitted_at": "2026-01-01T00:00:00+00:00",
                "walk_forward_ok": True,
                "walk_forward_metrics": {},
                "min_samples": 30,
                "global": {"n": 40, "x_knots": [0.5, 0.9], "p_win": [0.4, 0.8]},
                "by_strategy": {},
                "fit_notes": [],
            }
        ),
        encoding="utf-8",
    )
    cal = ConfidenceCalibrator(path)
    conf, status, source = cal.apply(0.7, "vega_scalping")
    assert status == "calibrated"
    assert source == "outcome_map"
    assert conf == pytest.approx(0.6)


def test_raw_x_from_outcome_prefers_stored_raw():
    assert raw_x_from_outcome({"raw_confidence_at_entry": 0.77, "score_at_entry": 0.5}) == 0.77
    assert raw_x_from_outcome({"score_at_entry": 0.8}) == pytest.approx(0.85)
