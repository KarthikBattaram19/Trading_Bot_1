"""Phase 1.7 — transaction cost model unit tests (§9.4)."""

from __future__ import annotations

import pytest

from backend.quant.costs.transaction_cost import (
    ImpactTier,
    LegCostInput,
    TransactionCostConfig,
    cost_gate_passes,
    edge_after_costs,
    estimate_from_mapping,
    estimate_stock_hedge_cost,
    estimate_transaction_cost,
    market_impact_bps,
    net_hedge_edge_after_costs,
    stat_arb_entry_z_with_cost_buffer,
)


def test_equity_slippage_is_five_bps_default():
    cfg = TransactionCostConfig()
    assert cfg.equity_slippage_bps == pytest.approx(5.0)  # 0.05%
    result = estimate_stock_hedge_cost(quantity=100, spot=500.0, config=cfg)
    # slippage = 500*100 * 0.0005 = 25
    assert result.cost_slippage == pytest.approx(25.0)
    assert result.total_transaction_cost > 25.0  # + commission + spread + impact


def test_option_slippage_pct_of_mid():
    cfg = TransactionCostConfig(option_slippage_pct_of_mid=0.02)  # 2%
    result = estimate_transaction_cost(
        [
            LegCostInput(
                kind="option",
                quantity=25,
                mid_price=10.0,
                lotsize=25,
            )
        ],
        config=cfg,
    )
    assert result.cost_slippage == pytest.approx(25 * 10.0 * 0.02)


def test_half_spread_from_bid_ask():
    result = estimate_transaction_cost(
        [
            LegCostInput(
                kind="option",
                quantity=25,
                mid_price=10.0,
                bid=9.8,
                ask=10.2,
                lotsize=25,
            )
        ]
    )
    # half-spread = 0.2 per share × 25 = 5
    assert result.cost_spread == pytest.approx(5.0)
    assert result.legs[0].spread_pct == pytest.approx(4.0)  # (0.4/10)*100
    assert result.liquidity_ok is False  # > 2% default max_spread


def test_liquidity_ok_when_spread_within_cap():
    result = estimate_transaction_cost(
        [
            LegCostInput(
                kind="option",
                quantity=25,
                mid_price=100.0,
                bid=99.5,
                ask=100.5,
                lotsize=25,
            )
        ]
    )
    assert result.legs[0].spread_pct == pytest.approx(1.0)
    assert result.liquidity_ok is True


def test_round_trip_doubles_one_way_components():
    one = estimate_stock_hedge_cost(quantity=50, spot=200.0, round_trip=False)
    rt = estimate_stock_hedge_cost(quantity=50, spot=200.0, round_trip=True)
    assert rt.cost_commissions == pytest.approx(one.cost_commissions * 2)
    assert rt.cost_slippage == pytest.approx(one.cost_slippage * 2)
    assert rt.round_trip is True


def test_market_impact_tiers():
    cfg = TransactionCostConfig(
        impact_tiers=(
            ImpactTier(max_notional_inr=10_000.0, impact_bps=1.0),
            ImpactTier(max_notional_inr=float("inf"), impact_bps=5.0),
        )
    )
    assert market_impact_bps(5_000.0, cfg) == 1.0
    assert market_impact_bps(50_000.0, cfg) == 5.0


def test_net_hedge_edge_and_cost_gate():
    edge = net_hedge_edge_after_costs(
        expected_gamma_pnl=100.0,
        expected_theta_loss=40.0,
        total_transaction_cost=30.0,
    )
    assert edge == pytest.approx(30.0)
    assert cost_gate_passes(net_hedge_edge=edge, min_edge_threshold=0.0)
    assert not cost_gate_passes(net_hedge_edge=0.0, min_edge_threshold=0.0)
    assert edge_after_costs(gross_edge=50.0, total_transaction_cost=60.0) < 0


def test_stat_arb_z_buffer():
    z = stat_arb_entry_z_with_cost_buffer(base_entry_z=2.0)
    assert z == pytest.approx(2.25)


def test_estimate_from_mapping_and_rehedge_est():
    cfg = TransactionCostConfig(expected_rehedge_count=2, rehedge_cost_multiplier=1.0)
    result = estimate_from_mapping(
        [{"kind": "equity", "quantity": 100, "mark_ltp": 100.0}],
        config=cfg,
    )
    assert result.cost_rehedge_est > 0
    assert result.total_transaction_cost > result.cost_commissions
