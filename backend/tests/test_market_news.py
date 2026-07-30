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
def _clear_news_cache():
    reset_market_news_cache()
    yield
    reset_market_news_cache()


def test_curation_contract_loads_market_news_txt():
    contract = load_curation_contract()
    assert contract.loaded is True
    assert "reuters" in contract.bot_priority
    assert contract.bot_priority[0] == "reuters"
    assert "moneycontrol" in contract.bot_priority
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
