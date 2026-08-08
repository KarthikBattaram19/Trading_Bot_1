"""Derived scan capacity for recommendation cycles — and a loud boot check.

The coverage gate used to be four independently hardcoded numbers
(`max_symbols`, `generation_budget_sec`, `min_coverage_ratio`,
`min_eligible_symbols`) that were free to describe an arithmetically impossible
cycle — and did. 40 symbols at ~5 paced Breeze calls each, spaced 700ms by the
global rate limiter, needs ~140s of wall clock; the budget was 20s. Every scan
was truncated, so `eligible/scanned` could never reach 0.80 of 20+ underlyings.
Nothing raised: the engine simply published nothing, for weeks, and the only
apparent fix was to loosen the gate until something got through.

So capacity is no longer configured. It is *derived* from the two physical
constraints — the paced call budget inside one cycle, and Breeze's ~5000
calls/day envelope — and validated at boot, so an unsatisfiable configuration
is a startup error instead of silent empty output.

    max_symbols       = min(wall-clock capacity, daily-envelope capacity)
    min_eligible      = ceil(min_coverage_ratio * max_symbols)

`min_eligible_symbols` derived this way is not redundant with the ratio: it is
an *absolute* floor sized to a full scan, so a cycle that only managed to scan
5 underlyings cannot publish on 5/5 = 100%.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Breeze vendor envelope (Docs/architecture.md §8.9): ~100 calls/min, ~5000/day
# across *all* non-order APIs. Recommendation cycles get a documented slice.
BREEZE_DAILY_CALL_LIMIT = 5000


class UnsatisfiableScanConfig(ValueError):
    """Raised at boot when the gate arithmetic cannot be satisfied."""


@dataclass(frozen=True)
class ScanCapacity:
    max_symbols: int
    min_eligible_symbols: int
    min_coverage_ratio: float
    enrichment_window_sec: float
    calls_per_symbol: int
    cycles_per_day: int
    calls_per_day: int
    limited_by: str  # "wall_clock" | "daily_envelope"

    def note(self) -> str:
        return (
            f"Scan capacity: {self.max_symbols} underlyings/cycle "
            f"(limited by {self.limited_by}), needing "
            f"{self.min_eligible_symbols} eligible "
            f"({self.min_coverage_ratio:.0%} of a full scan); "
            f"{self.calls_per_day} Breeze calls/day across "
            f"{self.cycles_per_day} cycles."
        )


def _hhmm_to_minutes(value: str) -> int:
    hh, _, mm = str(value).partition(":")
    return int(hh) * 60 + int(mm)


def _cycles_per_day(cfg: dict[str, Any]) -> int:
    session = cfg.get("session_schedule") or {}
    sched = cfg.get("scheduler") or {}
    start = _hhmm_to_minutes(session.get("entry_start", "09:20"))
    cutoff = _hhmm_to_minutes(session.get("entry_cutoff", "14:30"))
    cadence_sec = float(sched.get("recommendation_cadence_sec", 900))
    window_sec = max(0, (cutoff - start) * 60)
    if cadence_sec <= 0:
        return 1
    # One cycle fires at entry_start, then every cadence until the cutoff.
    return max(1, int(window_sec // cadence_sec) + 1)


def scan_capacity(cfg: dict[str, Any]) -> ScanCapacity:
    """Derive the per-cycle scan cap and eligible floor from the call budget."""
    enrich = cfg.get("recommendation_universe_enrichment") or {}
    coverage = cfg.get("strategy_coverage") or {}

    interval_sec = max(0.05, float(enrich.get("min_interval_ms", 700)) / 1000.0)
    enrich_calls = max(1, int(enrich.get("breeze_calls_per_symbol", 5)))
    history_calls = max(0, int(enrich.get("breeze_history_calls_per_symbol", 2)))
    total_calls = enrich_calls + history_calls

    budget_sec = float(enrich.get("generation_budget_sec", 120))
    frac = min(1.0, max(0.1, float(enrich.get("enrichment_budget_frac", 0.70))))
    window_sec = budget_sec * frac

    # (1) Wall clock: the global rate limiter serialises every Breeze call, so
    # concurrency does not buy throughput here — only the spacing matters.
    cap_wall_clock = int(window_sec // (enrich_calls * interval_sec))

    # (2) Daily envelope: every cycle of every session day shares one quota.
    cycles = _cycles_per_day(cfg)
    daily_budget = float(enrich.get("breeze_daily_call_budget", 3500))
    cap_daily = int(daily_budget // (cycles * total_calls))

    max_symbols = max(0, min(cap_wall_clock, cap_daily))
    limited_by = "wall_clock" if cap_wall_clock <= cap_daily else "daily_envelope"

    min_ratio = float(coverage.get("min_coverage_ratio", 0.80))
    explicit = coverage.get("min_eligible_symbols")
    min_eligible = (
        int(explicit) if explicit is not None else math.ceil(min_ratio * max_symbols)
    )

    return ScanCapacity(
        max_symbols=max_symbols,
        min_eligible_symbols=min_eligible,
        min_coverage_ratio=min_ratio,
        enrichment_window_sec=window_sec,
        calls_per_symbol=total_calls,
        cycles_per_day=cycles,
        calls_per_day=max_symbols * total_calls * cycles,
        limited_by=limited_by,
    )


def validate_scan_capacity(cfg: dict[str, Any]) -> ScanCapacity:
    """Fail loudly at boot rather than publish nothing all day.

    Every condition here previously failed silently: the cycle truncated, the
    coverage gate aborted every strategy, and the dashboard showed an empty
    recommendation list with no indication that the configuration itself was
    the reason.
    """
    cap = scan_capacity(cfg)
    coverage = cfg.get("strategy_coverage") or {}
    enrich = cfg.get("recommendation_universe_enrichment") or {}
    sched = cfg.get("scheduler") or {}
    min_scan = int(coverage.get("min_scan_symbols", 10))

    if cap.max_symbols < min_scan:
        raise UnsatisfiableScanConfig(
            f"Derived scan cap is {cap.max_symbols} underlyings/cycle, below the "
            f"min_scan_symbols={min_scan} needed for a meaningful coverage claim. "
            f"Raise generation_budget_sec (now {enrich.get('generation_budget_sec')}s, "
            f"{cap.enrichment_window_sec:.0f}s usable) or breeze_daily_call_budget "
            f"(now {enrich.get('breeze_daily_call_budget')} over {cap.cycles_per_day} "
            f"cycles at {cap.calls_per_symbol} calls/symbol), or lower "
            f"min_interval_ms — do NOT lower min_coverage_ratio to compensate."
        )

    if cap.min_eligible_symbols > cap.max_symbols:
        raise UnsatisfiableScanConfig(
            f"strategy_coverage.min_eligible_symbols={cap.min_eligible_symbols} "
            f"exceeds the derived scan cap of {cap.max_symbols} — no cycle can "
            "ever publish. Remove the explicit override to use the derived floor."
        )

    if cap.calls_per_day > BREEZE_DAILY_CALL_LIMIT:
        raise UnsatisfiableScanConfig(
            f"Recommendation cycles alone would use {cap.calls_per_day} Breeze "
            f"calls/day, over the ~{BREEZE_DAILY_CALL_LIMIT}/day vendor envelope. "
            "Lower breeze_daily_call_budget or lengthen recommendation_cadence_sec."
        )

    ttl = float(enrich.get("response_cache_ttl_sec", 0))
    cadence = float(sched.get("recommendation_cadence_sec", 900))
    budget = float(enrich.get("generation_budget_sec", 120))
    if ttl <= cadence + budget:
        raise UnsatisfiableScanConfig(
            f"response_cache_ttl_sec={ttl:.0f} does not outlive one scheduler "
            f"cadence plus a generation ({cadence:.0f}+{budget:.0f}s): dashboard "
            "reads would kick off their own competing cycles."
        )

    return cap
