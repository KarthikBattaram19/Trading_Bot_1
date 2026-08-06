"""Phase 1.6 — γ–θ re-hedge automation (mechanical; no LLM)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.models.recommendations import MarketNewsSummary
from backend.paper_sim.config import PaperSimConfig
from backend.paper_sim.models import (
    PaperLegPosition,
    PaperLegRequest,
    PaperOrderRequest,
    PaperSide,
)
from backend.paper_sim.service import get_paper_engine
from backend.services.market_news import reset_market_news_cache
from backend.tests.test_paper_sim import FakeFeed, _simple_vol_order


@pytest.fixture(autouse=True)
def _reset_news():
    reset_market_news_cache()
    yield
    reset_market_news_cache()


def _engine(**cfg_overrides):
    feed = FakeFeed()
    # ATM vs FakeFeed strike 500 — realistic Γ/Θ for breakeven tests
    feed.ltps["3045"] = 500.0
    defaults = dict(
        slippage_bps=0,
        require_fresh_marks=False,
        automation_tick_sec=1.0,
        rehedge_cooldown_sec=0.0,
        delta_threshold=0.0,  # allow hedge when delta drifts after move
        min_edge_threshold=-1e9,  # focus on distance gate in integration tests
        hedge_transaction_cost_inr=0.0,
    )
    defaults.update(cfg_overrides)
    config = PaperSimConfig(**defaults)
    return get_paper_engine(config=config, feed=feed, reset=True), feed


def _neutral_news(**overrides) -> MarketNewsSummary:
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


def test_default_rehedge_method_is_adjust_call_put_mix():
    assert PaperSimConfig().rehedge_method == "adjust_call_put_mix"


@pytest.mark.asyncio
async def test_open_sets_hedge_point_from_underlying():
    engine, feed = _engine()
    result = await engine.submit_order(_simple_vol_order())
    pos = result["position"]
    assert pos["hedge_point_price"] == pytest.approx(500.0)
    assert pos["breakeven_paid_count"] == 0
    assert pos["rehedge_method"] == "adjust_call_put_mix"
    assert result["broker_place_order"] is False


@pytest.mark.asyncio
async def test_rehedge_when_spot_moves_past_breakeven():
    engine, feed = _engine(use_half_breakeven=False)
    opened = await engine.submit_order(_simple_vol_order())
    position_id = opened["position"]["position_id"]
    assert opened["position"]["hedge_point_price"] == pytest.approx(500.0)

    # Move spot far enough that |ΔS|/S clears computed breakeven
    feed.ltps["3045"] = 530.0  # +6%

    from unittest.mock import patch

    with patch(
        "backend.services.market_news.get_market_news",
        return_value=_neutral_news(),
    ):
        tick = await engine.automation.tick()

    actions = tick["actions"]
    rehedges = [a for a in actions if a.get("action") == "rehedge"]
    assert rehedges, f"expected rehedge, got {actions}"
    assert rehedges[0]["method"] in {
        "increase_hedge",
        "reduce_options",
        "adjust_call_put_mix",
    }
    assert tick["status"]["llm_in_path"] is False

    pos = engine.ledger.positions[position_id]
    assert pos.breakeven_paid_count >= 1
    assert pos.hedge_point_price == pytest.approx(530.0)
    assert pos.gamma_theta_breakeven_pct is not None
    assert pos.gamma_theta_breakeven_pct > 0


@pytest.mark.asyncio
async def test_position_greeks_skips_cash_legs():
    engine, _feed = _engine()
    opened = await engine.submit_order(_simple_vol_order())
    position_id = opened["position"]["position_id"]
    position = engine.ledger.positions[position_id]
    position.legs.append(
        PaperLegPosition(
            symbol="SBIN",
            exchange="NSE",
            symbol_token="3045",
            side=PaperSide.buy,
            quantity=7,
            avg_price=500.0,
            mark_ltp=500.0,
            lotsize=1,
        )
    )

    captured_legs = []

    def fake_mark_strategy(*, global_params, legs):
        _ = global_params
        captured_legs.extend(legs)

        class Result:
            total_delta = 0.0
            total_gamma = 0.0
            total_theta = 0.0
            total_vega = 0.0

        return Result()

    from unittest.mock import patch

    with patch("backend.paper_sim.automation.mark_strategy", side_effect=fake_mark_strategy):
        await engine.automation._position_greeks(position_id, 500.0)

    assert captured_legs
    assert all(leg["type"] != "stock" for leg in captured_legs)


@pytest.mark.asyncio
async def test_increase_hedge_uses_options_only_adjustment():
    engine, feed = _engine(rehedge_method="increase_hedge", use_half_breakeven=False)
    opened = await engine.submit_order(_simple_vol_order())
    position_id = opened["position"]["position_id"]
    feed.ltps["3045"] = 530.0

    from unittest.mock import patch

    with patch(
        "backend.services.market_news.get_market_news",
        return_value=_neutral_news(),
    ):
        tick = await engine.automation.tick()

    rehedges = [a for a in tick["actions"] if a.get("action") == "rehedge"]
    assert rehedges, f"expected rehedge, got {tick['actions']}"
    assert rehedges[0]["method"] == "adjust_call_put_mix"
    assert all(fill["exchange"] == "NFO" for fill in rehedges[0]["fills"])

    pos = engine.ledger.positions[position_id]
    assert all(leg.exchange == "NFO" for leg in pos.legs)


@pytest.mark.asyncio
async def test_ps06_news_kill_flattens_instead_of_rehedge():
    engine, feed = _engine()
    await engine.submit_order(_simple_vol_order())
    feed.ltps["3045"] = 560.0

    from unittest.mock import patch

    with patch(
        "backend.services.market_news.get_market_news",
        return_value=_neutral_news(news_impact="early_exit", news_post_shock=True),
    ):
        tick = await engine.automation.tick()

    assert any(a.get("action") == "flatten" for a in tick["actions"])
    assert engine.positions(status="open") == []


@pytest.mark.asyncio
async def test_ps05_capital_cap_falls_back_to_reduce_options():
    # Legacy increase_hedge must remain options-only under tight capital.
    engine, feed = _engine(
        total_capital_inr=50_000,
        max_trade_investment_inr=2_000,
        max_leg_investment_inr=2_000,
        rehedge_method="increase_hedge",
    )
    # Cheap options so entry fits
    feed.ltps["40123"] = 5.0
    feed.ltps["40124"] = 5.0
    order = PaperOrderRequest(
        strategy_tag="simple_vol",
        underlying="SBIN",
        legs=[
            PaperLegRequest(
                symbol="SBIN28MAR24500CE",
                side=PaperSide.buy,
                quantity=25,
                exchange="NFO",
                symbol_token="40123",
            ),
            PaperLegRequest(
                symbol="SBIN28MAR24500PE",
                side=PaperSide.buy,
                quantity=25,
                exchange="NFO",
                symbol_token="40124",
            ),
        ],
    )
    opened = await engine.submit_order(order)
    position_id = opened["position"]["position_id"]
    feed.ltps["3045"] = 560.0

    from unittest.mock import patch

    with patch(
        "backend.services.market_news.get_market_news",
        return_value=_neutral_news(),
    ):
        tick = await engine.automation.tick()

    actions = [a for a in tick["actions"] if a.get("position_id") == position_id]
    assert actions
    # Either options-only hedge or capital_cap skip — must not create cash legs.
    assert all(a.get("action") in {"rehedge", "skip"} for a in actions)
    if any(a.get("action") == "rehedge" for a in actions):
        assert any(
            a.get("method") in {"reduce_options", "adjust_call_put_mix"} for a in actions
        )
        assert all(leg.exchange == "NFO" for leg in engine.ledger.positions[position_id].legs)


@pytest.mark.asyncio
async def test_ps08_kill_switch_skips_hedges():
    engine, feed = _engine()
    await engine.submit_order(_simple_vol_order())
    feed.ltps["3045"] = 560.0

    from backend.services.kill_switch_state import get_kill_switch_state

    state = get_kill_switch_state()
    state.set_armed(True)
    try:
        from unittest.mock import patch

        await engine.automation.start()
        with patch(
            "backend.services.market_news.get_market_news",
            return_value=_neutral_news(),
        ):
            tick = await engine.automation.tick()
        assert any(a.get("reason") == "kill_switch_armed" for a in tick["actions"])
        assert tick["status"]["state"] == "paused_kill_switch"
        await engine.automation.stop()
    finally:
        state.set_armed(False)


@pytest.mark.asyncio
async def test_ps09_stale_marks_skip_actions():
    engine, feed = _engine(require_fresh_marks=True, quote_stale_threshold_sec=1.0)
    await engine.submit_order(_simple_vol_order())
    feed.stale_tokens.add("40123")
    feed.age_sec["40123"] = 999.0

    from unittest.mock import patch

    with patch(
        "backend.services.market_news.get_market_news",
        return_value=_neutral_news(),
    ):
        tick = await engine.automation.tick()
    assert any(a.get("reason") == "marks_stale" for a in tick["actions"])


def test_automation_http_start_stop_status():
    from backend.main import app

    engine, _feed = _engine()
    client = TestClient(app)
    # Bind test engine into singleton used by routes
    get_paper_engine(config=engine.config, feed=engine.feed, reset=True)

    status = client.get("/api/v1/paper-sim/automation/status")
    assert status.status_code == 200
    body = status.json()
    assert body["state"] == "stopped"
    assert body["llm_in_path"] is False

    start = client.post(
        "/api/v1/paper-sim/automation/start",
        json={"tick_sec": 60, "rehedge_method": "increase_hedge"},
    )
    assert start.status_code == 200
    assert start.json()["running"] is True
    assert start.json()["llm_in_path"] is False

    health = client.get("/api/v1/paper-sim/health")
    assert health.status_code == 200
    assert health.json()["phase"] == "1.10"
    assert health.json()["capabilities"]["gamma_theta_automation"] is True
    assert health.json()["capabilities"]["llm_in_hedge_path"] is False

    stop = client.post("/api/v1/paper-sim/automation/stop")
    assert stop.status_code == 200
    assert stop.json()["running"] is False


@pytest.mark.asyncio
async def test_below_breakeven_skips_rehedge():
    engine, feed = _engine()
    await engine.submit_order(_simple_vol_order())
    # Tiny move — should stay below breakeven
    feed.ltps["3045"] = 500.5

    from unittest.mock import patch

    with patch(
        "backend.services.market_news.get_market_news",
        return_value=_neutral_news(),
    ):
        tick = await engine.automation.tick()

    skips = [a for a in tick["actions"] if a.get("action") == "skip"]
    assert skips
    assert skips[0]["reason"] in {"below_breakeven", "delta_below_threshold", "cooldown"}
