from __future__ import annotations

import inspect
from copy import deepcopy

from backend.models.recommendations import StrategySelectionLogic, StrategyType
from backend.services.recommendation_engine import (
    InstrumentCandidate,
    _build_universe,
    _demo_universe,
    _evaluate_gates,
    _hedge_insight,
    _load_config,
    _prefer_options_only_for_high_spot,
    _rank_symbols_for_enrichment,
    _stub_candidate,
    _structure_uses_underlying,
)
from backend.services.signals import seed_atm_history_prior


def _strategy(strategy_type: StrategyType = StrategyType.simple_volatility) -> StrategySelectionLogic:
    return StrategySelectionLogic(
        selected_strategy=strategy_type,
        entry_mode="cheap_vol_mode",
        scenario_tag="test",
        cross_strategy_matrix_ref="test",
        primary_signal="test signal",
    )


def _candidate(**overrides) -> InstrumentCandidate:
    volume = int(overrides.get("volume", 15200))
    open_interest = int(overrides.get("open_interest", 28000))
    base = dict(
        symbol="NIFTY",
        und_price=1680.0,
        iv_annualized=0.20,
        garch_forecast=0.30,
        iv_z_score=None,
        days_to_earnings=None,
        atm_premium_inr=210.0,
        volume=volume,
        open_interest=open_interest,
        spread_pct=0.4,
        dte=25,
        realized_vol_intraday=0.015,
        garch_distorted=False,
        price_history=[1680.0] * 30,
        atm_history_prior=seed_atm_history_prior(volume, open_interest),
    )
    base.update(overrides)
    if "atm_history_prior" not in overrides and (
        "volume" in overrides or "open_interest" in overrides
    ):
        base["atm_history_prior"] = seed_atm_history_prior(
            int(base["volume"]), int(base["open_interest"])
        )
    return InstrumentCandidate(**base)


def test_high_spot_index_options_only_candidate_has_no_t11_gate():
    cfg = _load_config()

    gates = _evaluate_gates(_candidate(), cfg, includes_underlying=False)

    assert all(g.gate_id != "T11" for g in gates)
    failed = [f"{g.gate_id}:{g.detail}" for g in gates if not g.passed]
    assert not failed, failed


def test_structure_uses_underlying_stays_false_even_for_stock_config():
    cfg = deepcopy(_load_config())
    cfg["strategies"]["simple_volatility"]["hedge_method"] = "stock"
    cfg["strategies"]["gamma_scalping"]["construction"] = "calls_stock"
    cfg["strategies"]["vega_scalping"]["hedge_method"] = "stock"

    assert _structure_uses_underlying(_strategy(StrategyType.simple_volatility), cfg) is False
    assert _structure_uses_underlying(_strategy(StrategyType.gamma_scalping), cfg) is False
    assert _structure_uses_underlying(_strategy(StrategyType.vega_scalping), cfg) is False


def test_high_spot_preference_no_longer_rewrites_strategy():
    cfg = deepcopy(_load_config())
    cfg["option_universe_filters"]["max_underlying_price"] = 1000
    cfg["strategies"]["simple_volatility"]["hedge_method"] = "stock"
    strategy = _strategy()

    updated, forced = _prefer_options_only_for_high_spot(_candidate(), strategy, cfg)

    assert updated == strategy
    assert forced is False


def test_hedge_insight_never_mentions_stock_or_futures():
    for strategy_type in (
        StrategyType.simple_volatility,
        StrategyType.gamma_scalping,
        StrategyType.vega_scalping,
    ):
        insight = _hedge_insight(_strategy(strategy_type), options_only=True)

        assert "stock" not in insight.structure_note.lower()
        assert "futures" not in insight.structure_note.lower()


def test_demo_fixture_helpers_are_tagged_and_never_called_from_build_universe():
    """§3.3/§5.1 guard: the fabricated demo/stub fixture builders must never be

    reachable from the production universe-building path. `_build_universe()` is
    the only function that feeds real recommendation ranking (via
    `_candidate_from_live`), so its source must never reference the demo/stub
    helpers — this turns the "confirmed by reading the full function" invariant
    from the audit into a check that fails loudly if a future refactor
    reintroduces the reference instead of relying on docstrings alone.
    """
    forbidden = {"_candidate_from_spec", "_demo_universe", "_stub_candidate", "_DEMO_SPECS"}
    source = inspect.getsource(_build_universe)
    referenced = {name for name in forbidden if name in source}
    assert not referenced, (
        f"_build_universe() must never call demo/stub fixture helpers, "
        f"found references to: {sorted(referenced)}"
    )

    # Sanity: the fixture helpers really do fabricate non-live marks, so the
    # guard above is checking something real, not a vacuous name that no
    # longer exists.
    demo_candidates = _demo_universe()
    assert demo_candidates, "demo fixture spec list must not be empty"
    assert all(c.marks_source == "demo" for c in demo_candidates)

    stub = _stub_candidate("NIFTY", _load_config())
    assert stub.marks_source == "stub"

    # And the real production path builds candidates the opposite way — via
    # `_candidate_from_live`, never the fixture spec builders.
    assert "_candidate_from_live" in source


def test_rank_symbols_for_enrichment_priority_names_always_come_first():
    priority = {"NIFTY": 0, "BANKNIFTY": 1}
    ranked = _rank_symbols_for_enrichment(
        ["ZEEL", "BANKNIFTY", "AAPL_NOT_REAL", "NIFTY"],
        priority=priority,
        liquidity={"AAPL_NOT_REAL": 999_999.0},
    )
    assert ranked[:2] == ["NIFTY", "BANKNIFTY"]


def test_rank_symbols_for_enrichment_orders_non_priority_names_by_liquidity_desc():
    ranked = _rank_symbols_for_enrichment(
        ["ZEEL", "SBIN", "TCS"],
        priority={},
        liquidity={"ZEEL": 100.0, "SBIN": 5000.0, "TCS": 2000.0},
    )
    assert ranked == ["SBIN", "TCS", "ZEEL"]


def test_rank_symbols_for_enrichment_falls_back_to_alphabetical_with_no_history():
    """A cold liquidity store (or an unenriched name) must not perturb ordering —
    same alphabetical fallback the enrichment budget used before this change."""
    ranked = _rank_symbols_for_enrichment(
        ["ZEEL", "SBIN", "TCS"],
        priority={},
        liquidity={},
    )
    assert ranked == ["SBIN", "TCS", "ZEEL"]


def test_rank_symbols_for_enrichment_mixes_liquid_and_unknown_names():
    ranked = _rank_symbols_for_enrichment(
        ["ZEEL", "SBIN", "TCS"],
        priority={},
        liquidity={"SBIN": 5000.0},
    )
    # SBIN has real liquidity history and sorts first; ZEEL/TCS have no
    # history (liquidity 0.0 default) and fall back to alphabetical.
    assert ranked == ["SBIN", "TCS", "ZEEL"]
