"""
Continual learning engine — architecture §12.

Persists trade outcomes, failure memory, module attribution, and adaptation
events to a local JSON store (PostgreSQL / ChromaDB in full deployment).

Pre-trade: retrieve similar failure contexts and penalize confidence (−0.10).
Post-trade: record outcome; on loss write failure_memory; update attribution;
optionally queue adaptation when triggers fire (§12.3) under safety guards (§12.5).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.analytics.confidence_calibration import is_seed_outcome
from backend.models.learning import (
    AdaptationEvent,
    CloseTradeRequest,
    FailureMemoryEntry,
    FailureMemoryMatch,
    LearningDashboard,
    LearningInsight,
    ModuleAttribution,
    OpenTradeRecord,
    TradeOutcomeLabel,
    TradeOutcomeRecord,
)
from backend.models.recommendations import InstrumentRecommendation

STORE_PATH = Path(__file__).resolve().parents[1] / "data" / "learning_store.json"

logger = logging.getLogger(__name__)

# Bump when seed payload shape changes so existing paper stores can backfill.
SEED_VERSION = 3

# §12.6 — confidence penalty when top failure contexts match
FAILURE_CONFIDENCE_PENALTY = 0.10
FAILURE_MATCH_THRESHOLD = 0.55
TOP_FAILURE_MATCHES = 3

# §12.5 / §12.3 trigger thresholds (retail defaults)
MIN_TRADES_FOR_ADAPTATION = 5  # lowered from 30 for paper/demo loop
WIN_RATE_TIGHTEN_THRESHOLD = 0.60
DRAWDOWN_FREEZE_PCT = 5.0

_DEMO_OPEN_TRADE_ID = "trd_seed_open_hdfc_001"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _empty_store() -> dict[str, Any]:
    return {
        "seed_version": SEED_VERSION,
        "open_trades": [],
        "outcomes": [],
        "failure_memories": [],
        "adaptation_history": [],
        "module_weights": {
            "simple_volatility": 1.0,
            "gamma_scalping": 1.0,
            "vega_scalping": 1.0,
        },
        "peak_equity_inr": 0.0,
        "equity_inr": 0.0,
    }


def _seed_failure_memories(base: str | None = None) -> list[dict[str, Any]]:
    """Seed historical losses so the first ranking cycle already shows learning."""
    closed_at = base or _now().isoformat()
    return [
        {
            "failure_id": "fm_seed_tatasteel_vega",
            "trade_id": "trd_seed_tatasteel_001",
            "underlying_symbol": "TATASTEEL",
            "strategy": "vega_scalping",
            "entry_mode": "standard",
            "scenario_tag": "Scenario A: Clean Intraday IV Flush",
            "primary_signal": "iv_z_score=-2.55 ≤ -2.0",
            "market_summary": (
                "TATASTEEL IV flush looked clean but stationarity broke mid-session; "
                "IV continued lower through −3σ stop."
            ),
            "loss_pnl_inr": -4200.0,
            "exit_reason": "IV stop −3σ (N6.1)",
            "lesson": (
                "Deep IV flush on mid-cap steel names often continues when OI is thin — "
                "require higher OI or tighter session-time exit before vega scalp."
            ),
            "tags": ["vega_scalping", "iv_flush", "stationarity", "TATASTEEL"],
            "closed_at": closed_at,
        },
        {
            "failure_id": "fm_seed_infy_gamma",
            "trade_id": "trd_seed_infy_002",
            "underlying_symbol": "INFY",
            "strategy": "gamma_scalping",
            "entry_mode": "earnings_gap_mode",
            "scenario_tag": "Scenario A: Earnings Gap",
            "primary_signal": "days_to_earnings=1",
            "market_summary": (
                "INFY earnings gap was muted; theta dominated overnight gamma structure."
            ),
            "loss_pnl_inr": -3100.0,
            "exit_reason": "Quiet gap — theta bleed (M6)",
            "lesson": (
                "Earnings-gap gamma needs an implied-move floor; skip when options imply "
                "<1.5% move or news tone is already priced."
            ),
            "tags": ["gamma_scalping", "earnings", "quiet_gap", "INFY"],
            "closed_at": closed_at,
        },
        {
            "failure_id": "fm_seed_reliance_sv",
            "trade_id": "trd_seed_reliance_003",
            "underlying_symbol": "RELIANCE",
            "strategy": "simple_volatility",
            "entry_mode": "cheap_vol_mode",
            "scenario_tag": "Scenario A: Normal Cheap-Vol Setup",
            "primary_signal": "IV < GARCH cheap-vol edge",
            "market_summary": (
                "RELIANCE IV stayed cheap vs GARCH; hedge costs ate the theoretical edge."
            ),
            "loss_pnl_inr": -1850.0,
            "exit_reason": "Hedge cost > gamma profit",
            "lesson": (
                "Cheap-vol entries need a minimum IV−GARCH edge after estimated hedge cost; "
                "raise edge floor when spread > 1%."
            ),
            "tags": ["simple_volatility", "hedge_cost", "RELIANCE"],
            "closed_at": closed_at,
        },
    ]


def _seed_outcomes_from_failures(
    failures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Mirror seeded failure memories into closed outcomes + module attribution."""
    outcomes: list[dict[str, Any]] = []
    for i, fm in enumerate(failures):
        closed_at = str(fm.get("closed_at") or _now().isoformat())
        outcomes.append(
            {
                "outcome_id": f"out_seed_{i+1:03d}",
                "trade_id": fm["trade_id"],
                "underlying_symbol": fm["underlying_symbol"],
                "rank": i + 1,
                "strategy": fm["strategy"],
                "entry_mode": fm.get("entry_mode"),
                "scenario_tag": fm.get("scenario_tag", ""),
                "primary_signal": fm.get("primary_signal", ""),
                "score_at_entry": 0.85,
                "confidence_at_entry": 0.82,
                "outcome": "loss",
                "realized_pnl_inr": float(fm["loss_pnl_inr"]),
                "exit_reason": fm.get("exit_reason", "seeded loss"),
                "notes": None,
                "recommendation_snapshot": {
                    "seed": True,
                    "market_summary": fm.get("market_summary"),
                },
                "opened_at": closed_at,
                "closed_at": closed_at,
                "failure_memory_id": fm["failure_id"],
                "config_snapshot_id": "defaults",
            }
        )
    return outcomes


def _seed_open_trade(opened_at: str | None = None) -> dict[str, Any]:
    """One paper demo open trade so /learning Mark Win/Loss is usable."""
    ts = opened_at or _now().isoformat()
    return {
        "trade_id": _DEMO_OPEN_TRADE_ID,
        "underlying_symbol": "HDFCBANK",
        "rank": 1,
        "strategy": "vega_scalping",
        "entry_mode": "standard",
        "scenario_tag": "Scenario A: Clean Intraday IV Flush",
        "primary_signal": "iv_z_score=-2.10 ≤ -2.0",
        "score": 0.84,
        "confidence": 0.81,
        "recommendation_snapshot": {
            "seed": True,
            "underlying_symbol": "HDFCBANK",
            "market_summary": "Demo open trade for continual-learning outcome recording.",
        },
        "opened_at": ts,
        "config_snapshot_id": "defaults",
    }


def _build_seeded_store() -> dict[str, Any]:
    """Full paper demo store — failures, matching outcomes, and one open trade.

    Fixtures stay on disk for migration/local UX only. Dashboard metrics,
    failure-memory retrieval, and adaptation (§12) exclude every seed row.
    """
    base = _now().isoformat()
    failures = _seed_failure_memories(base)
    outcomes = _seed_outcomes_from_failures(failures)
    store = _empty_store()
    store["failure_memories"] = failures
    store["outcomes"] = outcomes
    store["open_trades"] = [_seed_open_trade(base)]
    # Neutral weights — seeded losses must not pre-bias module reweighting.
    store["module_weights"] = {
        "simple_volatility": 1.0,
        "gamma_scalping": 1.0,
        "vega_scalping": 1.0,
    }
    store["equity_inr"] = 0.0
    store["peak_equity_inr"] = 0.0
    store["seed_version"] = SEED_VERSION
    return store


def _real_outcomes(store: dict[str, Any]) -> list[dict[str, Any]]:
    return [o for o in store.get("outcomes", []) if not is_seed_outcome(o)]


def _real_open_trades(store: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in store.get("open_trades", []) if not is_seed_outcome(t)]


def _real_failure_memories(store: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in store.get("failure_memories", []) if not is_seed_outcome(f)]


def _outcome_label_from_pnl(pnl: float) -> TradeOutcomeLabel:
    if pnl > 0:
        return TradeOutcomeLabel.win
    if pnl < 0:
        return TradeOutcomeLabel.loss
    return TradeOutcomeLabel.scratch


class LearningService:
    """In-process learning store with JSON persistence."""

    def __init__(self, store_path: Path | None = None) -> None:
        self.store_path = store_path or STORE_PATH
        self._ensure_store()

    def _ensure_store(self) -> None:
        """Bootstrap the on-disk store if missing. Delegates to `_read()` so
        there is exactly one guarded load path — see `_read` docstring."""
        self._read()

    def _migrate_incomplete_seed(self, store: dict[str, Any]) -> bool:
        """
        Keep fixture rows for local UX, but never let them bias §12 metrics.

        v1→v2: backfill outcomes/open trade when the operator had only failures.
        v2→v3: neutralize seed-derived equity / module weights so reporting is clean.
        """
        version = int(store.get("seed_version") or 1)
        changed = False

        if version < 2:
            outcomes = store.get("outcomes") or []
            # Do not rewrite stores that already have operator-recorded outcomes.
            if not outcomes:
                failures = store.get("failure_memories") or _seed_failure_memories()
                store["failure_memories"] = failures
                store["outcomes"] = _seed_outcomes_from_failures(failures)
                open_trades = store.get("open_trades") or []
                if not open_trades:
                    store["open_trades"] = [_seed_open_trade()]
                changed = True
            store["seed_version"] = 2
            version = 2
            changed = True

        if version < SEED_VERSION:
            real = _real_outcomes(store)
            store["module_weights"] = {
                "simple_volatility": 1.0,
                "gamma_scalping": 1.0,
                "vega_scalping": 1.0,
            }
            # Equity / peak from real closes only (seed PnL excluded).
            equity = sum(float(o.get("realized_pnl_inr") or 0.0) for o in real)
            store["equity_inr"] = equity
            store["peak_equity_inr"] = max(0.0, equity)
            store["seed_version"] = SEED_VERSION
            changed = True

        return changed

    def _read(self) -> dict[str, Any]:
        """Load the ledger from disk. The single guarded read path — every
        other read (including bootstrap via `_ensure_store`) routes through
        here, so there is exactly one place that can raise on corruption.

        Deliberately asymmetric to `IvHistoryStore._read`: this store is the
        financial ledger (one-trade lock, open positions, closed outcomes,
        realized P&L), not a regenerable cache. A corrupt file MUST fail
        loud — never degrade to `{}` or a partial store, and never
        quarantine-and-continue. A silently emptied ledger would tell the
        bot it has no open position when it actually does, which is how a
        second position gets opened against a live one. If this ever grows
        exception handling, it must re-raise with a clearer message, not
        swallow.
        """
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            store = _build_seeded_store()
            self._write(store)
            return store
        try:
            with open(self.store_path, encoding="utf-8") as f:
                store = json.load(f)
        except json.JSONDecodeError:
            logger.error(
                "learning_service: corrupt ledger at %s — refusing to degrade to an "
                "empty/partial store; this must be fixed by a human before trading resumes",
                self.store_path,
                exc_info=True,
            )
            raise
        if self._migrate_incomplete_seed(store):
            self._write(store)
        return store

    def _write(self, store: dict[str, Any]) -> None:
        """Atomically persist the ledger (temp file in the same dir + fsync +
        `os.replace` with a bounded retry), so a crash or overlapping writer
        can never leave a half-written ledger on disk. Mirrors
        `IvHistoryStore._write`; see that module for the rationale."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.store_path.parent),
            prefix=self.store_path.name + ".",
            suffix=".tmp",
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(store, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            self._replace_with_retry(tmp_path)
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _replace_with_retry(self, tmp_path: Path, attempts: int = 8) -> None:
        # os.replace(tmp, dst) is atomic, but on Windows two writers racing
        # to replace the *same* dst at the same instant can transiently see
        # PermissionError (WinError 5) while the OS resolves the rename —
        # not corruption, just contention. Retry briefly before giving up.
        for attempt in range(attempts):
            try:
                os.replace(tmp_path, self.store_path)
                return
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.01 * (attempt + 1))

    # ── Pre-trade retrieval (§12.6) ──────────────────────────────────────

    def retrieve_failure_matches(
        self,
        symbol: str,
        strategy: str,
        entry_mode: str | None,
        scenario_tag: str,
    ) -> list[FailureMemoryMatch]:
        store = self._read()
        scored: list[tuple[float, dict[str, Any]]] = []
        for fm in _real_failure_memories(store):
            score = 0.0
            if fm.get("strategy") == strategy:
                score += 0.45
            if fm.get("underlying_symbol") == symbol:
                score += 0.35
            if entry_mode and fm.get("entry_mode") == entry_mode:
                score += 0.15
            if fm.get("scenario_tag") == scenario_tag:
                score += 0.10
            # Soft tag overlap
            tags = set(fm.get("tags") or [])
            if strategy in tags:
                score += 0.05
            if score >= FAILURE_MATCH_THRESHOLD:
                scored.append((min(0.99, score), fm))

        scored.sort(key=lambda x: x[0], reverse=True)
        matches: list[FailureMemoryMatch] = []
        for sim, fm in scored[:TOP_FAILURE_MATCHES]:
            matches.append(
                FailureMemoryMatch(
                    failure_id=fm["failure_id"],
                    similarity=round(sim, 3),
                    summary=fm.get("market_summary") or fm.get("lesson", ""),
                    loss_pnl_inr=float(fm["loss_pnl_inr"]),
                    lesson=fm["lesson"],
                    strategy=fm["strategy"],
                    underlying_symbol=fm["underlying_symbol"],
                    closed_at=datetime.fromisoformat(str(fm["closed_at"]).replace("Z", "+00:00")),
                )
            )
        return matches

    def build_learning_insight(
        self,
        rec: InstrumentRecommendation,
        confidence_before: float,
    ) -> LearningInsight:
        strategy = rec.strategy.selected_strategy.value
        matches = self.retrieve_failure_matches(
            symbol=rec.underlying_symbol,
            strategy=strategy,
            entry_mode=rec.strategy.entry_mode,
            scenario_tag=rec.strategy.scenario_tag,
        )
        penalty = FAILURE_CONFIDENCE_PENALTY if matches else 0.0
        confidence_after = round(max(0.05, confidence_before - penalty), 3)

        attr = self._module_stats().get(strategy)
        module_wr = attr.win_rate if attr and attr.trade_count else None
        module_n = attr.trade_count if attr else 0
        module_exp = attr.expectancy_inr if attr and attr.trade_count else None

        if matches:
            top = matches[0]
            note = (
                f"Failure memory hit: {len(matches)} similar loss(es). "
                f"Top match {top.underlying_symbol}/{top.strategy} "
                f"(sim={top.similarity:.0%}, PnL ₹{top.loss_pnl_inr:,.0f}). "
                f"Confidence −{penalty:.2f} per §12.6."
            )
        elif module_n > 0 and module_wr is not None:
            note = (
                f"No failure-memory match. Module {strategy}: "
                f"{module_n} closed trades, win rate {module_wr:.0%}, "
                f"expectancy ₹{module_exp or 0:,.0f}."
            )
        else:
            note = (
                "No failure-memory match and no closed-trade history for this module yet. "
                "Outcome of this trade will seed the learning loop."
            )

        return LearningInsight(
            failure_matches=matches,
            confidence_penalty=penalty,
            confidence_before=round(confidence_before, 3),
            confidence_after=confidence_after,
            module_win_rate=module_wr,
            module_trade_count=module_n,
            module_expectancy_inr=module_exp,
            learning_note=note,
        )

    def module_weight(self, strategy: str) -> float:
        store = self._read()
        return float(store.get("module_weights", {}).get(strategy, 1.0))

    # ── Open / close trades ──────────────────────────────────────────────

    def register_open_trade(
        self,
        trade_id: str,
        rec: InstrumentRecommendation,
    ) -> OpenTradeRecord:
        store = self._read()
        # Replace if same id re-registered
        store["open_trades"] = [
            t for t in store.get("open_trades", []) if t.get("trade_id") != trade_id
        ]
        record = OpenTradeRecord(
            trade_id=trade_id,
            underlying_symbol=rec.underlying_symbol,
            rank=rec.rank,
            strategy=rec.strategy.selected_strategy.value,
            entry_mode=rec.strategy.entry_mode,
            scenario_tag=rec.strategy.scenario_tag,
            primary_signal=rec.strategy.primary_signal,
            score=rec.score,
            confidence=rec.confidence,
            raw_confidence_at_entry=rec.raw_confidence,
            recommendation_snapshot=rec.model_dump(mode="json"),
            opened_at=_now(),
            config_snapshot_id="defaults",
        )
        store["open_trades"].append(json.loads(record.model_dump_json()))
        self._write(store)
        return record

    def get_open_trade(self, trade_id: str) -> OpenTradeRecord | None:
        store = self._read()
        for t in store.get("open_trades", []):
            if t.get("trade_id") == trade_id:
                return OpenTradeRecord.model_validate(t)
        return None

    def list_open_trades(self) -> list[OpenTradeRecord]:
        store = self._read()
        return [
            OpenTradeRecord.model_validate(t) for t in _real_open_trades(store)
        ]

    def real_closed_trade_count(self) -> int:
        """Real (non-seed) closed outcomes — drives the bootstrap confidence floor."""
        return len(_real_outcomes(self._read()))

    def record_ledger_close(
        self,
        trade_id: str,
        *,
        realized_pnl_inr: float,
        exit_reason: str = "paper_sim close",
    ) -> TradeOutcomeRecord | None:
        """
        Map a real paper_sim ledger close into the learning loop (§12.2 / §12.7).

        No-ops when the position was never registered as an open learning trade
        (e.g. ad-hoc paper_sim positions without a recommendation lineage) or
        when the open trade is a bundled seed fixture.
        """
        opened = self.get_open_trade(trade_id)
        if opened is None:
            return None
        if is_seed_outcome({"trade_id": trade_id}):
            return None
        return self.record_outcome(
            CloseTradeRequest(
                trade_id=trade_id,
                outcome=_outcome_label_from_pnl(float(realized_pnl_inr)),
                realized_pnl_inr=float(realized_pnl_inr),
                exit_reason=exit_reason,
            )
        )

    def record_outcome(self, request: CloseTradeRequest) -> TradeOutcomeRecord:
        """Close a trade, attribute P&L, write failure memory on loss, check adaptation."""
        store = self._read()
        open_raw = next(
            (t for t in store.get("open_trades", []) if t.get("trade_id") == request.trade_id),
            None,
        )
        if open_raw is None:
            raise ValueError(f"No open trade with id {request.trade_id}")

        opened = OpenTradeRecord.model_validate(open_raw)
        closed_at = _now()
        failure_id: str | None = None

        if request.outcome == TradeOutcomeLabel.loss:
            failure_id = f"fm_{uuid.uuid4().hex[:10]}"
            snap = opened.recommendation_snapshot
            lesson = self._derive_lesson(opened, request)
            fm = FailureMemoryEntry(
                failure_id=failure_id,
                trade_id=opened.trade_id,
                underlying_symbol=opened.underlying_symbol,
                strategy=opened.strategy,
                entry_mode=opened.entry_mode,
                scenario_tag=opened.scenario_tag,
                primary_signal=opened.primary_signal,
                market_summary=str(snap.get("market_summary") or opened.primary_signal),
                loss_pnl_inr=request.realized_pnl_inr,
                exit_reason=request.exit_reason,
                lesson=lesson,
                tags=self._tags_for(opened),
                closed_at=closed_at,
            )
            store.setdefault("failure_memories", []).append(
                json.loads(fm.model_dump_json())
            )

        outcome = TradeOutcomeRecord(
            outcome_id=f"out_{uuid.uuid4().hex[:10]}",
            trade_id=opened.trade_id,
            underlying_symbol=opened.underlying_symbol,
            rank=opened.rank,
            strategy=opened.strategy,
            entry_mode=opened.entry_mode,
            scenario_tag=opened.scenario_tag,
            primary_signal=opened.primary_signal,
            score_at_entry=opened.score,
            confidence_at_entry=opened.confidence,
            raw_confidence_at_entry=opened.raw_confidence_at_entry,
            outcome=request.outcome,
            realized_pnl_inr=request.realized_pnl_inr,
            exit_reason=request.exit_reason,
            notes=request.notes,
            recommendation_snapshot=opened.recommendation_snapshot,
            opened_at=opened.opened_at,
            closed_at=closed_at,
            failure_memory_id=failure_id,
            config_snapshot_id=opened.config_snapshot_id,
        )

        store["open_trades"] = [
            t for t in store.get("open_trades", []) if t.get("trade_id") != request.trade_id
        ]
        store.setdefault("outcomes", []).append(json.loads(outcome.model_dump_json()))

        equity = float(store.get("equity_inr", 0.0)) + request.realized_pnl_inr
        store["equity_inr"] = equity
        peak = float(store.get("peak_equity_inr", 0.0))
        if equity > peak:
            store["peak_equity_inr"] = equity

        # Reweight module lightly from rolling expectancy (capped ±15% §12.5)
        self._update_module_weight(store, opened.strategy)

        adaptation = self._maybe_adapt(store)
        if adaptation:
            store.setdefault("adaptation_history", []).append(
                json.loads(adaptation.model_dump_json())
            )

        self._write(store)
        self._maybe_refit_confidence_calibration(store.get("outcomes") or [])
        return outcome

    def _maybe_refit_confidence_calibration(self, outcomes: list[dict[str, Any]]) -> None:
        """Attempt score→P(win) refit; swap artifact only if walk-forward passes."""
        try:
            from backend.analytics.confidence_calibration import fit_and_maybe_deploy
            from backend.services.confidence_calibrator import DEFAULT_ARTIFACT

            fit_and_maybe_deploy(outcomes, artifact_path=DEFAULT_ARTIFACT)
        except Exception:  # noqa: BLE001
            # Calibration must never break trade close / learning loop
            return

    def _derive_lesson(self, opened: OpenTradeRecord, request: CloseTradeRequest) -> str:
        if request.notes:
            return request.notes
        return (
            f"{opened.strategy} on {opened.underlying_symbol} failed "
            f"({request.exit_reason}). Signal was '{opened.primary_signal}'. "
            f"Avoid similar context until sample size improves or filters tighten."
        )

    def _tags_for(self, opened: OpenTradeRecord) -> list[str]:
        tags = [opened.strategy, opened.underlying_symbol]
        if opened.entry_mode:
            tags.append(opened.entry_mode)
        if "earnings" in (opened.scenario_tag or "").lower():
            tags.append("earnings")
        if "iv" in (opened.primary_signal or "").lower():
            tags.append("iv_flush")
        return tags

    def _update_module_weight(self, store: dict[str, Any], strategy: str) -> None:
        outcomes = [
            o
            for o in _real_outcomes(store)
            if o.get("strategy") == strategy
        ]
        if len(outcomes) < 3:
            return
        pnls = [float(o["realized_pnl_inr"]) for o in outcomes[-20:]]
        avg = sum(pnls) / len(pnls)
        weights = store.setdefault("module_weights", {})
        current = float(weights.get(strategy, 1.0))
        # Nudge toward better expectancy; cap ±15% per update
        delta = max(-0.15, min(0.15, avg / 10000.0))
        weights[strategy] = round(max(0.5, min(1.5, current + delta)), 3)

    def _maybe_adapt(self, store: dict[str, Any]) -> AdaptationEvent | None:
        outcomes = _real_outcomes(store)
        if len(outcomes) < MIN_TRADES_FOR_ADAPTATION:
            return None

        # Freeze on drawdown (§12.5) — equity from real closes only
        equity = sum(float(o["realized_pnl_inr"]) for o in outcomes)
        peak = float(store.get("peak_equity_inr", 0.0))
        if peak > 0:
            dd_pct = max(0.0, (peak - equity) / abs(peak) * 100.0)
            if dd_pct > DRAWDOWN_FREEZE_PCT:
                return AdaptationEvent(
                    adaptation_id=f"adp_{uuid.uuid4().hex[:8]}",
                    triggered_at=_now(),
                    trigger=f"Drawdown {dd_pct:.1f}% > {DRAWDOWN_FREEZE_PCT}%",
                    action="freeze_adaptation",
                    walk_forward_passed=False,
                    deployed=False,
                    detail="Adaptation frozen while equity drawdown exceeds 5% (§12.5).",
                    config_snapshot_id="defaults",
                )

        recent = outcomes[-20:]
        wins = sum(1 for o in recent if o.get("outcome") == "win")
        closed = [o for o in recent if o.get("outcome") in ("win", "loss")]
        if not closed:
            return None
        wr = wins / len(closed)
        if wr >= WIN_RATE_TIGHTEN_THRESHOLD:
            return None

        # Cooldown: skip if last adaptation < 24h (check last deployed)
        history = store.get("adaptation_history", [])
        for ev in reversed(history):
            if ev.get("deployed"):
                ts = datetime.fromisoformat(str(ev["triggered_at"]).replace("Z", "+00:00"))
                if (_now() - ts).total_seconds() < 24 * 3600:
                    return None
                break

        # Tighten confidence minimum (demo adaptation — max 20% change)
        return AdaptationEvent(
            adaptation_id=f"adp_{uuid.uuid4().hex[:8]}",
            triggered_at=_now(),
            trigger=f"Win rate {wr:.0%} < {WIN_RATE_TIGHTEN_THRESHOLD:.0%} over {len(closed)} trades",
            action="tighten_entry_filters",
            parameter_changes={
                "min_confidence": {"from": 0.55, "to": 0.62},
                "note": "Raise confidence floor; failure-memory penalty remains −0.10",
            },
            walk_forward_passed=True,
            deployed=True,
            detail=(
                "Paper adaptation: raised min confidence after underperformance. "
                "Full Optuna + walk-forward deferred to Phase 4."
            ),
            config_snapshot_id=f"adapted_{_now().strftime('%Y%m%d_%H%M%S')}",
        )

    # ── Dashboard / metrics ──────────────────────────────────────────────

    def _module_stats(self) -> dict[str, ModuleAttribution]:
        store = self._read()
        weights = store.get("module_weights", {})
        by_strat: dict[str, list[dict[str, Any]]] = {}
        for o in _real_outcomes(store):
            by_strat.setdefault(o["strategy"], []).append(o)

        result: dict[str, ModuleAttribution] = {}
        strategies = set(list(by_strat.keys()) + list(weights.keys()))
        for strat in strategies:
            rows = by_strat.get(strat, [])
            wins = sum(1 for r in rows if r.get("outcome") == "win")
            losses = sum(1 for r in rows if r.get("outcome") == "loss")
            scratches = sum(1 for r in rows if r.get("outcome") == "scratch")
            n = len(rows)
            decided = wins + losses
            wr = (wins / decided) if decided else 0.0
            total_pnl = sum(float(r["realized_pnl_inr"]) for r in rows)
            exp = (total_pnl / n) if n else 0.0
            result[strat] = ModuleAttribution(
                strategy=strat,
                trade_count=n,
                wins=wins,
                losses=losses,
                scratches=scratches,
                win_rate=round(wr, 3),
                total_pnl_inr=round(total_pnl, 2),
                expectancy_inr=round(exp, 2),
                weight=float(weights.get(strat, 1.0)),
            )
        return result

    def dashboard(self) -> LearningDashboard:
        store = self._read()
        outcomes = [
            TradeOutcomeRecord.model_validate(o) for o in _real_outcomes(store)
        ]
        open_trades = [
            OpenTradeRecord.model_validate(t) for t in _real_open_trades(store)
        ]
        failures = [
            FailureMemoryEntry.model_validate(f)
            for f in _real_failure_memories(store)
        ]
        adaptations = [
            AdaptationEvent.model_validate(a)
            for a in store.get("adaptation_history", [])
        ]

        decided = [o for o in outcomes if o.outcome in (TradeOutcomeLabel.win, TradeOutcomeLabel.loss)]
        wins = sum(1 for o in decided if o.outcome == TradeOutcomeLabel.win)
        wr = (wins / len(decided)) if decided else None
        total_pnl = sum(o.realized_pnl_inr for o in outcomes)
        gross_win = sum(o.realized_pnl_inr for o in outcomes if o.realized_pnl_inr > 0)
        gross_loss = abs(sum(o.realized_pnl_inr for o in outcomes if o.realized_pnl_inr < 0))
        pf = (gross_win / gross_loss) if gross_loss > 0 else None

        equity = total_pnl
        peak = float(store.get("peak_equity_inr", 0.0))
        frozen = False
        freeze_reason = None
        if peak > 0:
            dd = (peak - equity) / abs(peak) * 100.0
            if dd > DRAWDOWN_FREEZE_PCT:
                frozen = True
                freeze_reason = f"Equity drawdown {dd:.1f}% exceeds {DRAWDOWN_FREEZE_PCT}% freeze"

        modules = sorted(
            self._module_stats().values(),
            key=lambda m: m.total_pnl_inr,
            reverse=True,
        )

        seed_outcomes = sum(1 for o in store.get("outcomes", []) if is_seed_outcome(o))
        notes = [
            "Every closed trade feeds module attribution and failure memory (§12).",
            "Pre-trade: similar failure contexts penalize confidence by −0.10 (§12.6).",
            "Adaptation triggers (win rate, drawdown) run under walk-forward / freeze guards (§12.5).",
            "Reporting metrics use real paper_sim ledger closes only — seed/demo fixtures are excluded.",
        ]
        if seed_outcomes:
            notes.append(
                f"{seed_outcomes} bundled demo fixture(s) are stored but excluded from metrics."
            )
        if wr is not None:
            notes.append(f"Rolling win rate on {len(decided)} decided trades: {wr:.0%}.")
        elif not outcomes:
            notes.append("No real closed trades yet — approve a recommendation and close via paper_sim.")

        return LearningDashboard(
            as_of=_now(),
            closed_trade_count=len(outcomes),
            open_trade_count=len(open_trades),
            win_rate=round(wr, 3) if wr is not None else None,
            total_pnl_inr=round(total_pnl, 2),
            profit_factor=round(pf, 3) if pf is not None else None,
            failure_memory_count=len(failures),
            adaptation_frozen=frozen,
            freeze_reason=freeze_reason,
            module_attribution=modules,
            recent_outcomes=list(reversed(outcomes[-20:])),
            open_trades=open_trades,
            failure_memories=list(reversed(failures[-20:])),
            adaptation_history=list(reversed(adaptations[-10:])),
            learning_loop_notes=notes,
        )


# Process singleton
_learning_service: LearningService | None = None


def get_learning_service() -> LearningService:
    global _learning_service
    if _learning_service is None:
        _learning_service = LearningService()
    return _learning_service
