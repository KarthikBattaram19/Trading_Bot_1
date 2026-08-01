import pytest
from backend.execution.options_only import (
    OPTIONS_ONLY_REQUIRED,
    OptionsOnlyViolation,
    assert_options_only_legs,
    assert_options_only_strategy_config,
    structure_is_options_only,
)

def test_rejects_stock_leg():
    with pytest.raises(OptionsOnlyViolation) as ei:
        assert_options_only_legs([{"type": "call"}, {"type": "stock"}])
    assert ei.value.code == OPTIONS_ONLY_REQUIRED

def test_allows_call_put():
    assert_options_only_legs([{"type": "call"}, {"type": "put"}])
    assert structure_is_options_only([{"type": "CALL"}, {"type": "Put"}]) is True

def test_rejects_stock_hedge_config():
    with pytest.raises(OptionsOnlyViolation):
        assert_options_only_strategy_config(hedge_method="stock")
    with pytest.raises(OptionsOnlyViolation):
        assert_options_only_strategy_config(construction="calls_stock")
    assert_options_only_strategy_config(hedge_method="options_only", construction="four_leg_options")

