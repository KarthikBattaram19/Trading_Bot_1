# GARCH(1,1) MLE-fit weights — design

Date: 2026-08-04
Source: `Improve_Recoemmendation_Engine.md` §3.4 / backlog item F34

## Problem

`backend/quant/signals/garch.py::forecast_garch_11` runs a GARCH(1,1)-shaped
recursive variance filter, but `gamma=0.05, alpha=0.05, beta=0.90` are fixed
config constants applied identically to every symbol. Real GARCH(1,1) fits
these weights per series via maximum likelihood; without that step every
underlying — regardless of how its volatility actually clusters or reverts —
gets the same reaction to shocks and the same persistence. This is a
legitimate simplification for a paper-trading system, but any language
claiming "the model was fit" is inaccurate.

Secondary issue in the same function: long-run variance `VL` is computed as
`mean(r²)` (returns treated as zero-mean) instead of the mean-centered sample
variance `mean((r - r̄)²)`. Immaterial for near-zero-drift daily equity
returns, but incorrect for a trending name.

## Goals

- Fit `(γ, α, β)` per symbol via MLE when there's enough history to do so
  reliably; fall back to the existing fixed weights when there isn't.
- Fix `VL` to use mean-centered sample variance.
- Make it observable downstream whether a given forecast was actually fit.
- No behavior change for existing callers that don't opt in.

## Non-goals

- Persisting/caching fitted weights across requests (refit is cheap; see
  Performance below).
- Changing the GARCH recursion's shape, annualization, gap/insufficient-
  history handling (Q-14, MD-10), or the `garch_one_step` VT-4 worked-example
  helper — all unchanged.

## Design

### Three-tier threshold on return count `n`

| `n` | Behavior |
| --- | --- |
| `n < min_observations` (20, unchanged) | `insufficient_history`, distorted — unchanged |
| `min_observations ≤ n < fit_min_observations` (new, default 60) | Too thin to fit reliably. Use fixed config weights. `fitted=False`, **not** distorted — same output as today. |
| `n ≥ fit_min_observations` | Attempt MLE fit. Converged → use fitted weights, `fitted=True`. Failed/degenerate → `garch_distorted=True`, `reason="garch_fit_failed"`. |

`fit_min_observations` is higher than `min_observations` because fitting 3
free parameters off ~20 points is unstable; 60 (~3 months of daily bars)
gives the optimizer enough signal.

### `garch.py` changes

- New private helper `_sigma2_path(returns, vl, gamma, alpha, beta) -> list[float]`
  factoring out the recursive variance walk currently inlined in
  `forecast_garch_11`'s loop. Reused by both the plain filter and the MLE
  objective so the fit optimizes exactly the recursion that produces the
  forecast — no drift between what's fit and what's used.
- New `fit_garch_11_mle(cleaned_returns, vl, *, initial=(0.05, 0.90)) -> FittedGarchWeights | None`:
  - Minimizes the negative Gaussian log-likelihood
    `NLL = 0.5 * sum(log(sigma2_t) + r_t**2 / sigma2_t)` over `t = 2..n`
    (skipping `t=1`, which has no lagged residual — same convention the
    current loop uses).
  - Free parameters: `alpha, beta` (2D), with `gamma = 1 - alpha - beta`.
    `scipy.optimize.minimize(method="SLSQP")`, bounds `alpha, beta ∈ [1e-6, 1-1e-6]`,
    inequality constraint `alpha + beta ≤ 1 - 1e-6` (keeps `gamma > 0`,
    stationarity). Warm-started at today's fixed defaults `(0.05, 0.90)`.
  - Returns `None` on: optimizer `success=False`, any non-finite value in the
    resulting sigma2 path, or a fitted `gamma <= 0`.
- `forecast_garch_11(...)` gains `fit_weights: bool = False` and
  `fit_min_observations: int = 60`. Existing `gamma`/`alpha`/`beta` params
  become the fallback weights used when fitting is off, insufficient, or
  fails-closed is not triggered (the 20–59 tier).
- `VL` computation changes from `sum(r*r for r in cleaned) / n` to
  mean-centered: `mean = sum(cleaned)/n; vl = sum((r-mean)**2 for r in cleaned)/n`.
  Applies to both the fit and fallback paths (single code path, no branching).
- `GarchForecastResult` gains `fitted: bool`, `gamma_used: float | None`,
  `alpha_used: float | None`, `beta_used: float | None`.

### Call site — `backend/services/quant_snapshot.py`

```python
result = forecast_garch_11(
    log_returns_from_prices(history),
    gamma=float(gcfg.get("gamma_weight", 0.05)),
    alpha=float(gcfg.get("alpha_weight", 0.05)),
    beta=float(gcfg.get("beta_weight", 0.9)),
    annualization_factor=int(gcfg.get("annualization_factor", 252)),
    min_observations=min_obs,
    fit_weights=bool(gcfg.get("enable_mle_fit", True)),
    fit_min_observations=int(gcfg.get("fit_min_observations", 60)),
)
```

Two new keys, both optional with safe defaults — no change for callers/tests
that construct `cfg` without them.

### Config / schema / dependencies

- `backend/config/trading_parameters.defaults.json` → `garch_forecast`:
  add `"enable_mle_fit": true, "fit_min_observations": 60`.
- `backend/schemas/trading_parameters.schema.json` → `GarchForecastParams`:
  add `enable_mle_fit` (boolean) and `fit_min_observations` (integer,
  minimum 20) properties. (Also reconcile the pre-existing drift where
  `min_observations`/`max_log_return_gap` are set in defaults.json but
  absent from this schema object, since the edit touches the same block.)
- `backend/requirements.txt`: add `scipy>=1.13.0` (already present
  transitively via chromadb, but this fix makes it a direct import —
  declare it explicitly).

### Performance

The optimization is a 2-parameter SLSQP fit over ≤ a few hundred daily
returns — sub-millisecond, negligible next to the 20s universe-enrichment
I/O budget (`recommendation_universe_enrichment.max_symbols`, network-bound).
Refit-per-call (no caching) keeps the design simple and always uses the
freshest history; revisit only if profiling shows otherwise.

### Docs

- `Docs/Trading_Parameters.md`: update the GARCH section to describe the
  three-tier fit/fallback/distorted behavior instead of implying fixed
  weights throughout.
- `Improve_Recoemmendation_Engine.md` §3.4: mark resolved, describe the new
  behavior and the remaining fixed-weight fallback tier (20–59 obs) as an
  intentional, documented simplification.

## Testing plan

`backend/tests/quant/test_garch.py`:

1. `n ≥ 60` well-behaved synthetic series → `fitted=True`, weights sum to 1,
   fitted weights differ from the fixed defaults.
2. `20 ≤ n < 60` → `fitted=False`, weights equal the fixed defaults passed
   in, `usable=True` (matches today's behavior).
3. Forced fit failure (monkeypatch `fit_garch_11_mle` to return `None`) at
   `n ≥ 60` → `garch_distorted=True`, `reason="garch_fit_failed"`,
   `usable=False`.
4. VL mean-centering: series with nonzero drift → `result.vl` matches
   `mean((r-r̄)²)`, not `mean(r²)`.
5. `fit_garch_11_mle` unit-level: recovers weights close to the generating
   process on a series simulated from known `(γ,α,β)` (sanity check that the
   optimizer converges to something sensible, not just "doesn't crash").

Existing tests reviewed for compatibility:
- `test_vt4_worked_example_annualized_vol` — uses `garch_one_step`, untouched.
- `test_garch_weights_must_sum_to_one`, `test_q14_insufficient_history_marks_distorted`,
  `test_md10_gap_blocks_garch`, `test_forecast_from_price_history_usable` —
  call `forecast_garch_11` without `fit_weights`, defaults to `False`,
  unaffected.
- `backend/tests/test_quant_snapshot.py` — both cases use ≤ 39 returns
  (< 60 `fit_min_observations`), so they land on the unchanged fallback
  tier and stay green without modification.

## Open risk

MLE convergence quality on real (noisy, sometimes near-flat) NSE daily
return series is unverified until implemented — the fail-closed behavior
(`garch_fit_failed` → distorted) is the safety valve if fits turn out
unreliable in practice more often than expected. Worth a quick manual spot
check against a few real symbols' history during implementation, not just
synthetic data.
