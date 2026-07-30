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
    assert "kill_switch_armed" in bot_body
    assert bot_body.get("place_order_enabled") is False

    pause = client.post("/api/v1/bot/pause")
    assert pause.status_code == 200
    assert pause.json()["kill_switch_armed"] is True
    assert client.get("/api/v1/bot/status").json()["kill_switch_armed"] is True
    resume = client.post("/api/v1/bot/resume")
    assert resume.status_code == 200
    assert resume.json()["kill_switch_armed"] is False


def test_recommendation_uses_feed_sources(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    from backend.main import app

    client = TestClient(app)
    res = client.get("/api/v1/recommendations")
    assert res.status_code == 200
    data = res.json()
    assert "feed_sources" in data
    assert "mcp_sources" not in data
    assert "market_news" in data


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
