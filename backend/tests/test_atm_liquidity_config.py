# backend/tests/test_atm_liquidity_config.py
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / "config" / "trading_parameters.defaults.json"


def test_liquidity_defaults_match_relative_gates_spec():
    cfg = json.loads(DEFAULTS.read_text(encoding="utf-8"))
    f = cfg["option_universe_filters"]
    assert f["min_volume"] == 2000
    assert f["min_open_interest"] == 20000
    assert f["max_spread_pct"] == 0.5
    assert f["volume_vs_avg_min_ratio"] == 1.5
    assert f["oi_vs_avg_min_ratio"] == 1.3
    assert f["atm_history_lookback_days"] == 20
    assert f["atm_history_min_days"] == 10
    assert f["atm_liquidity_agg"] == "min_ce_pe"
    assert f["spread_agg"] == "max_ce_pe"
    for key in ("simple_volatility", "gamma_scalping", "vega_scalping"):
        sel = cfg["strategies"][key]["option_selection"]
        assert sel["min_volume"] == 2000
        assert sel["min_open_interest"] == 20000
        assert sel["max_spread_pct"] == 0.5
