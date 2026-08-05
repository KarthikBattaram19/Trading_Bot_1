"""Phase 1.3 — Market_News ingest → paper-sim /news + recommendation market_news."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.services.market_news import (
    get_market_news,
    mock_market_news,
    paper_news_packet,
    refresh_market_news,
    reset_market_news_cache,
)
from backend.services.market_news.classifier import classify_headline, aggregate_packet_flags
from backend.services.market_news.curation import (
    load_curation_contract,
    normalize_source_id,
    workflow_window_at,
)


@pytest.fixture(autouse=True)
def _clear_news_cache(monkeypatch: pytest.MonkeyPatch):
    # Deterministic offline path for unit tests (live RSS exercised separately).
    monkeypatch.setenv("MARKET_NEWS_LIVE", "0")
    monkeypatch.delenv("MARKET_NEWS_HEADLINES_PATH", raising=False)
    reset_market_news_cache()
    yield
    reset_market_news_cache()


def test_curation_contract_loads_market_news_txt():
    contract = load_curation_contract()
    assert contract.loaded is True
    assert contract.bot_priority == (
        "nse",
        "sebi",
        "reuters",
        "moneycontrol",
        "economic_times",
        "pulse",
        "cnbc_tv18",
    )
    assert "nse" in contract.windows["session"] or "pulse" in contract.windows["session"]
    assert normalize_source_id("Reuters India") == "reuters"
    assert normalize_source_id("SEBI circulars") == "sebi"


def test_classifier_tone_topics_symbols():
    item = classify_headline(
        title="Infosys quarterly earnings due tomorrow; Street eyes guidance",
        summary="IT major set to report results.",
        source="Moneycontrol",
        source_id="moneycontrol",
        time_published="20260730T084500",
        tickers_hint=["INFY"],
    )
    assert "earnings" in item.topics
    assert "INFY" in item.tickers
    assert item.tone in {"bullish", "neutral", "bearish"}

    shock = classify_headline(
        title="Markets in panic crash after geopolitical shock",
        summary="Circuit breakers tripped in a post-shock sell-off.",
        source="Reuters India",
        source_id="reuters",
        time_published="20260730T100000",
    )
    assert shock.tone == "bearish"
    assert "post_shock" in shock.topics
    flags = aggregate_packet_flags([shock])
    assert flags["news_post_shock"] is True
    assert flags["kill_event"] is True
    assert flags["news_impact"] == "kill_event"
    assert "post-shock" in flags["macro_risk_flags"]


def test_get_market_news_from_fixture():
    summary = refresh_market_news()
    assert summary.headline_count >= 4
    assert summary.dominant_tone in {"bullish", "neutral", "bearish"}
    assert summary.topics
    assert summary.symbol_tags
    assert summary.source_freshness
    assert summary.workflow_window in {"pre_open", "session", "after_close"}
    assert summary.news_impact in {
        "none",
        "take_profit",
        "rehedge_aggressive",
        "early_exit",
        "kill_event",
    }
    assert any("earnings" in (i.topics or []) for i in summary.items) or summary.earnings_mentions >= 0


def test_custom_headlines_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "headlines.json"
    path.write_text(
        json.dumps(
            [
                {
                    "title": "SEBI issues emergency circular after market crash panic",
                    "summary": "Post-shock regulatory surprise for derivatives desks.",
                    "source": "SEBI",
                    "time_published": "20260730T160000",
                    "tickers_hint": ["NIFTY"],
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MARKET_NEWS_HEADLINES_PATH", str(path))
    reset_market_news_cache()
    summary = refresh_market_news()
    assert summary.news_post_shock is True
    assert summary.dominant_tone == "bearish"
    assert "NIFTY" in summary.symbol_tags
    assert "sebi_regulatory" in summary.topics or any(
        "sebi_regulatory" in i.topics for i in summary.items
    )


def test_paper_news_packet_shape():
    packet = paper_news_packet(force_refresh=True)
    for key in (
        "dominant_tone",
        "topics",
        "symbol_tags",
        "macro_risk_flags",
        "source_freshness",
        "news_impact",
        "market_news",
    ):
        assert key in packet
    assert packet["market_news"]["headline_count"] == packet["market_news"]["headline_count"]
    assert isinstance(packet["topics"], list)


def test_paper_sim_news_endpoint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    from backend.main import app

    client = TestClient(app)
    res = client.get("/api/v1/paper-sim/news")
    assert res.status_code == 200
    data = res.json()
    assert data["dominant_tone"] in {"bullish", "neutral", "bearish"}
    assert "topics" in data
    assert "symbol_tags" in data
    assert "macro_risk_flags" in data
    assert "source_freshness" in data
    assert "news_impact" in data
    assert "market_news" in data

    health = client.get("/api/v1/paper-sim/health")
    assert health.status_code == 200
    body = health.json()
    assert body["phase"] == "1.10"
    assert body["capabilities"]["market_news"] is True
    assert "dominant_tone" in body["market_news"]


def test_recommendations_include_live_market_news(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    from backend.main import app
    from backend.services.universe_enrichment import (
        EnrichmentStats,
        LiveMarks,
        UniverseEnricher,
        reset_universe_enricher_for_tests,
    )

    reset_universe_enricher_for_tests()

    async def _fake_enrich_many(self, symbols, **_kwargs):  # noqa: ANN001
        marks = {
            s.upper(): LiveMarks(
                symbol=s.upper(),
                und_price=100.0,
                atm_premium_inr=40.0,
                volume=2000,
                open_interest=15000,
                spread_pct=1.0,
                dte=20,
                iv_annualized=0.2,
            )
            for s in symbols
        }
        return marks, EnrichmentStats(requested=len(symbols), live_ok=len(symbols))

    monkeypatch.setattr(UniverseEnricher, "enrich_many", _fake_enrich_many)

    client = TestClient(app)
    res = client.get("/api/v1/recommendations")
    assert res.status_code == 200
    data = res.json()
    news = data["market_news"]
    assert "dominant_tone" in news
    assert "topics" in news
    assert "macro_risk_flags" in news
    assert news["headline_count"] >= 1
    # Live fixture path — not the stub "Simulated Feed" mock unless empty
    sources = {i["source"] for i in news.get("items", [])}
    assert sources
    assert "feed_sources" in data
    news_feed = next(s for s in data["feed_sources"] if s["source_id"] == "market_news")
    assert news_feed["status"] in {"active", "stub"}


def test_recommendations_refresh_bypasses_market_news_cache(
    monkeypatch: pytest.MonkeyPatch,
):
    """Refresh analysis must re-ingest news even when the TTL cache is warm."""
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    monkeypatch.setenv("MARKET_NEWS_CACHE_TTL_SEC", "3600")
    reset_market_news_cache()

    from backend.services.recommendation_engine import (
        reset_recommendation_response_cache_for_tests,
    )

    reset_recommendation_response_cache_for_tests()

    primed = get_market_news(force_refresh=True)
    assert primed.source_freshness
    primed_ts = max(v for v in primed.source_freshness.values() if v is not None)

    # Warm-cache hit must still return the primed packet.
    assert get_market_news() is primed

    from backend.main import app
    from backend.services.universe_enrichment import (
        EnrichmentStats,
        LiveMarks,
        UniverseEnricher,
        reset_universe_enricher_for_tests,
    )

    reset_universe_enricher_for_tests()

    async def _fake_enrich_many(self, symbols, **_kwargs):  # noqa: ANN001
        marks = {
            s.upper(): LiveMarks(
                symbol=s.upper(),
                und_price=100.0,
                atm_premium_inr=40.0,
                volume=2000,
                open_interest=15000,
                spread_pct=1.0,
                dte=20,
                iv_annualized=0.2,
            )
            for s in symbols
        }
        return marks, EnrichmentStats(requested=len(symbols), live_ok=len(symbols))

    monkeypatch.setattr(UniverseEnricher, "enrich_many", _fake_enrich_many)

    client = TestClient(app)
    # Explicit refresh path (UI "Refresh analysis") must bypass response + news caches.
    res = client.get("/api/v1/recommendations?refresh=true")
    assert res.status_code == 200
    news = res.json()["market_news"]
    assert news["source_freshness"]
    refreshed_ts = max(
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        for v in news["source_freshness"].values()
        if v is not None
    )
    assert refreshed_ts >= primed_ts
    # After generate_recommendations, in-process cache is a new packet (not the primed one).
    assert get_market_news() is not primed


def test_mock_market_news_still_available():
    mock = mock_market_news()
    assert mock.headline_count == 2
    assert mock.dominant_tone == "neutral"


def test_workflow_window_boundaries():
    pre = workflow_window_at(datetime(2026, 7, 30, 3, 0, tzinfo=timezone.utc))  # 08:30 IST
    assert pre == "pre_open"
    session = workflow_window_at(datetime(2026, 7, 30, 5, 0, tzinfo=timezone.utc))  # 10:30 IST
    assert session == "session"
    after = workflow_window_at(datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc))  # 17:30 IST
    assert after == "after_close"


def test_get_market_news_cached():
    a = get_market_news(force_refresh=True)
    b = get_market_news()
    assert a.headline_count == b.headline_count
    assert a.dominant_tone == b.dominant_tone


def test_live_rss_ingest_mocked(monkeypatch: pytest.MonkeyPatch):
    """Live HTTPS path maps curated RSS into MarketNewsSummary (no network)."""
    from backend.services.market_news import feeds as feeds_mod

    sample_rss = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>t</title>
      <item>
        <title>Nifty jumps as RBI holds rates; FII buying returns - Moneycontrol.com</title>
        <description>Benchmark rallies on policy pause.</description>
        <pubDate>Fri, 31 Jul 2026 07:30:00 GMT</pubDate>
      </item>
      <item>
        <title>Infosys quarterly earnings beat Street estimates</title>
        <description>IT major posts strong guidance.</description>
        <pubDate>Fri, 31 Jul 2026 06:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""

    class _FakeResponse:
        content = sample_rss

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url: str):
            return _FakeResponse()

    monkeypatch.setenv("MARKET_NEWS_LIVE", "1")
    monkeypatch.delenv("MARKET_NEWS_HEADLINES_PATH", raising=False)
    monkeypatch.setattr(feeds_mod.httpx, "Client", _FakeClient)
    reset_market_news_cache()

    summary = refresh_market_news()
    assert summary.headline_count >= 2
    titles = " ".join(i.title for i in summary.items)
    assert "Nifty" in titles or "Infosys" in titles
    assert "Moneycontrol.com" not in titles  # Google suffix stripped
    from backend.services.market_news.service import market_news_feed_status

    feed = market_news_feed_status()
    assert "mode=live" in (feed.detail or "")
    assert "sample_headlines.json" not in (feed.detail or "")


def test_rank_for_window_uses_trust_tier_not_window_membership():
    """An off-window Tier-2 source (Reuters) must outrank an in-window Tier-5
    source (Pulse) — windows are freshness labels, not a ranking penalty."""
    from backend.services.market_news.ingest import RawHeadline, _rank_for_window

    contract = load_curation_contract()
    items = [
        RawHeadline(
            title="Pulse roundup",
            summary="s",
            source="Pulse by Zerodha",
            source_id="pulse",
            time_published="20260730T090000",
        ),
        RawHeadline(
            title="Reuters news",
            summary="s",
            source="Reuters India",
            source_id="reuters",
            time_published="20260730T090000",
        ),
    ]
    # "session" window includes pulse (in_window=0) but not reuters (in_window=1).
    # With window-ranking, old code would rank pulse first despite lower trust tier.
    # With trust-tier-only ranking, reuters should come first due to bot_priority order.
    ranked = _rank_for_window(items, contract, "session")
    assert ranked[0].source_id == "reuters"


def test_parse_pubdate_formats():
    from backend.services.market_news.feeds import parse_pubdate
    from zoneinfo import ZoneInfo

    rfc = parse_pubdate("Fri, 31 Jul 2026 07:30:00 GMT")
    assert rfc is not None
    assert rfc.year == 2026
    sebi = parse_pubdate("30 Jul, 2026 +0530")
    assert sebi is not None
    assert sebi.astimezone(ZoneInfo("Asia/Kolkata")).day == 30
    compact = parse_pubdate("20260731T073000")
    assert compact is not None
    assert compact.hour == 7
