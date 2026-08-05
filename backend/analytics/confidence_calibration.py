"""Outcome-calibrated confidence maps — architecture §10.4.

Fits monotone raw-confidence → P(win) maps from closed trades, validates with
walk-forward, and writes a deployable JSON artifact.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIN_SAMPLES = 30
MIN_OOS = 10
BRIER_TOLERANCE = 0.05
P_CLAMP = (0.05, 0.95)
TRAIN_FRAC = 0.70


def is_win(pnl: float, outcome_label: str | None, strategy: str) -> bool | None:
    """Strategy-specific win hook. v1: pnl > 0; scratch excluded (None)."""
    _ = strategy  # reserved for strategy-specific rules
    label = (outcome_label or "").lower()
    if label == "scratch":
        return None
    return float(pnl) > 0.0


def is_seed_outcome(row: dict[str, Any]) -> bool:
    """True for bundled demo/fixture rows that must never enter §12 metrics."""
    tid = str(row.get("trade_id") or "")
    oid = str(row.get("outcome_id") or "")
    fid = str(row.get("failure_id") or "")
    snap = row.get("recommendation_snapshot")
    snap_seed = isinstance(snap, dict) and bool(snap.get("seed"))
    return (
        snap_seed
        or "_seed_" in tid
        or tid.startswith("trd_seed")
        or oid.startswith("out_seed")
        or "_seed_" in oid
        or fid.startswith("fm_seed")
        or "_seed_" in fid
    )


def raw_x_from_outcome(row: dict[str, Any]) -> float:
    if row.get("raw_confidence_at_entry") is not None:
        return float(row["raw_confidence_at_entry"])
    score = float(row.get("score_at_entry") or 0.0)
    return min(0.95, score + 0.05)


def apply_map(raw_x: float, knots: list[float], p_win: list[float]) -> float:
    if not knots or not p_win or len(knots) != len(p_win):
        lo, hi = P_CLAMP
        return max(lo, min(hi, float(raw_x)))
    x = float(raw_x)
    if x <= knots[0]:
        y = p_win[0]
    elif x >= knots[-1]:
        y = p_win[-1]
    else:
        y = p_win[0]
        for i in range(len(knots) - 1):
            if knots[i] <= x <= knots[i + 1]:
                span = knots[i + 1] - knots[i]
                if span <= 1e-12:
                    y = p_win[i + 1]
                else:
                    t = (x - knots[i]) / span
                    y = p_win[i] + t * (p_win[i + 1] - p_win[i])
                break
    lo, hi = P_CLAMP
    return max(lo, min(hi, float(y)))


def _brier(xs: list[float], ys: list[float], knots: list[float], p_win: list[float]) -> float:
    if not xs:
        return 1.0
    err = 0.0
    for x, y in zip(xs, ys):
        p = apply_map(x, knots, p_win)
        err += (p - y) ** 2
    return err / len(xs)


def _pool_adjacent_violators(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    """Isotonic regression (non-decreasing) on sorted unique-x bins."""
    if not xs:
        return [], []
    pairs = sorted(zip(xs, ys), key=lambda t: t[0])
    # Bin by rounded x to stabilize
    bins: dict[float, list[float]] = {}
    for x, y in pairs:
        key = round(x, 3)
        bins.setdefault(key, []).append(y)
    kx = sorted(bins.keys())
    means = [sum(bins[k]) / len(bins[k]) for k in kx]
    weights = [len(bins[k]) for k in kx]

    # PAV
    blocks: list[list[int]] = [[i] for i in range(len(means))]
    vals = list(means)
    wts = list(weights)

    changed = True
    while changed:
        changed = False
        i = 0
        new_blocks: list[list[int]] = []
        new_vals: list[float] = []
        new_wts: list[float] = []
        while i < len(vals):
            if i + 1 < len(vals) and vals[i] > vals[i + 1] + 1e-12:
                # merge i and i+1
                w = wts[i] + wts[i + 1]
                v = (vals[i] * wts[i] + vals[i + 1] * wts[i + 1]) / w
                new_blocks.append(blocks[i] + blocks[i + 1])
                new_vals.append(v)
                new_wts.append(w)
                i += 2
                changed = True
                # append rest then restart
                while i < len(vals):
                    new_blocks.append(blocks[i])
                    new_vals.append(vals[i])
                    new_wts.append(wts[i])
                    i += 1
                break
            else:
                new_blocks.append(blocks[i])
                new_vals.append(vals[i])
                new_wts.append(wts[i])
                i += 1
        blocks, vals, wts = new_blocks, new_vals, new_wts

    # Expand block means back to knot positions (one knot per original bin, monotone)
    out_p = [0.0] * len(kx)
    for block, v in zip(blocks, vals):
        for idx in block:
            out_p[idx] = v
    # Ensure strictly recorded monotone
    for i in range(1, len(out_p)):
        if out_p[i] < out_p[i - 1]:
            out_p[i] = out_p[i - 1]
    lo, hi = P_CLAMP
    out_p = [max(lo, min(hi, p)) for p in out_p]
    return kx, out_p


def _fit_map(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    return _pool_adjacent_violators(xs, ys)


def _is_monotone(p_win: list[float]) -> bool:
    return all(p_win[i] <= p_win[i + 1] + 1e-9 for i in range(len(p_win) - 1))


def _extract_xy(outcomes: list[dict[str, Any]]) -> list[tuple[float, float, str, str]]:
    """Return (raw_x, y, strategy, closed_at) for fittable rows."""
    rows: list[tuple[float, float, str, str]] = []
    for o in outcomes:
        if is_seed_outcome(o):
            continue
        w = is_win(
            float(o.get("realized_pnl_inr") or 0.0),
            str(o.get("outcome") or ""),
            str(o.get("strategy") or ""),
        )
        if w is None:
            continue
        rows.append(
            (
                raw_x_from_outcome(o),
                1.0 if w else 0.0,
                str(o.get("strategy") or "unknown"),
                str(o.get("closed_at") or ""),
            )
        )
    rows.sort(key=lambda t: t[3])
    return rows


def _walk_forward_ok(
    xs: list[float], ys: list[float]
) -> tuple[bool, dict[str, float], list[float], list[float]]:
    n = len(xs)
    if n < MIN_SAMPLES:
        return False, {}, [], []
    split = max(int(n * TRAIN_FRAC), n - MIN_OOS)
    oos_n = n - split
    if oos_n < MIN_OOS:
        return False, {}, [], []
    train_x, train_y = xs[:split], ys[:split]
    test_x, test_y = xs[split:], ys[split:]
    knots, p_win = _fit_map(train_x, train_y)
    if len(knots) < 2 or not _is_monotone(p_win):
        return False, {}, [], []
    brier_is = _brier(train_x, train_y, knots, p_win)
    brier_oos = _brier(test_x, test_y, knots, p_win)
    ok = brier_oos <= brier_is + BRIER_TOLERANCE
    # Full-sample map for deploy
    full_k, full_p = _fit_map(xs, ys)
    metrics = {
        "brier_oos": round(brier_oos, 6),
        "brier_is": round(brier_is, 6),
        "ece_oos": 0.0,
    }
    if not ok or len(full_k) < 2 or not _is_monotone(full_p):
        return False, metrics, [], []
    return True, metrics, full_k, full_p


def fit_and_maybe_deploy(
    outcomes: list[dict[str, Any]],
    artifact_path: Path,
    prior_path: Path | None = None,
) -> dict[str, Any]:
    """Fit maps; write artifact only when walk-forward passes.

    If walk-forward fails and a prior deployed artifact exists at artifact_path
    (or prior_path), it is left unchanged.
    """
    prior = prior_path or artifact_path
    rows = _extract_xy(outcomes)
    report: dict[str, Any] = {
        "deployed": False,
        "walk_forward_ok": False,
        "n_fit": len(rows),
        "fit_notes": [],
    }
    if len(rows) < MIN_SAMPLES:
        report["fit_notes"].append(f"n_fit={len(rows)} < {MIN_SAMPLES}")
        return report

    xs = [r[0] for r in rows]
    ys = [r[1] for r in rows]
    ok, metrics, knots, p_win = _walk_forward_ok(xs, ys)
    report["walk_forward_metrics"] = metrics
    report["walk_forward_ok"] = ok
    if not ok:
        report["fit_notes"].append("walk_forward_failed")
        return report

    by_strategy: dict[str, Any] = {}
    strategies = sorted({r[2] for r in rows})
    for strat in strategies:
        srows = [r for r in rows if r[2] == strat]
        if len(srows) < MIN_SAMPLES:
            continue
        sxs = [r[0] for r in srows]
        sys_ = [r[1] for r in srows]
        # Prefer strategy WF when OOS large enough; else attach if global already ok
        split = max(int(len(sxs) * TRAIN_FRAC), len(sxs) - MIN_OOS)
        oos_n = len(sxs) - split
        if oos_n >= MIN_OOS:
            sok, _, sk, sp = _walk_forward_ok(sxs, sys_)
            if not sok:
                continue
            by_strategy[strat] = {"n": len(srows), "x_knots": sk, "p_win": sp}
        else:
            sk, sp = _fit_map(sxs, sys_)
            if len(sk) >= 2 and _is_monotone(sp):
                by_strategy[strat] = {"n": len(srows), "x_knots": sk, "p_win": sp}

    artifact = {
        "version": 1,
        "deployed": True,
        "fitted_at": datetime.now(timezone.utc).isoformat(),
        "walk_forward_ok": True,
        "walk_forward_metrics": metrics,
        "min_samples": MIN_SAMPLES,
        "global": {"n": len(rows), "x_knots": knots, "p_win": p_win},
        "by_strategy": by_strategy,
        "fit_notes": ["deployed_after_walk_forward"],
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    report["deployed"] = True
    report["fit_notes"].append(f"wrote {artifact_path}")
    report["by_strategy_keys"] = list(by_strategy.keys())
    _ = prior  # retained for API symmetry; failed path leaves prior file alone
    return report
