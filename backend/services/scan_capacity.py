"""Derived scan capacity for recommendation cycles — and a loud config check.

The coverage gate used to be four independently hardcoded numbers
(`max_symbols`, `generation_budget_sec`, `min_coverage_ratio`,
`min_eligible_symbols`) that were free to describe an arithmetically impossible
cycle — and did. 40 symbols at ~6 paced Breeze calls each, spaced 700ms, needs
~170s of wall clock; the budget was 20s. Every scan was truncated, so
`eligible/scanned` could never reach 0.80 of 20+ underlyings. Nothing raised:
the engine simply published nothing, for weeks, and the only apparent fix was
to loosen the gate until something got through.

So capacity is no longer configured. It is *derived* from the physical
constraints and validated both at boot and per cycle (config is re-read from
disk each cycle, so boot-only validation would certify a file that can change
under it):

    max_symbols  = min(enrichment wall clock, history wall clock, daily envelope)
    min_eligible = ceil(min_coverage_ratio * max_symbols)

There is deliberately NO `min_eligible_symbols` config key: an absolute floor
that can drift (or be quietly lowered) independently of the cap is exactly the
gate-loosening lever this module exists to remove. The floor is sized to a
full scan, so a cycle that only managed 5 of a 20-symbol cap cannot publish on
5/5 = 100%.

What this model counts, it paces (`backend/services/breeze_pacing.py`):
enrichment calls through each `UniverseEnricher`'s limiter, candle-history
calls through the shared `history_pacer`; the two run as sequential phases of
one cycle, split `enrichment_budget_frac` / the remainder of
`generation_budget_sec`, and `recommendation_engine._build_universe` enforces
that split with separate deadlines. What it does NOT count: paper_sim
automation mark refreshes and health probes (funded by the envelope remainder
outside `breeze_daily_call_budget`), and on-demand `?refresh=true` generations
(unbudgeted — runtime call accounting is an open BACKLOG item).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from backend.services.market_session import parse_hhmm

# Breeze vendor envelope (Docs/architecture.md §8.9): ~100 calls/min, ~5000/day
# across *all* non-order APIs. Recommendation cycles get a documented slice.
BREEZE_DAILY_CALL_LIMIT = 5000

# Single source for the scheduler cadence fallback — trading_scheduler.py must
# use this same constant, or boot validation models a cadence the scheduler
# doesn't run (test_scan_capacity.py pins the two together).
DEFAULT_RECOMMENDATION_CADENCE_SEC = 900.0


class UnsatisfiableScanConfig(ValueError):
    """Raised at boot and per cycle when the gate arithmetic cannot hold."""


@dataclass(frozen=True)
class ScanCapacity:
    max_symbols: int
    min_eligible_symbols: int
    min_coverage_ratio: float
    enrichment_window_sec: float
    history_window_sec: float
    calls_per_symbol: int
    cycles_per_day: int
    calls_per_day: int
    limited_by: str  # "wall_clock" | "history_window" | "daily_envelope"

    def note(self) -> str:
        return (
            f"Scan capacity: {self.max_symbols} underlyings/cycle "
            f"(limited by {self.limited_by}), needing "
            f"{self.min_eligible_symbols} eligible "
            f"({self.min_coverage_ratio:.0%} of a full scan); "
            f"{self.calls_per_day} Breeze calls/day across "
            f"{self.cycles_per_day} scheduled cycles "
            "(on-demand refreshes are extra)."
        )


def _minutes(section: dict[str, Any], key: str, default: str) -> int:
    raw = section.get(key, default)
    try:
        t = parse_hhmm(raw)
    except (ValueError, AttributeError) as exc:
        raise UnsatisfiableScanConfig(
            f"session_schedule.{key}={raw!r} is not HH:MM: {exc}"
        ) from exc
    return t.hour * 60 + t.minute


def _cycles_per_day(cfg: dict[str, Any]) -> int:
    session = cfg.get("session_schedule") or {}
    sched = cfg.get("scheduler") or {}
    start = _minutes(session, "entry_start", "09:20")
    cutoff = _minutes(session, "entry_cutoff", "14:30")
    cadence_sec = float(
        sched.get("recommendation_cadence_sec", DEFAULT_RECOMMENDATION_CADENCE_SEC)
    )
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
    enrich_calls = max(1, int(enrich.get("breeze_calls_per_symbol", 6)))
    history_calls = max(0, int(enrich.get("breeze_history_calls_per_symbol", 2)))
    total_calls = enrich_calls + history_calls

    budget_sec = float(enrich.get("generation_budget_sec", 120))
    frac = min(1.0, max(0.1, float(enrich.get("enrichment_budget_frac", 0.70))))
    enrich_window = budget_sec * frac
    history_window = budget_sec - enrich_window

    # (1)/(2) Wall clock per phase: every counted call is paced at interval_sec
    # (enrichment via each UniverseEnricher's limiter, history via the shared
    # breeze_pacing.history_pacer), so spacing — not concurrency — is the
    # throughput bound in both windows.
    cap_enrich = int(enrich_window // (enrich_calls * interval_sec))
    cap_history = (
        int(history_window // (history_calls * interval_sec))
        if history_calls > 0
        else cap_enrich
    )

    # (3) Daily envelope: every *scheduled* cycle shares one quota.
    cycles = _cycles_per_day(cfg)
    daily_budget = float(enrich.get("breeze_daily_call_budget", 3500))
    cap_daily = int(daily_budget // (cycles * total_calls))

    max_symbols = max(0, min(cap_enrich, cap_history, cap_daily))
    if max_symbols == cap_enrich:
        limited_by = "wall_clock"
    elif max_symbols == cap_history:
        limited_by = "history_window"
    else:
        limited_by = "daily_envelope"

    min_ratio = float(coverage.get("min_coverage_ratio", 0.80))
    # No config override — see module docstring. validate_scan_capacity
    # rejects the key's presence outright; here it is simply never read.
    min_eligible = math.ceil(min_ratio * max_symbols)

    return ScanCapacity(
        max_symbols=max_symbols,
        min_eligible_symbols=min_eligible,
        min_coverage_ratio=min_ratio,
        enrichment_window_sec=enrich_window,
        history_window_sec=history_window,
        calls_per_symbol=total_calls,
        cycles_per_day=cycles,
        calls_per_day=max_symbols * total_calls * cycles,
        limited_by=limited_by,
    )


def validate_scan_capacity(cfg: dict[str, Any]) -> ScanCapacity:
    """Fail loudly rather than publish nothing all day.

    Runs at boot (FastAPI lifespan) AND at the top of every recommendation
    cycle — the config file is re-read from disk each cycle, so a post-boot
    edit must hit the same wall the boot check does, not silently take effect.
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

    if "min_eligible_symbols" in coverage:
        raise UnsatisfiableScanConfig(
            "strategy_coverage.min_eligible_symbols is no longer a config key: "
            "the absolute eligible floor is always derived as "
            "ceil(min_coverage_ratio × scan cap) so it cannot be tuned apart "
            f"from the cap (it would be {cap.min_eligible_symbols} here). "
            "Remove the key."
        )

    if cap.max_symbols < min_scan:
        raise UnsatisfiableScanConfig(
            f"Derived scan cap is {cap.max_symbols} underlyings/cycle, below the "
            f"min_scan_symbols={min_scan} needed for a meaningful coverage claim "
            f"(enrichment {cap.enrichment_window_sec:.0f}s / history "
            f"{cap.history_window_sec:.0f}s of "
            f"generation_budget_sec={enrich.get('generation_budget_sec')}s; "
            f"daily {enrich.get('breeze_daily_call_budget')} calls over "
            f"{cap.cycles_per_day} cycles at {cap.calls_per_symbol}/symbol). "
            "Raise the budget inputs or lower min_interval_ms — do NOT lower "
            "min_coverage_ratio to compensate."
        )

    if cap.calls_per_day > BREEZE_DAILY_CALL_LIMIT:
        raise UnsatisfiableScanConfig(
            f"Recommendation cycles alone would use {cap.calls_per_day} Breeze "
            f"calls/day, over the ~{BREEZE_DAILY_CALL_LIMIT}/day vendor envelope. "
            "Lower breeze_daily_call_budget or lengthen recommendation_cadence_sec."
        )

    # Same fallback (90) the engine itself uses when the key is missing
    # (recommendation_engine._response_cache_ttl_sec), so the error reports the
    # TTL the system would actually run at, not a fiction.
    ttl = float(enrich.get("response_cache_ttl_sec", 90.0))
    cadence = float(
        sched.get("recommendation_cadence_sec", DEFAULT_RECOMMENDATION_CADENCE_SEC)
    )
    budget = float(enrich.get("generation_budget_sec", 120))
    if ttl <= cadence + budget:
        raise UnsatisfiableScanConfig(
            f"response_cache_ttl_sec={ttl:.0f} does not outlive one scheduler "
            f"cadence plus a generation ({cadence:.0f}+{budget:.0f}s): dashboard "
            "reads would kick off their own competing cycles."
        )

    return cap
