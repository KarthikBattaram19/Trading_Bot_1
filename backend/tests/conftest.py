"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _market_news_offline_by_default(monkeypatch: pytest.MonkeyPatch):
    """Keep Market_News on the bundled fixture unless a test enables live."""
    monkeypatch.setenv("MARKET_NEWS_LIVE", "0")


@pytest.fixture(autouse=True)
def _isolated_kill_switch_state(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point kill-switch persistence at a throwaway file, not the real one."""
    from backend.services import kill_switch_state

    state = kill_switch_state.KillSwitchState(store_path=tmp_path / "kill_switch_state.json")
    monkeypatch.setattr(kill_switch_state, "_kill_switch_state", state)
