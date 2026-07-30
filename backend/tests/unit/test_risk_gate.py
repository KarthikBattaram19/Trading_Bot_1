"""Phase 1.7 — pre-trade risk gate thresholds (§11.4)."""

from __future__ import annotations

import pytest

from backend.execution.risk_gate import (
    PreTradeContext,
    PreTradeThresholds,
    evaluate_pre_trade_gate,
    price_on_tick_grid,
    quantity_multiple_of_lotsize,
)
from backend.quant.risk.greeks_limits import GreeksLimitThresholds, check_greeks_limits


def test_quantity_lotsize_and_tick_grid():
    assert quantity_multiple_of_lotsize(75, 25)
    assert quantity_multiple_of_lotsize(50, 25)
    assert not quantity_multiple_of_lotsize(40, 25)
    assert not quantity_multiple_of_lotsize(0, 25)
    assert price_on_tick_grid(100.05, 0.05)
    assert not price_on_tick_grid(100.03, 0.05)


def test_greeks_limits_pass_and_fail():
    thr = GreeksLimitThresholds(
        max_abs_total_delta=10.0,
        max_abs_total_gamma=5.0,
        max_abs_total_vega=100.0,
        min_total_theta=-50.0,
    )
    ok = check_greeks_limits(
        total_delta=1.0,
        total_gamma=2.0,
        total_vega=10.0,
        total_theta=-20.0,
        thresholds=thr,
    )
    assert ok.passed
    bad_delta = check_greeks_limits(
        total_delta=11.0,
        total_gamma=2.0,
        total_vega=10.0,
        total_theta=-20.0,
        thresholds=thr,
    )
    assert not bad_delta.passed
    assert "total_delta" in bad_delta.failures
    bad_theta = check_greeks_limits(
        total_delta=1.0,
        total_gamma=2.0,
        total_vega=10.0,
        total_theta=-51.0,
        thresholds=thr,
    )
    assert "total_theta" in bad_theta.failures


def test_kill_switch_blocks():
    result = evaluate_pre_trade_gate(PreTradeContext(kill_switch_armed=True))
    assert not result.passed
    assert "kill_switch" in result.failed_ids


def test_fresh_feeds_and_confidence_gates():
    thr = PreTradeThresholds(min_confidence=0.70)
    result = evaluate_pre_trade_gate(
        PreTradeContext(
            feeds_fresh=True,
            kill_switch_armed=False,
            confidence=0.65,
            is_discretionary=True,
            buying_power_ok=True,
        ),
        thresholds=thr,
    )
    assert not result.passed
    assert "confidence" in result.failed_ids

    ok = evaluate_pre_trade_gate(
        PreTradeContext(
            feeds_fresh=True,
            kill_switch_armed=False,
            confidence=0.85,
            is_discretionary=True,
            buying_power_ok=True,
            rag_faithfulness=0.90,
            regime="cheap_vol",
            one_trade_scope_clear=True,
        ),
        thresholds=thr,
    )
    assert ok.passed


def test_transaction_cost_gate_on_hedge():
    fail = evaluate_pre_trade_gate(
        PreTradeContext(
            kill_switch_armed=False,
            is_hedge=True,
            net_hedge_edge=0.0,
        )
    )
    assert "transaction_cost" in fail.failed_ids

    passed = evaluate_pre_trade_gate(
        PreTradeContext(
            kill_switch_armed=False,
            is_hedge=True,
            net_hedge_edge=12.5,
        )
    )
    assert passed.passed or "transaction_cost" not in passed.failed_ids


def test_regime_and_lot_tick_checks():
    blocked = evaluate_pre_trade_gate(
        PreTradeContext(
            kill_switch_armed=False,
            is_discretionary=True,
            regime="high_vol_stress",
            confidence=0.9,
            rag_faithfulness=0.9,
            one_trade_scope_clear=True,
        )
    )
    assert "regime" in blocked.failed_ids

    lot_fail = evaluate_pre_trade_gate(
        PreTradeContext(
            kill_switch_armed=False,
            quantity=40,
            lotsize=25,
            limit_price=100.03,
            tick_size=0.05,
        )
    )
    assert "lotsize" in lot_fail.failed_ids
    assert "tick_size" in lot_fail.failed_ids


def test_spread_liquidity_gate():
    result = evaluate_pre_trade_gate(
        PreTradeContext(kill_switch_armed=False, spread_pct=3.5),
        thresholds=PreTradeThresholds(max_spread_pct=2.0),
    )
    assert "liquidity_spread" in result.failed_ids


def test_gate_result_as_dict():
    result = evaluate_pre_trade_gate(PreTradeContext(kill_switch_armed=False))
    payload = result.as_dict()
    assert payload["passed"] is True
    assert isinstance(payload["checks"], list)
    assert payload["checks"][0]["id"]
