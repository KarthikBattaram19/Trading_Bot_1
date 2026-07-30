"""OSS workbook parity tests — Black–Scholes–Merton vs Docs/OSS (1).xlsm.

CI gate per Docs/architecture.md §8.5.12 / §22.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.quant.pricing.bsm import (
    BSMInputs,
    black_scholes_merton_price,
    mark_strategy,
    option_greeks,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "oss" / "iron_condor.json"
)


@pytest.fixture(scope="module")
def iron_condor() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _rel_error(actual: float, expected: float) -> float:
    if expected == 0:
        return abs(actual)
    return abs(actual - expected) / abs(expected)


def test_fixture_matches_workbook_asof_date(iron_condor: dict) -> None:
    gp = iron_condor["global_params"]
    assert gp["eval_date"] == "2024-01-04"
    assert gp["eval_time"] == "10:35:00"
    assert gp["eval_datetime"] == "2024-01-04T10:35:00+05:30"
    assert gp["day_count"] == 365
    assert gp["default_contract_multiplier"] == 100  # OSS US fixture only


@pytest.mark.parametrize("leg_index", [0, 1, 2, 3])
def test_per_share_mark_within_one_cent(iron_condor: dict, leg_index: int) -> None:
    gp = iron_condor["global_params"]
    leg = iron_condor["legs"][leg_index]
    inputs = BSMInputs.from_api(
        und_price=gp["und_price"],
        strike=leg["strike"],
        days_to_expiry=leg["days_to_expiry"],
        int_rate=gp["int_rate"],
        div_yield=gp["div_yield"],
        volatility=gp["volatility"],
        option_type=leg["type"],
        day_count=gp["day_count"],
    )
    price = black_scholes_merton_price(inputs)
    tol = iron_condor["tolerances"]["price_abs"]
    assert abs(price - leg["mark_price"]) <= tol


def test_iron_condor_strategy_totals_within_rel_tol(iron_condor: dict) -> None:
    marked = mark_strategy(
        global_params=iron_condor["global_params"],
        legs=iron_condor["legs"],
    )
    expected = iron_condor["totals"]
    greek_tol = iron_condor["tolerances"]["greek_rel"]
    pnl_tol = iron_condor["tolerances"]["pnl_rel"]

    assert _rel_error(marked.total_pnl, expected["total_pnl"]) <= pnl_tol
    assert _rel_error(marked.total_delta, expected["total_delta"]) <= greek_tol
    assert _rel_error(marked.total_gamma, expected["total_gamma"]) <= greek_tol
    assert _rel_error(marked.total_theta, expected["total_theta"]) <= greek_tol
    assert _rel_error(marked.total_vega, expected["total_vega"]) <= greek_tol
    assert _rel_error(marked.total_rho, expected["total_rho"]) <= greek_tol
    assert _rel_error(marked.total_value, expected["total_value"]) <= pnl_tol
    assert abs(marked.total_initial_cf - expected["total_initial_cf"]) < 1e-9


def test_per_leg_scaled_greeks_match_workbook(iron_condor: dict) -> None:
    marked = mark_strategy(
        global_params=iron_condor["global_params"],
        legs=iron_condor["legs"],
    )
    greek_tol = iron_condor["tolerances"]["greek_rel"]
    for actual, expected in zip(marked.legs, iron_condor["legs"], strict=True):
        assert abs(actual.mark_price - expected["mark_price"]) <= 0.01
        assert _rel_error(actual.delta, expected["delta"]) <= greek_tol
        assert _rel_error(actual.gamma, expected["gamma"]) <= greek_tol
        assert _rel_error(actual.theta, expected["theta"]) <= greek_tol
        assert _rel_error(actual.vega, expected["vega"]) <= greek_tol
        assert _rel_error(actual.rho, expected["rho"]) <= greek_tol
        assert _rel_error(actual.pnl, expected["pnl"]) <= greek_tol


def test_stock_leg_delta_convention() -> None:
    marked = mark_strategy(
        global_params={
            "und_price": 202.38,
            "div_yield": 0.0,
            "int_rate": 4.0,
            "volatility": 20.0,
            "flat_volatility": True,
            "display_mode": "total",
            "default_contract_multiplier": 100,
            "default_stock_multiplier": 1,
            "day_count": 365,
        },
        legs=[
            {
                "leg_id": 1,
                "position": 1000,
                "type": "stock",
                "initial_price": 202.38,
                "contract_multiplier": 1,
            }
        ],
    )
    leg = marked.legs[0]
    assert leg.mark_price == pytest.approx(202.38)
    assert leg.delta == pytest.approx(1000.0)
    assert leg.gamma == 0.0
    assert leg.vega == 0.0
    assert leg.theta == 0.0
    assert leg.rho == 0.0
    assert leg.initial_cf == pytest.approx(-202_380.0)


def test_expired_option_greeks_zero() -> None:
    inputs = BSMInputs.from_api(
        und_price=100.0,
        strike=100.0,
        days_to_expiry=0.0,
        int_rate=4.0,
        div_yield=0.0,
        volatility=20.0,
        option_type="call",
    )
    greeks = option_greeks(inputs)
    assert greeks["gamma"] == 0.0
    assert greeks["theta"] == 0.0
    assert greeks["vega"] == 0.0
    assert greeks["rho"] == 0.0
