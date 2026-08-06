"""Phase 1.4 — SH-4 strategy selection with Market_News overlay (N-02–N-12)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.models.recommendations import MarketNewsSummary, NewsItem, StrategyType
from backend.services.market_news import reset_market_news_cache
from backend.services.strategy_selection import (
    QuantRegimeInputs,
    recommendation_action,
    select_strategy_packet,
    select_strategy_sh4,
)


@pytest.fixture(autouse=True)
def _clear_news_cache():
    reset_market_news_cache()
    yield
    reset_market_news_cache()


def _news(**overrides) -> MarketNewsSummary:
    base = dict(
        headline_count=1,
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
        interpretation="test",
        items=[],
    )
    base.update(overrides)
    return MarketNewsSummary.model_validate(base)


def _quant(**overrides) -> QuantRegimeInputs:
    base = dict(
        symbol="SBIN",
        iv_annualized=0.22,
        garch_forecast=0.28,
        iv_z_score=None,
        days_to_earnings=None,
        realized_vol_intraday=0.01,
        garch_distorted=False,
    )
    base.update(overrides)
    return QuantRegimeInputs(**base)


def test_n02_earnings_event_rejects_simple_vol_prefers_gamma():
    """N-02: Earnings / company event + plain long-vega → gamma earnings_gap_mode."""
    news = _news(
        news_event_imminent=True,
        earnings_mentions=1,
        topics=["earnings"],
        symbol_tags=["INFY"],
        macro_risk_flags=["company_event_coverage"],
    )
    # Cheap IV would otherwise pick simple_volatility; event must override.
    sel = select_strategy_sh4(
        _quant(symbol="INFY", iv_annualized=0.20, garch_forecast=0.30, iv_z_score=-2.5),
        news,
    )
    assert sel.selected_strategy == StrategyType.gamma_scalping
    assert sel.entry_mode == "earnings_gap_mode"
    assert any("simple_volatility" in r for r in sel.rejected_strategies)
    assert any("vega_scalping" in r for r in sel.rejected_strategies)


def test_n02_calendar_earnings_also_forces_gamma():
    news = _news()
    sel = select_strategy_sh4(
        _quant(symbol="INFY", days_to_earnings=1, iv_z_score=None),
        news,
    )
    assert sel.selected_strategy == StrategyType.gamma_scalping
    assert sel.entry_mode == "earnings_gap_mode"


def test_n03_post_shock_blocks_all_vol():
    """N-03: Post-shock / crisis → blocked / stand_aside."""
    news = _news(
        dominant_tone="bearish",
        news_post_shock=True,
        news_not_blocking=False,
        news_impact="adverse_tone",
        macro_risk_flags=["post-shock", "crisis_tone"],
    )
    sel = select_strategy_sh4(
        _quant(iv_annualized=0.20, garch_forecast=0.35, iv_z_score=-2.4),
        news,
    )
    assert sel.selected_strategy == StrategyType.blocked
    packet = select_strategy_packet(_quant(), news)
    assert packet["recommendation"] in {"blocked", "stand_aside"}


def test_n03_garch_distorted_blocks():
    news = _news()
    sel = select_strategy_sh4(_quant(garch_distorted=True), news)
    assert sel.selected_strategy == StrategyType.blocked


def test_n04_n05_n06_post_entry_news_no_longer_exists():
    """N-04/N-05/N-06 (superseded): there is no post-entry news action at all.

    ``post_entry_news_action`` and ``select_strategy_packet``'s
    ``post_entry_action`` key were removed — news is entry-side only
    (SH-4 overlay may decline to open a NEW trade; it can never act on an
    already-open one). See backend/paper_sim/automation.py for the
    guarantee that open positions are never closed by news
    (test_adverse_post_shock_news_never_closes_open_position).
    """
    import backend.services.strategy_selection as ss

    assert not hasattr(ss, "post_entry_news_action")
    news = _news(news_impact="adverse_tone", news_post_shock=True, dominant_tone="bearish")
    packet = select_strategy_packet(_quant(), news)
    assert "post_entry_action" not in packet


def test_n07_symbol_tagged_adverse_defers_entry():
    """N-07: Symbol-tagged adverse news → prefer defer / blocked."""
    news = _news(
        dominant_tone="bearish",
        news_not_blocking=False,
        symbol_tags=["SBIN"],
        items=[
            NewsItem(
                title="SBIN hit by fraud probe",
                summary="Adverse company news",
                source="Moneycontrol",
                time_published="20260730T100000",
                sentiment_label="Bearish",
                sentiment_score=-0.6,
                tickers=["SBIN"],
                topics=["corporate_action"],
            )
        ],
    )
    # Not cheap-vol elevated RV path — adverse symbol with blocking news
    sel = select_strategy_sh4(
        _quant(
            symbol="SBIN",
            iv_annualized=0.30,
            garch_forecast=0.28,
            realized_vol_intraday=0.01,
        ),
        news,
    )
    assert sel.selected_strategy == StrategyType.blocked


def test_n10_regulatory_surprise_blocks():
    """N-10: SEBI / regulatory surprise → block model trades."""
    news = _news(
        macro_risk_flags=["regulatory_surprise"],
        topics=["sebi_regulatory"],
        news_not_blocking=True,  # packet may not flip U4; SH-4 still blocks on flag
    )
    sel = select_strategy_sh4(_quant(iv_z_score=-2.5), news)
    assert sel.selected_strategy == StrategyType.blocked


def test_n12_iv_flush_but_news_blocking_no_vega():
    """N-12: IV z ≤ −2 but news blocking → no vega entry."""
    news = _news(
        dominant_tone="bearish",
        news_not_blocking=False,
        news_impact="adverse_tone",
    )
    sel = select_strategy_sh4(
        _quant(iv_annualized=0.22, garch_forecast=0.28, iv_z_score=-2.5),
        news,
    )
    assert sel.selected_strategy != StrategyType.vega_scalping
    assert any("vega_scalping" in r and "news_not_blocking" in r for r in sel.rejected_strategies)


def test_normal_regime_prefers_simple_vol():
    news = _news()
    sel = select_strategy_sh4(
        _quant(iv_annualized=0.22, garch_forecast=0.30, iv_z_score=None),
        news,
    )
    assert sel.selected_strategy == StrategyType.simple_volatility
    assert sel.entry_mode == "cheap_vol_mode"
    assert recommendation_action(sel) == "enter_long_vol"


def test_iv_flush_news_clear_prefers_vega():
    news = _news(news_not_blocking=True)
    sel = select_strategy_sh4(
        _quant(iv_annualized=0.25, garch_forecast=0.24, iv_z_score=-2.2),
        news,
    )
    assert sel.selected_strategy == StrategyType.vega_scalping
    assert recommendation_action(sel) == "enter_vega"


def test_high_rv_prefers_gamma():
    news = _news()
    sel = select_strategy_sh4(
        _quant(
            iv_annualized=0.35,
            garch_forecast=0.25,
            iv_z_score=None,
            realized_vol_intraday=0.02,
        ),
        news,
    )
    assert sel.selected_strategy == StrategyType.gamma_scalping
    assert sel.entry_mode == "high_realized_vol_mode"


def test_paper_sim_strategies_select_endpoint():
    from backend.main import app

    client = TestClient(app)
    body = {
        "symbol": "SBIN",
        "iv_annualized": 0.22,
        "garch_forecast": 0.30,
        "iv_z_score": None,
        "force_news": {
            "dominant_tone": "neutral",
            "news_not_blocking": True,
            "news_event_imminent": False,
            "news_post_shock": False,
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
    resp = client.post("/api/v1/paper-sim/strategies/select", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["selected_strategy"] == "simple_volatility"
    assert data["recommendation"] == "enter_long_vol"
    assert data["market_news"]["news_not_blocking"] is True


def test_paper_sim_strategies_select_earnings_override():
    from backend.main import app

    client = TestClient(app)
    body = {
        "symbol": "INFY",
        "iv_annualized": 0.20,
        "garch_forecast": 0.30,
        "iv_z_score": -2.5,
        "force_news": {
            "dominant_tone": "neutral",
            "news_not_blocking": True,
            "news_event_imminent": True,
            "news_post_shock": False,
            "news_impact": "none",
            "macro_risk_flags": ["company_event_coverage"],
            "topics": ["earnings"],
            "symbol_tags": ["INFY"],
            "earnings_mentions": 1,
            "items": [],
            "interpretation": "earnings dry-run",
            "headline_count": 1,
            "dominant_sentiment": "Neutral",
        },
    }
    resp = client.post("/api/v1/paper-sim/strategies/select", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["selected_strategy"] == "gamma_scalping"
    assert data["entry_mode"] == "earnings_gap_mode"
    assert data["recommendation"] == "enter_gamma"
