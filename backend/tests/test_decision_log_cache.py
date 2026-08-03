"""Decision log must not hang waiting on a full live recommendation cycle."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.models.recommendations import (
    FeedHealth,
    FeedSource,
    FeedSourceStatus,
    MarketNewsSummary,
    RecommendationResponse,
)
from backend.services import decision_log
from backend.services import recommendation_engine as engine


def _empty_response() -> RecommendationResponse:
    now = datetime.now(timezone.utc)
    return RecommendationResponse(
        generated_at=now,
        feed_as_of=now,
        feed_sources=[
            FeedSource(
                source_id="test",
                source_name="test",
                status=FeedSourceStatus.active,
                capabilities=["quotes"],
                last_fetch_at=now,
                health=FeedHealth.fresh,
            )
        ],
        market_news=MarketNewsSummary(
            headline_count=0,
            dominant_sentiment="neutral",
            earnings_mentions=0,
            macro_risk_flags=[],
            interpretation="test",
            items=[],
        ),
        universe_scanned=3,
        candidates_passing_gates=1,
        recommendations=[],
        analysis_notes=["from-cache"],
    )


@pytest.fixture(autouse=True)
def _reset_caches():
    engine.reset_recommendation_response_cache_for_tests()
    yield
    engine.reset_recommendation_response_cache_for_tests()


@pytest.mark.asyncio
async def test_list_decisions_uses_cache_without_calling_generate(monkeypatch):
    cached = _empty_response()
    engine._store_recommendation_response_cache(cached)

    async def _should_not_run(**_kwargs):
        raise AssertionError("generate_recommendations must not run when cache is warm")

    monkeypatch.setattr(decision_log, "generate_recommendations", _should_not_run)
    monkeypatch.setattr(decision_log, "_acted_on_decisions", lambda: [])

    decisions = await decision_log.list_decisions()
    assert decisions == []


@pytest.mark.asyncio
async def test_list_decisions_returns_acted_on_when_generate_times_out(monkeypatch):
    async def _hang(**_kwargs):
        import asyncio

        await asyncio.sleep(60)
        return _empty_response()

    monkeypatch.setattr(decision_log, "generate_recommendations", _hang)
    monkeypatch.setattr(decision_log, "peek_cached_recommendations", lambda: None)
    monkeypatch.setattr(decision_log, "_acted_on_decisions", lambda: [])
    monkeypatch.setattr(decision_log, "_LIVE_DECISIONS_TIMEOUT_SEC", 0.05)

    decisions = await decision_log.list_decisions()
    assert decisions == []
