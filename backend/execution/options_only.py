from __future__ import annotations
from typing import Any, Sequence

OPTIONS_ONLY_REQUIRED = "OPTIONS_ONLY_REQUIRED"

class OptionsOnlyViolation(ValueError):
    def __init__(self, message: str = "Call/Put legs only; stock/underlying legs are not allowed"):
        super().__init__(message)
        self.code = OPTIONS_ONLY_REQUIRED

def leg_type(leg: Any) -> str:
    if isinstance(leg, dict):
        raw = leg.get("type") or leg.get("option_type") or ""
    else:
        raw = getattr(leg, "type", None) or getattr(leg, "option_type", None) or ""
    return str(raw).strip().lower()

def assert_options_only_legs(legs: Sequence[Any]) -> None:
    for leg in legs:
        if leg_type(leg) == "stock":
            raise OptionsOnlyViolation()

def assert_options_only_strategy_config(
    *, hedge_method: str | None = None, construction: str | None = None
) -> None:
    if hedge_method is not None and str(hedge_method).strip().lower() == "stock":
        raise OptionsOnlyViolation("hedge_method=stock is not allowed (options-only hard lock)")
    if construction is not None and str(construction).strip().lower() == "calls_stock":
        raise OptionsOnlyViolation("construction=calls_stock is not allowed (options-only hard lock)")

def structure_is_options_only(
    legs: Sequence[Any] | None = None,
    *,
    hedge_method: str | None = None,
    construction: str | None = None,
) -> bool:
    try:
        if legs is not None:
            assert_options_only_legs(legs)
        assert_options_only_strategy_config(hedge_method=hedge_method, construction=construction)
    except OptionsOnlyViolation:
        return False
    return True
