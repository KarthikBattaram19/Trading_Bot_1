"""Phase 1.5 — GARCH / IV z-score signals + POST /signals/evaluate."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.models.recommendations import MarketNewsSummary
from backend.services.market_news import reset_market_news_cache
from backend.services.signals import SignalComputeInputs, evaluate_candidate, signals_for_underlying


@pytest.fixture(autouse=True)
def _clear_news_cache():
    reset_market_news_cache()
    yield
    reset_market_news_cache()


def _neutral_news(**overrides) -> MarketNewsSummary:
    base = dict(
        headline_count=0,
        dominant_sentiment="Neutral",
        dominant_tone="neutral",
        earnings_mentions=0,
        macro_risk_flags=[],
        topics=[],
        symbol_tags=[],
        news_not_blocking=True,
        news_event_imminent=False,
        news_post_shock=False,
        news_impact="none",
        source_freshness={"reuters": datetime.now(timezone.utc)},
        workflow_window="session",
        kill_event=False,
        interpretation="test",
        items=[],
    )
    base.update(overrides)
    return MarketNewsSummary.model_validate(base)


def test_evaluate_cheap_vol_enter_long_vol():
    news = _neutral_news()
    inp = SignalComputeInputs(
        symbol="SBIN",
        und_price=812.0,
        option_iv_annual=0.22,
        garch_forecast_annual=0.30,
        iv_z_score=None,
        includes_underlying=True,
        atm_premium_inr=95,
        volume=22000,
        open_interest=35000,
        spread_pct=0.9,
    )
    out = evaluate_candidate(inp, news=news)
    assert out["cheap_vol"] is True
    assert out["garch_forecast_annual"] == pytest.approx(0.30)
    assert out["option_iv_annual"] == pytest.approx(0.22)
    assert out["iv_minus_garch"] == pytest.approx(-0.08)
    assert out["recommendation"] == "enter_long_vol"
    assert out["selected_strategy"] == "simple_volatility"
    assert out["gates_passed"] is True
    assert out["eligible"] is True


def test_evaluate_t11_fail_when_options_and_underlying():
    """MD-14 / T11: spot > ₹1000 with stock hedge → stand_aside."""
    news = _neutral_news()
    inp = SignalComputeInputs(
        symbol="INFY",
        und_price=1680.0,
        option_iv_annual=0.20,
        garch_forecast_annual=0.30,
        includes_underlying=True,
        atm_premium_inr=210,
        volume=15200,
        open_interest=28000,
        spread_pct=1.1,
    )
    out = evaluate_candidate(inp, news=news)
    assert out["gates_passed"] is False
    t11 = next(g for g in out["gates"] if g["gate_id"] == "T11")
    assert t11["passed"] is False
    assert out["recommendation"] == "stand_aside"
    assert out["eligible"] is False


def test_evaluate_t11_skipped_options_only():
    news = _neutral_news()
    inp = SignalComputeInputs(
        symbol="INFY",
        und_price=1680.0,
        option_iv_annual=0.20,
        garch_forecast_annual=0.30,
        includes_underlying=False,
        atm_premium_inr=210,
        volume=15200,
        open_interest=28000,
        spread_pct=1.1,
    )
    out = evaluate_candidate(inp, news=news)
    t11 = next(g for g in out["gates"] if g["gate_id"] == "T11")
    assert t11["passed"] is True
    assert "options-only" in (t11["detail"] or "").lower() or "N/A" in t11["label"]
    assert out["recommendation"] == "enter_long_vol"


def test_evaluate_q14_insufficient_history_stand_aside():
    news = _neutral_news()
    inp = SignalComputeInputs(
        symbol="SBIN",
        und_price=800.0,
        option_iv_annual=0.20,
        price_history=[800.0, 801.0, 799.0],  # too few bars
        includes_underlying=True,
    )
    out = evaluate_candidate(inp, news=news)
    assert out["garch_insufficient_history"] is True
    assert out["garch_distorted"] is True
    assert out["recommendation"] in {"stand_aside", "blocked"}


def test_evaluate_q15_rejects_vega_on_zero_std():
    news = _neutral_news()
    inp = SignalComputeInputs(
        symbol="ITC",
        und_price=428.0,
        option_iv_annual=0.26,
        garch_forecast_annual=0.25,
        intraday_iv_series=[0.26] * 20,  # σ=0
        includes_underlying=True,
        atm_premium_inr=68,
        volume=31000,
        open_interest=42000,
        spread_pct=0.7,
    )
    out = evaluate_candidate(inp, news=news)
    assert out["iv_z_reject_vega"] is True
    assert out["iv_zscore"] is None
    # Without usable z, should not pick vega_scalping
    assert out["selected_strategy"] != "vega_scalping"


def test_evaluate_vega_entry_when_z_flush():
    news = _neutral_news()
    inp = SignalComputeInputs(
        symbol="RELIANCE",
        und_price=982.0,
        option_iv_annual=0.24,
        garch_forecast_annual=0.28,
        iv_z_score=-2.5,
        includes_underlying=True,
        atm_premium_inr=185,
        volume=12500,
        open_interest=22000,
        spread_pct=1.2,
    )
    out = evaluate_candidate(inp, news=news)
    assert out["recommendation"] == "enter_vega"
    assert out["selected_strategy"] == "vega_scalping"
    assert out["vega_entry_ok"] is True


def test_evaluate_n03_garch_distorted_blocked():
    news = _neutral_news(news_post_shock=True, news_not_blocking=False)
    inp = SignalComputeInputs(
        symbol="SBIN",
        und_price=800.0,
        option_iv_annual=0.22,
        garch_forecast_annual=0.30,
        garch_distorted=True,
        includes_underlying=True,
    )
    out = evaluate_candidate(inp, news=news)
    assert out["garch_distorted"] is True
    assert out["recommendation"] in {"stand_aside", "blocked"}
    assert out["selected_strategy"] == "blocked"


def test_signals_for_underlying_packet_shape():
    packet = signals_for_underlying("SBIN", news=_neutral_news())
    for key in (
        "garch_forecast_annual",
        "option_iv_annual",
        "iv_minus_garch",
        "iv_zscore",
        "garch_distorted",
        "market_news",
        "selected_strategy",
        "recommendation",
    ):
        assert key in packet
    assert packet["underlying"] == "SBIN"
    assert packet["garch_forecast_annual"] is not None


def test_get_signals_endpoint():
    from backend.main import app

    client = TestClient(app)
    resp = client.get("/api/v1/paper-sim/signals", params={"underlying": "SBIN"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["underlying"] == "SBIN"
    assert "garch_forecast_annual" in data
    assert "recommendation" in data
    assert "market_news" in data


def test_post_signals_evaluate_endpoint():
    from backend.main import app

    client = TestClient(app)
    body = {
        "symbol": "SBIN",
        "und_price": 812.0,
        "option_iv_annual": 0.22,
        "garch_forecast_annual": 0.30,
        "includes_underlying": True,
        "atm_premium_inr": 95,
        "volume": 22000,
        "open_interest": 35000,
        "spread_pct": 0.9,
        "force_news": {
            "dominant_tone": "neutral",
            "news_not_blocking": True,
            "news_event_imminent": False,
            "news_post_shock": False,
            "kill_event": False,
            "news_impact": "none",
            "macro_risk_flags": [],
            "topics": [],
            "symbol_tags": [],
            "earnings_mentions": 0,
            "items": [],
            "interpretation": "dry-run",
            "headline_count": 0,
            "dominant_sentiment": "Neutral",
        },
    }
    resp = client.post("/api/v1/paper-sim/signals/evaluate", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["evaluate"] is True
    assert data["recommendation"] == "enter_long_vol"
    assert data["gates_passed"] is True
    assert any(g["gate_id"] == "T11" for g in data["gates"])
