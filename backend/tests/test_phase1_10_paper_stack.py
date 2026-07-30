"""Phase 1.10: EXECUTION_MODE=paper on Railway — never live (M-01)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.integrations.base import ExecutionMode
from backend.integrations.registry import (
    get_execution_mode,
    get_requested_execution_mode,
    is_paper_deploy_stack,
    paper_stack_guard_status,
    place_order_enabled,
    reset_paper_stack_alert_for_tests,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAILWAY_PAPER_ENV = REPO_ROOT / "infra" / "env" / "railway.paper.env.example"


def _clear_railway_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "DEPLOY_STACK",
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_PROJECT_ID",
        "RAILWAY_SERVICE_ID",
        "RAILWAY_STATIC_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_railway_paper_env_example_confirms_paper_not_live():
    text = RAILWAY_PAPER_ENV.read_text(encoding="utf-8")
    assert "DEPLOY_STACK=paper" in text
    assignments: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        assignments[key.strip()] = value.strip()
    assert assignments.get("EXECUTION_MODE") == "paper"
    assert assignments.get("DEPLOY_STACK") == "paper"
    assert assignments.get("ALLOW_LIVE_PLACE_ORDER") == "false"
    assert "Never set EXECUTION_MODE=live" in text


def test_paper_stack_defaults_to_paper_when_mode_unset(monkeypatch):
    reset_paper_stack_alert_for_tests()
    _clear_railway_markers(monkeypatch)
    monkeypatch.setenv("DEPLOY_STACK", "paper")
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    monkeypatch.delenv("ALLOW_LIVE_PLACE_ORDER", raising=False)

    assert get_requested_execution_mode() == ExecutionMode.paper
    assert get_execution_mode() == ExecutionMode.paper
    assert place_order_enabled() is False


def test_paper_stack_detected_from_railway_env(monkeypatch):
    reset_paper_stack_alert_for_tests()
    _clear_railway_markers(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("EXECUTION_MODE", "paper")
    monkeypatch.delenv("ALLOW_LIVE_PLACE_ORDER", raising=False)

    assert is_paper_deploy_stack() is True
    assert get_execution_mode() == ExecutionMode.paper
    assert place_order_enabled() is False


def test_m01_live_on_railway_coerced_to_paper(monkeypatch):
    reset_paper_stack_alert_for_tests()
    _clear_railway_markers(monkeypatch)
    monkeypatch.setenv("DEPLOY_STACK", "paper")
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("ALLOW_LIVE_PLACE_ORDER", "true")

    assert get_requested_execution_mode() == ExecutionMode.live
    assert get_execution_mode() == ExecutionMode.paper
    assert place_order_enabled() is False
    guard = paper_stack_guard_status()
    assert guard["live_blocked"] is True
    assert guard["requested_execution_mode"] == "live"
    assert guard["execution_mode"] == "paper"


def test_live_allowed_only_off_paper_stack(monkeypatch):
    reset_paper_stack_alert_for_tests()
    _clear_railway_markers(monkeypatch)
    monkeypatch.setenv("DEPLOY_STACK", "gcp")
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("ALLOW_LIVE_PLACE_ORDER", "true")

    assert is_paper_deploy_stack() is False
    assert get_execution_mode() == ExecutionMode.live
    assert place_order_enabled() is True


def test_health_exposes_paper_stack_guard(monkeypatch):
    reset_paper_stack_alert_for_tests()
    _clear_railway_markers(monkeypatch)
    monkeypatch.setenv("DEPLOY_STACK", "paper")
    monkeypatch.setenv("EXECUTION_MODE", "paper")
    monkeypatch.delenv("ALLOW_LIVE_PLACE_ORDER", raising=False)
    from backend.main import app

    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["phase"] == "1"
    assert body["execution_mode"] == "paper"
    assert body["deploy_stack"] == "paper"
    assert body["place_order_enabled"] is False
    assert body["live_blocked"] is False

    bot = client.get("/api/v1/bot/status")
    assert bot.status_code == 200
    bot_body = bot.json()
    assert bot_body["execution_mode"] == "paper"
    assert bot_body["deploy_stack"] == "paper"
    assert bot_body["phase"] == "1"

    paper = client.get("/api/v1/paper-sim/health")
    assert paper.status_code == 200
    paper_body = paper.json()
    assert paper_body["phase"] == "1.10"
    assert paper_body["broker_place_order"] is False
    assert paper_body.get("railway_never_live") is True


def test_health_live_blocked_when_misconfigured(monkeypatch):
    reset_paper_stack_alert_for_tests()
    _clear_railway_markers(monkeypatch)
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "fake-project")
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("ALLOW_LIVE_PLACE_ORDER", "true")
    from backend.main import app

    client = TestClient(app)
    body = client.get("/health").json()
    assert body["requested_execution_mode"] == "live"
    assert body["execution_mode"] == "paper"
    assert body["deploy_stack"] == "paper"
    assert body["live_blocked"] is True
    assert body["place_order_enabled"] is False
