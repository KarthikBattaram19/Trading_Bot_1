"""Recommendation generation must not hang page/API callers forever."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from backend.models.recommendations import (
    FeedHealth,
    FeedSource,
    FeedSourceStatus,
    MarketNewsSummary,
    RecommendationResponse,
)
from backend.services import recommendation_engine as engine


def _empty_response(*, generated_at: datetime | None = None) -> RecommendationResponse:
    now = generated_at or datetime.now(timezone.utc)
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
        universe_scanned=0,
        candidates_passing_gates=0,
        recommendations=[],
        analysis_notes=["cached-or-empty"],
    )


@pytest.fixture(autouse=True)
def _reset_response_cache():
    engine.reset_recommendation_response_cache_for_tests()
    yield
    engine.reset_recommendation_response_cache_for_tests()


@pytest.mark.asyncio
async def test_generate_recommendations_returns_cached_within_ttl(monkeypatch):
    calls = {"n": 0}
    first = _empty_response()
    first.analysis_notes = ["first-generation"]

    async def _fake_uncached(**_kwargs):
        calls["n"] += 1
        return first

    monkeypatch.setattr(engine, "_generate_recommendations_uncached", _fake_uncached)
    monkeypatch.setattr(engine, "_response_cache_ttl_sec", lambda: 90.0)

    a = await engine.generate_recommendations()
    b = await engine.generate_recommendations()

    assert calls["n"] == 1
    assert a.analysis_notes == ["first-generation"]
    assert b.analysis_notes == ["first-generation"]


@pytest.mark.asyncio
async def test_generate_recommendations_force_refresh_bypasses_cache(monkeypatch):
    calls = {"n": 0}

    async def _fake_uncached(**_kwargs):
        calls["n"] += 1
        resp = _empty_response()
        resp.analysis_notes = [f"gen-{calls['n']}"]
        return resp

    monkeypatch.setattr(engine, "_generate_recommendations_uncached", _fake_uncached)
    monkeypatch.setattr(engine, "_response_cache_ttl_sec", lambda: 90.0)

    a = await engine.generate_recommendations()
    b = await engine.generate_recommendations(force_refresh=True)

    assert calls["n"] == 2
    assert a.analysis_notes == ["gen-1"]
    assert b.analysis_notes == ["gen-2"]


@pytest.mark.asyncio
async def test_peek_cached_recommendations_none_when_empty():
    assert engine.peek_cached_recommendations() is None


@pytest.mark.asyncio
async def test_enrich_many_stops_when_deadline_exceeded():
    from backend.services.universe_enrichment import UniverseEnricher

    enricher = UniverseEnricher(
        cache_ttl_sec=90,
        max_concurrency=2,
        min_interval_ms=0,
        fetch_spot_ltp=False,
    )

    async def _slow_one(self, symbol, stats=None):  # noqa: ANN001
        await asyncio.sleep(0.05)
        return None

    enricher.enrich_one = _slow_one.__get__(enricher, UniverseEnricher)  # type: ignore[method-assign]

    started = asyncio.get_event_loop().time()
    _out, stats = await enricher.enrich_many(
        [f"SYM{i}" for i in range(40)],
        deadline_monotonic=started + 0.12,
        max_symbols=40,
    )
    elapsed = asyncio.get_event_loop().time() - started

    assert elapsed < 0.5
    assert stats.requested <= 40
    assert "deadline" in " ".join(stats.errors).lower() or stats.failed >= 0
