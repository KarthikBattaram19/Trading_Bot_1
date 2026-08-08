"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import pytest

import backend.paper_sim.service as paper_sim_service
import backend.services.learning_service as learning_service_module
import backend.services.recommendation_engine as recommendation_engine_module


@pytest.fixture(autouse=True)
def _market_news_offline_by_default(monkeypatch: pytest.MonkeyPatch):
    """Keep Market_News on the bundled fixture unless a test enables live."""
    monkeypatch.setenv("MARKET_NEWS_LIVE", "0")


@pytest.fixture(autouse=True)
def _reset_process_singletons(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Give every test a clean `paper_sim`/`learning_service` process singleton,
    and never let a default-constructed `LearningService` reach the real
    on-disk store.

    Both `get_paper_engine()` (backend/paper_sim/service.py) and
    `get_learning_service()` (backend/services/learning_service.py) are
    process-global `_x is None` singletons. A test that opens a paper
    position, or leaves a real trade in the default learning-store
    singleton, leaves that state behind for every later test in the same
    process — making results depend on file/test ordering instead of each
    test's own setup.

    Reset the module global to `None` (not call `get_paper_engine()` /
    `get_learning_service()`) so we never force-construct a real
    `PaperEngine`/`LearningService` for tests that never touch either — a
    real `PaperEngine()` builds an `IciciDirectDataOnlyFeed` and a real
    `LearningService()` reads the on-disk default store, neither of which
    a test that doesn't use the singleton should pay for or be affected by.

    Reset *before* each test: that is what actually fixes ordering-
    dependence, since only the state a test starts with can affect its
    outcome. Also reset *after* as a defense-in-depth measure (e.g. so nothing
    lingers into fixture teardown of other autouse fixtures), but the
    before-reset is the one doing the real work.

    Additionally, redirect `learning_service.STORE_PATH` — the module-level
    default `LearningService.__init__` falls back to
    (`self.store_path = store_path or STORE_PATH`) — to a per-test `tmp_path`.
    This closes the coupling for any test (existing or future) that reaches
    a *default-constructed* `LearningService`/`get_learning_service()`
    without passing its own `store_path`: without this, such a test silently
    reads/writes `backend/data/learning_store.json`, the operator's real
    trading ledger. Every current test that legitimately touches
    `LearningService` already passes its own `tmp_path`-backed `store_path`
    explicitly (confirmed by auditing test_learning_seed.py,
    test_learning_store_resilience.py, test_confidence_floor.py,
    test_decisions.py, test_ledger_reconciliation.py, test_paper_sim.py,
    test_scheduler_full_day.py, test_trade_executor.py — none read
    `STORE_PATH` or the bundled real file directly), so this redirect changes
    nothing for them; it only removes the trap for tests that (like
    `test_fully_autonomous_mode_still_executes`) call `is_one_trade_locked()`
    /`has_open_paper_position()` unpinned and fall through to the default.

    Tests that call `get_paper_engine(config=..., feed=..., reset=True)` (or
    monkeypatch `get_paper_engine`/`get_learning_service` directly, e.g. via
    the `_isolated_learning_service` fixture in test_trade_executor.py) are
    unaffected: those either construct their own instance explicitly or
    replace the accessor entirely, so clearing the module global underneath
    them changes nothing they rely on.

    Also resets `recommendation_engine._response_cache` (via the existing
    `reset_recommendation_response_cache_for_tests()` helper) — the same
    class of process-global leaking ambient state across tests, caught via a
    reverse-file-order run: `test_fno_universe.py::test_recommendation_universe_uses_fno_master`
    calls `generate_recommendations()` without `force_refresh`, so it can
    pick up a stale cached response left by an earlier test. This duplicates
    (harmlessly — both are idempotent) the local `_reset_response_cache`
    autouse fixture already in test_recommendation_response_cache.py.
    """
    monkeypatch.setattr(learning_service_module, "STORE_PATH", tmp_path / "learning_store.json")
    paper_sim_service._engine = None
    learning_service_module._learning_service = None
    recommendation_engine_module.reset_recommendation_response_cache_for_tests()
    yield
    paper_sim_service._engine = None
    learning_service_module._learning_service = None
    recommendation_engine_module.reset_recommendation_response_cache_for_tests()
