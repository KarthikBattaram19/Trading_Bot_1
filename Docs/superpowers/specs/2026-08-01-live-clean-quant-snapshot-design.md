# Live-clean Quant Snapshot + Strategy Coverage Gate — Design Spec

| Field | Value |
|---|---|
| Date | 2026-08-01 |
| Status | Approved for implementation |
| Approach | Shared Quant Snapshot Store + per-strategy coverage gate |
| Modes | Full backfill in `shadow`, `paper`, and `live` |

## 1. Goal

Make recommendation quant inputs **live-clean**:

- Backfill real history for GARCH, IV z, RV, and earnings.
- No `[spot]*5` synthetic history, no silent `garch=0.28`, no demo/stub marks in ranking.
- Apply per-strategy coverage before SH-4 can select that strategy.
- Surface coverage warnings when a strategy’s cycle is aborted.

## 2. Locked decisions

| Decision | Choice |
|---|---|
| Modes | Option C (full signal backfill) in all `EXECUTION_MODE` values |
| Coverage | Per strategy: `eligible/scanned >= 0.80` AND `eligible >= 50` |
| On abort | Strategy unavailable for SH-4 this cycle; other strategies may still publish |
| All strategies abort | Empty `recommendations[]` + cycle warning (HTTP 200) |
| Synthetic fills | Forbidden for ranking (demo/stub only in tests / explicit offline harness) |
| Earnings source (v1) | File-backed earnings calendar + `Market_News` imminent overlay |

## 3. Architecture

```
FNO universe (G11)
  → Universe enrichment (LTP + ATM)
  → QuantSnapshotStore (candles, IV history, earnings calendar, news)
  → Per-strategy coverage gate
  → SH-4 (available_strategies only)
  → Retail gates → score → top-3
```

## 4. QuantSnapshot

Per symbol, each signal carries `value` + `usable` + `reason`:

- Live marks: spot, ATM IV, premium, volume/OI/spread/DTE
- Daily price history → GARCH(1,1); usable only if `min_observations` met and not distorted for cheap-vol trust
- Intraday IV series → IV z
- Intraday candles → realized vol
- Earnings calendar → `days_to_earnings`

## 5. Per-strategy eligibility

| Strategy | Eligible when |
|---|---|
| `simple_volatility` | live marks + usable IV + usable GARCH |
| `vega_scalping` | simple_vol inputs + usable IV z |
| `gamma_scalping` | live marks + usable IV + (usable RV **or** usable days_to_earnings) + usable GARCH **unless** earnings-gap with `days_to_earnings <= 1` |

```
eligible = count(symbols meeting required inputs)
coverage = eligible / scanned
publish = coverage >= 0.80 AND eligible >= 50
else: abort strategy + warning
```

## 6. SH-4 integration

`select_strategy_sh4(..., available_strategies)` skips rows that would select an aborted strategy (`strategy_coverage_abort`), falling through or returning `blocked` if nothing remains.

## 7. API

`RecommendationResponse.coverage_by_strategy[]` plus `analysis_notes` lines such as:

`STRATEGY_COVERAGE_ABORT vega_scalping: eligible=12/210 (5.7%) < 80% or <50`

## 8. Out of scope

- Score/confidence recalibration
- Broker margin API
- Third-party earnings vendor
- Supervision / ranked-fallback changes
