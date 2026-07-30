"""Black–Scholes–Merton pricing and Greeks (Macroption OSS conventions).

Aligned with ``Docs/OSS_Guide (1).pdf`` §§8–9 and ``Docs/architecture.md`` §8.5.7:

- European exercise, continuous dividend yield ``q``
- Vega / rho per **1 percentage point** (1% σ or 1% r)
- Theta per **one calendar day** (365-day year)
- ``display_mode=total`` scales Value / P/L / Greeks by ``position × multiplier``

OSS parity fixture uses US-style ``default_contract_multiplier=100``.
India NFO paper/live must supply the ICICI Direct instrument-master ``lotsize`` per leg
instead of copying that default blindly.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, log, sqrt
from statistics import NormalDist
from typing import Any, Iterable, Literal, Mapping

_NORM = NormalDist()
_N = _NORM.cdf
_PHI = _NORM.pdf

OptionType = Literal["call", "put", "stock"]
DisplayMode = Literal["per_share", "total"]


def _as_decimal_rate(value: float) -> float:
    """Convert OSS/API percent inputs (e.g. 28.4, 4.0) to model decimals."""
    return float(value) / 100.0


@dataclass(frozen=True, slots=True)
class BSMInputs:
    """Per-share European option inputs (spot, strike, rates, vol, time)."""

    spot: float
    strike: float
    time_years: float
    rate: float
    dividend_yield: float
    volatility: float
    option_type: Literal["call", "put"]

    @classmethod
    def from_api(
        cls,
        *,
        und_price: float,
        strike: float,
        days_to_expiry: float,
        int_rate: float,
        div_yield: float,
        volatility: float,
        option_type: Literal["call", "put"],
        day_count: int = 365,
    ) -> BSMInputs:
        if days_to_expiry < 0:
            raise ValueError("days_to_expiry must be >= 0")
        if day_count <= 0:
            raise ValueError("day_count must be > 0")
        return cls(
            spot=float(und_price),
            strike=float(strike),
            time_years=float(days_to_expiry) / float(day_count),
            rate=_as_decimal_rate(int_rate),
            dividend_yield=_as_decimal_rate(div_yield),
            volatility=_as_decimal_rate(volatility),
            option_type=option_type,
        )


@dataclass(frozen=True, slots=True)
class LegResult:
    leg_id: int
    option_type: OptionType
    position: int
    contract_multiplier: int
    mark_price: float
    value: float
    initial_cf: float
    pnl: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


@dataclass(frozen=True, slots=True)
class StrategyMarkResult:
    legs: tuple[LegResult, ...]
    total_initial_cf: float
    total_value: float
    total_pnl: float
    total_delta: float
    total_gamma: float
    total_theta: float
    total_vega: float
    total_rho: float


def _d1_d2(
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    dividend_yield: float,
    volatility: float,
) -> tuple[float, float]:
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be > 0")
    if volatility <= 0:
        raise ValueError("volatility must be > 0")
    if time_years <= 0:
        # Expired / at expiry handled by callers (price → intrinsic, greeks → 0)
        raise ValueError("time_years must be > 0 for d1/d2")
    vol_sqrt_t = volatility * sqrt(time_years)
    d1 = (
        log(spot / strike)
        + (rate - dividend_yield + 0.5 * volatility * volatility) * time_years
    ) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    return d1, d2


def black_scholes_merton_price(inputs: BSMInputs) -> float:
    """Return the European option mark **per share** (OSS column I)."""
    if inputs.time_years <= 0:
        intrinsic = max(inputs.spot - inputs.strike, 0.0)
        if inputs.option_type == "put":
            intrinsic = max(inputs.strike - inputs.spot, 0.0)
        return intrinsic

    d1, d2 = _d1_d2(
        inputs.spot,
        inputs.strike,
        inputs.time_years,
        inputs.rate,
        inputs.dividend_yield,
        inputs.volatility,
    )
    df_q = exp(-inputs.dividend_yield * inputs.time_years)
    df_r = exp(-inputs.rate * inputs.time_years)
    if inputs.option_type == "call":
        return inputs.spot * df_q * _N(d1) - inputs.strike * df_r * _N(d2)
    return inputs.strike * df_r * _N(-d2) - inputs.spot * df_q * _N(-d1)


def option_greeks(inputs: BSMInputs) -> dict[str, float]:
    """Return per-share Greeks using OSS Guide conventions."""
    if inputs.time_years <= 0:
        if inputs.option_type == "call":
            delta = 1.0 if inputs.spot > inputs.strike else 0.0
        else:
            delta = -1.0 if inputs.spot < inputs.strike else 0.0
        return {
            "delta": delta,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
        }

    d1, d2 = _d1_d2(
        inputs.spot,
        inputs.strike,
        inputs.time_years,
        inputs.rate,
        inputs.dividend_yield,
        inputs.volatility,
    )
    df_q = exp(-inputs.dividend_yield * inputs.time_years)
    df_r = exp(-inputs.rate * inputs.time_years)
    sqrt_t = sqrt(inputs.time_years)
    phi = _PHI(d1)
    gamma = df_q * phi / (inputs.spot * inputs.volatility * sqrt_t)
    vega = 0.01 * inputs.spot * df_q * sqrt_t * phi

    if inputs.option_type == "call":
        delta = df_q * _N(d1)
        theta = (
            -inputs.spot * df_q * phi * inputs.volatility / (2.0 * sqrt_t)
            + inputs.dividend_yield * inputs.spot * df_q * _N(d1)
            - inputs.rate * inputs.strike * df_r * _N(d2)
        ) / 365.0
        rho = 0.01 * inputs.strike * inputs.time_years * df_r * _N(d2)
    else:
        delta = df_q * (_N(d1) - 1.0)
        theta = (
            -inputs.spot * df_q * phi * inputs.volatility / (2.0 * sqrt_t)
            - inputs.dividend_yield * inputs.spot * df_q * _N(-d1)
            + inputs.rate * inputs.strike * df_r * _N(-d2)
        ) / 365.0
        rho = -0.01 * inputs.strike * inputs.time_years * df_r * _N(-d2)

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "rho": rho,
    }


def _effective_multiplier(
    leg: Mapping[str, Any],
    default_contract_multiplier: int,
    default_stock_multiplier: int = 1,
) -> int:
    override = leg.get("contract_multiplier")
    if override is not None:
        return int(override)
    if str(leg.get("type", "")).lower() == "stock":
        return int(default_stock_multiplier)
    return int(default_contract_multiplier)


def _scale_factor(
    position: int,
    multiplier: int,
    display_mode: DisplayMode,
) -> float:
    if display_mode == "per_share":
        return float(position)
    return float(position * multiplier)


def mark_leg(
    leg: Mapping[str, Any],
    *,
    und_price: float,
    div_yield: float,
    int_rate: float,
    volatility: float,
    flat_volatility: bool = True,
    default_contract_multiplier: int = 100,
    default_stock_multiplier: int = 1,
    display_mode: DisplayMode = "total",
    day_count: int = 365,
) -> LegResult:
    """Mark one OSS-style leg (call / put / stock)."""
    leg_id = int(leg.get("leg_id") or 0)
    option_type = str(leg.get("type", "")).lower()
    if option_type not in {"call", "put", "stock"}:
        raise ValueError(f"unsupported leg type: {option_type!r}")

    position = int(leg["position"])
    multiplier = _effective_multiplier(
        leg, default_contract_multiplier, default_stock_multiplier
    )
    scale = _scale_factor(position, multiplier, display_mode)

    initial_price = float(leg.get("initial_price") or 0.0)
    initial_cf = float(
        leg.get("initial_cf")
        if leg.get("initial_cf") is not None
        else -position * initial_price * multiplier
    )

    if option_type == "stock":
        mark_price = float(und_price)
        # Per-share stock delta is +1; signed position×multiplier is applied via scale.
        greeks = {
            "delta": 1.0,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
        }
    else:
        days = float(leg["days_to_expiry"])
        leg_vol = (
            float(leg["leg_volatility"])
            if (not flat_volatility and leg.get("leg_volatility") is not None)
            else float(volatility)
        )
        inputs = BSMInputs.from_api(
            und_price=und_price,
            strike=float(leg["strike"]),
            days_to_expiry=days,
            int_rate=int_rate,
            div_yield=div_yield,
            volatility=leg_vol,
            option_type=option_type,  # type: ignore[arg-type]
            day_count=day_count,
        )
        mark_price = black_scholes_merton_price(inputs)
        greeks = option_greeks(inputs)

    value = scale * mark_price
    pnl = initial_cf + value
    return LegResult(
        leg_id=leg_id,
        option_type=option_type,  # type: ignore[arg-type]
        position=position,
        contract_multiplier=multiplier,
        mark_price=mark_price,
        value=value,
        initial_cf=initial_cf,
        pnl=pnl,
        delta=scale * greeks["delta"],
        gamma=scale * greeks["gamma"],
        theta=scale * greeks["theta"],
        vega=scale * greeks["vega"],
        rho=scale * greeks["rho"],
    )


def mark_strategy(
    *,
    global_params: Mapping[str, Any],
    legs: Iterable[Mapping[str, Any]],
) -> StrategyMarkResult:
    """Reprice an OSS strategy and return per-leg + total marks (OSS row 18)."""
    display_mode: DisplayMode = str(  # type: ignore[assignment]
        global_params.get("display_mode") or "total"
    )
    if display_mode not in {"per_share", "total"}:
        raise ValueError(f"invalid display_mode: {display_mode!r}")

    default_mult = int(global_params.get("default_contract_multiplier") or 100)
    default_stock = int(global_params.get("default_stock_multiplier") or 1)
    day_count = int(global_params.get("day_count") or 365)
    flat = bool(global_params.get("flat_volatility", True))

    marked: list[LegResult] = []
    for leg in legs:
        if str(leg.get("type", "")).lower() in {"", "none"}:
            continue
        marked.append(
            mark_leg(
                leg,
                und_price=float(global_params["und_price"]),
                div_yield=float(global_params["div_yield"]),
                int_rate=float(global_params["int_rate"]),
                volatility=float(global_params["volatility"]),
                flat_volatility=flat,
                default_contract_multiplier=default_mult,
                default_stock_multiplier=default_stock,
                display_mode=display_mode,
                day_count=day_count,
            )
        )

    return StrategyMarkResult(
        legs=tuple(marked),
        total_initial_cf=sum(x.initial_cf for x in marked),
        total_value=sum(x.value for x in marked),
        total_pnl=sum(x.pnl for x in marked),
        total_delta=sum(x.delta for x in marked),
        total_gamma=sum(x.gamma for x in marked),
        total_theta=sum(x.theta for x in marked),
        total_vega=sum(x.vega for x in marked),
        total_rho=sum(x.rho for x in marked),
    )
