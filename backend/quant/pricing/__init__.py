"""Option pricing engines (OSS / Black–Scholes–Merton)."""

from backend.quant.pricing.bsm import (
    BSMInputs,
    LegResult,
    StrategyMarkResult,
    black_scholes_merton_price,
    mark_strategy,
    option_greeks,
)

__all__ = [
    "BSMInputs",
    "LegResult",
    "StrategyMarkResult",
    "black_scholes_merton_price",
    "mark_strategy",
    "option_greeks",
]
