# backend/tests/test_trading_parameters_options_only_config.py
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = json.loads((ROOT / "config" / "trading_parameters.defaults.json").read_text(encoding="utf-8"))

REMOVED = {
    "max_underlying_price",
    "max_underlying_price_applies_when",
    "exclude_index_underlyings",
    "require_cash_equity_underlying",
    "max_underlying_price_rationale",
    "excluded_index_underlying_symbols",
}


def test_t11_keys_removed_from_defaults():
    f = DEFAULTS["option_universe_filters"]
    for key in REMOVED:
        assert key not in f, key


def test_strategies_are_options_only():
    assert DEFAULTS["strategies"]["simple_volatility"]["hedge_method"] == "options_only"
    assert DEFAULTS["strategies"]["gamma_scalping"]["construction"] == "four_leg_options"
    assert DEFAULTS["gamma_theta_breakeven"]["rehedge_method"] == "adjust_call_put_mix"
