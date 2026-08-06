"""Phase 0 smoke: scaffold, feed_sources (no MCP), ICICI gates, shadow default."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient


def test_no_mcp_registry_module():
    assert importlib.util.find_spec("backend.services.mcp_registry") is None


def test_health_and_feeds(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    monkeypatch.delenv("ALLOW_LIVE_PLACE_ORDER", raising=False)
    from backend.main import app

    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["execution_mode"] == "shadow"
    assert body["phase"] == "1"
    assert body["place_order_enabled"] is False
    assert body.get("local_containers_required") is False
    assert body.get("remote_builder") == "nixpacks"

    feeds = client.get("/api/v1/feeds/status")
    assert feeds.status_code == 200
    sources = feeds.json()
    ids = {s["source_id"] for s in sources}
    assert "icici_direct" in ids
    assert "market_news" in ids
    assert "user-broker-feed" not in ids
    assert "user-nse-india" not in ids
    assert "user-market-news" not in ids

    assert client.get("/api/v1/feeds/mcp").status_code == 404

    paper = client.get("/api/v1/paper-sim/health")
    assert paper.status_code == 200
    paper_body = paper.json()
    assert paper_body["broker_place_order"] is False
    assert paper_body.get("separate_from_icici_live") is True
    assert paper_body.get("module") == "paper_sim"

    bot = client.get("/api/v1/bot/status")
    assert bot.status_code == 200
    bot_body = bot.json()
    assert bot_body["execution_mode"] == "shadow"
    assert bot_body.get("place_order_enabled") is False


def test_recommendation_uses_feed_sources(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    from backend.integrations.icici_direct.instrument_master import (
        InstrumentMaster,
        reset_instrument_master_for_tests,
    )
    from backend.main import app
    from backend.services.universe_enrichment import (
        EnrichmentStats,
        LiveMarks,
        UniverseEnricher,
        reset_universe_enricher_for_tests,
    )

    reset_instrument_master_for_tests()
    reset_universe_enricher_for_tests()
    master = InstrumentMaster()
    master.load_rows(
        [
            {
                "exch_seg": "NFO",
                "ShortName": "STABAN",
                "Token": "1",
                "InstrumentName": "OPTSTK",
                "ExpiryDate": "28-Mar-2024",
                "StrikePrice": "800",
                "OptionType": "CE",
                "ExchangeCode": "SBIN",
                "LotSize": "1500",
            }
        ]
    )
    monkeypatch.setattr(
        "backend.services.recommendation_engine.get_instrument_master",
        lambda: master,
    )

    async def _noop_ensure(self, *, max_age_sec=None):  # noqa: ANN001
        return master.count

    monkeypatch.setattr(
        "backend.integrations.icici_direct.market_data.IciciDirectMarketDataAdapter.ensure_instruments",
        _noop_ensure,
    )

    async def _fake_enrich_many(self, symbols, **_kwargs):  # noqa: ANN001
        marks = {
            s.upper(): LiveMarks(
                symbol=s.upper(),
                und_price=800.0,
                atm_premium_inr=50.0,
                volume=5000,
                open_interest=20000,
                spread_pct=1.0,
                dte=21,
                iv_annualized=0.22,
            )
            for s in symbols
        }
        return marks, EnrichmentStats(requested=len(symbols), live_ok=len(symbols))

    monkeypatch.setattr(UniverseEnricher, "enrich_many", _fake_enrich_many)
    monkeypatch.setattr(
        "backend.services.recommendation_engine.get_universe_enricher",
        lambda cfg=None: UniverseEnricher(instruments=master, min_interval_ms=1),
    )

    client = TestClient(app)
    res = client.get("/api/v1/recommendations")
    assert res.status_code == 200
    data = res.json()
    assert "feed_sources" in data
    assert "mcp_sources" not in data
    assert "market_news" in data
    assert data["universe_scanned"] >= 1
    assert any("Marks coverage" in n for n in data.get("analysis_notes", []))


def test_place_order_disabled_in_shadow(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    monkeypatch.delenv("ALLOW_LIVE_PLACE_ORDER", raising=False)
    import asyncio

    from backend.integrations.icici_direct.client import IciciDirectAPIError, IciciDirectClient
    from backend.integrations.registry import place_order_enabled

    assert place_order_enabled() is False
    client = IciciDirectClient(api_key="test", api_secret="test")

    async def _call():
        await client.place_order({"quantity": "1"})

    with pytest.raises(IciciDirectAPIError, match="place_order disabled"):
        asyncio.run(_call())


def test_broker_test_requires_credentials(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    for key in (
        "ICICI_DIRECT_API_KEY",
        "ICICI_DIRECT_API_SECRET",
        "ICICI_DIRECT_SESSION_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    from backend.integrations.icici_direct.session_manager import reset_session_manager_for_tests
    from backend.integrations.credential_vault import get_vault

    reset_session_manager_for_tests()
    get_vault()._bundles.clear()  # noqa: SLF001 — test isolation

    from backend.main import app

    client = TestClient(app)
    res = client.post("/api/v1/config/integrations/broker/test")
    assert res.status_code == 400
    assert "credentials" in res.json()["detail"].lower()
