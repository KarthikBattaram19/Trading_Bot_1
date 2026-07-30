"""Aggregate Greeks limit checks (architecture §9.F / §11.4)."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping


@dataclass(frozen=True, slots=True)
class GreeksLimitThresholds:
    """Per-strategy / portfolio ceilings on OSS ``total_*`` Greeks.

    Theta gate: ``total_theta >= min_total_theta`` — more negative theta means
    larger daily decay and fails when below the floor (max daily decay).
    """

    max_abs_total_delta: float = 10_000.0
    max_abs_total_gamma: float = 5_000.0
    max_abs_total_vega: float = 50_000.0
    max_abs_total_rho: float = 50_000.0
    min_total_theta: float = -50_000.0  # reject if more negative


@dataclass(frozen=True, slots=True)
class GreeksLimitResult:
    passed: bool
    failures: tuple[str, ...]
    detail: Mapping[str, float]


def check_greeks_limits(
    *,
    total_delta: float,
    total_gamma: float,
    total_vega: float,
    total_theta: float,
    total_rho: float | None = None,
    thresholds: GreeksLimitThresholds | None = None,
) -> GreeksLimitResult:
    """Return pass/fail for |Δ|, |Γ|, |ν|, Θ floor, optional |ρ|."""
    thr = thresholds or GreeksLimitThresholds()
    failures: list[str] = []
    values = {
        "total_delta": float(total_delta),
        "total_gamma": float(total_gamma),
        "total_vega": float(total_vega),
        "total_theta": float(total_theta),
    }
    if total_rho is not None:
        values["total_rho"] = float(total_rho)

    for key, val in values.items():
        if not isfinite(val):
            failures.append(f"{key}_non_finite")

    if abs(values["total_delta"]) > float(thr.max_abs_total_delta):
        failures.append("total_delta")
    if abs(values["total_gamma"]) > float(thr.max_abs_total_gamma):
        failures.append("total_gamma")
    if abs(values["total_vega"]) > float(thr.max_abs_total_vega):
        failures.append("total_vega")
    if values["total_theta"] < float(thr.min_total_theta):
        failures.append("total_theta")
    if total_rho is not None and abs(values["total_rho"]) > float(thr.max_abs_total_rho):
        failures.append("total_rho")

    return GreeksLimitResult(
        passed=len(failures) == 0,
        failures=tuple(failures),
        detail=values,
    )
