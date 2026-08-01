"""Per-strategy coverage gate for recommendation cycles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.models.recommendations import StrategyType
from backend.services.quant_snapshot import QuantSnapshot


@dataclass
class StrategyCoverageRow:
    strategy: StrategyType
    scanned: int
    eligible: int
    coverage: float
    published: bool
    warning: str | None = None


@dataclass
class StrategyCoverageReport:
    scanned: int
    by_strategy: dict[StrategyType, StrategyCoverageRow]
    available_strategies: set[StrategyType]
    warnings: list[str] = field(default_factory=list)

    def note_lines(self) -> list[str]:
        lines = list(self.warnings)
        for row in self.by_strategy.values():
            status = "published" if row.published else "aborted"
            lines.append(
                f"STRATEGY_COVERAGE {row.strategy.value}: "
                f"eligible={row.eligible}/{row.scanned} "
                f"({row.coverage:.1%}) — {status}"
            )
        return lines

    def api_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "strategy": row.strategy.value,
                "scanned": row.scanned,
                "eligible": row.eligible,
                "coverage": round(row.coverage, 4),
                "published": row.published,
            }
            for row in self.by_strategy.values()
        ]


def _live_marks_ok(snap: QuantSnapshot) -> bool:
    return (
        snap.marks_live
        and snap.und_price.usable
        and snap.iv_annualized.usable
    )


def eligible_simple_volatility(snap: QuantSnapshot) -> bool:
    return _live_marks_ok(snap) and snap.garch_forecast.usable and not snap.garch_distorted


def eligible_vega_scalping(snap: QuantSnapshot) -> bool:
    return eligible_simple_volatility(snap) and snap.iv_z_score.usable


def eligible_gamma_scalping(snap: QuantSnapshot) -> bool:
    if not _live_marks_ok(snap):
        return False
    dte = snap.days_to_earnings.value if snap.days_to_earnings.usable else None
    # Earnings-gap path: calendar days_to_earnings <= 1 does not require GARCH.
    if snap.days_to_earnings.usable and dte is not None and int(dte) <= 1:
        return True
    has_rv_or_earn = snap.realized_vol_intraday.usable or snap.days_to_earnings.usable
    return has_rv_or_earn and snap.garch_forecast.usable and not snap.garch_distorted


_ELIGIBILITY = {
    StrategyType.simple_volatility: eligible_simple_volatility,
    StrategyType.vega_scalping: eligible_vega_scalping,
    StrategyType.gamma_scalping: eligible_gamma_scalping,
}


def evaluate_strategy_coverage(
    snapshots: list[QuantSnapshot],
    *,
    scanned: int,
    cfg: dict[str, Any],
) -> StrategyCoverageReport:
    section = cfg.get("strategy_coverage") or {}
    min_ratio = float(section.get("min_coverage_ratio", 0.80))
    min_eligible = int(section.get("min_eligible_symbols", 50))
    scanned_n = max(0, int(scanned))

    by_strategy: dict[StrategyType, StrategyCoverageRow] = {}
    available: set[StrategyType] = set()
    warnings: list[str] = []

    for st, pred in _ELIGIBILITY.items():
        eligible = sum(1 for s in snapshots if pred(s))
        coverage = (eligible / scanned_n) if scanned_n > 0 else 0.0
        published = coverage >= min_ratio and eligible >= min_eligible
        warning = None
        if not published:
            warning = (
                f"STRATEGY_COVERAGE_ABORT {st.value}: "
                f"eligible={eligible}/{scanned_n} ({coverage:.1%}) "
                f"< {min_ratio:.0%} or <{min_eligible}"
            )
            warnings.append(warning)
        else:
            available.add(st)
        by_strategy[st] = StrategyCoverageRow(
            strategy=st,
            scanned=scanned_n,
            eligible=eligible,
            coverage=coverage,
            published=published,
            warning=warning,
        )

    return StrategyCoverageReport(
        scanned=scanned_n,
        by_strategy=by_strategy,
        available_strategies=available,
        warnings=warnings,
    )
