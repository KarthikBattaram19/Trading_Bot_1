from __future__ import annotations

from copy import deepcopy

from backend.models.recommendations import StrategySelectionLogic, StrategyType
from backend.services.recommendation_engine import (
    InstrumentCandidate,
    _evaluate_gates,
    _hedge_insight,
    _load_config,
    _prefer_options_only_for_high_spot,
    _structure_uses_underlying,
)


def _strategy(strategy_type: StrategyType = StrategyType.simple_volatility) -> StrategySelectionLogic:
    return StrategySelectionLogic(
        selected_strategy=strategy_type,
        entry_mode="cheap_vol_mode",
        scenario_tag="test",
        cross_strategy_matrix_ref="test",
        primary_signal="test signal",
    )


def _candidate(**overrides) -> InstrumentCandidate:
    base = dict(
        symbol="NIFTY",
        und_price=1680.0,
        iv_annualized=0.20,
        garch_forecast=0.30,
        iv_z_score=None,
        days_to_earnings=None,
        atm_premium_inr=210.0,
        volume=15200,
        open_interest=28000,
        spread_pct=1.1,
        dte=25,
        realized_vol_intraday=0.015,
        garch_distorted=False,
        price_history=[1680.0] * 30,
    )
    base.update(overrides)
    return InstrumentCandidate(**base)


def test_high_spot_index_options_only_candidate_has_no_t11_gate():
    cfg = _load_config()

    gates = _evaluate_gates(_candidate(), cfg, includes_underlying=False)

    assert all(g.gate_id != "T11" for g in gates)
    assert all(g.passed for g in gates)


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
