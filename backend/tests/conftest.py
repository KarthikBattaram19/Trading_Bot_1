"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _market_news_offline_by_default(monkeypatch: pytest.MonkeyPatch):
    """Keep Market_News on the bundled fixture unless a test enables live."""
    monkeypatch.setenv("MARKET_NEWS_LIVE", "0")
