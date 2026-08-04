# GARCH(1,1) MLE-fit weights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace GARCH(1,1)'s fixed, unfitted `(γ,α,β)` weights with a per-symbol MLE fit (fail-closed to distorted when the fit can't run reliably, fail-open to the fixed weights when there simply isn't enough history to attempt one), and fix `VL` to use mean-centered sample variance.

**Architecture:** `backend/quant/signals/garch.py` gains a shared `_sigma2_path` recursion helper (used by both the plain filter and a new MLE objective), a `fit_garch_11_mle` function built on `scipy.optimize.minimize`, and a three-tier threshold in `forecast_garch_11` that picks fitted vs. fixed vs. distorted based on how much history is available. `backend/services/quant_snapshot.py` opts in via two new config keys.

**Tech Stack:** Python 3.14, `scipy.optimize` (SLSQP), `pytest` (`asyncio_mode=auto`, run from repo root).

## Global Constraints

- `min_observations` (existing, default 20): below this, `insufficient_history` — unchanged, do not touch this tier's behavior.
- `fit_min_observations` (new, default 60): below this (but ≥ `min_observations`), use fixed weights, `fitted=False`, **not** distorted.
- At/above `fit_min_observations`: attempt MLE fit; on failure, `garch_distorted=True`, `reason="garch_fit_failed"`.
- MLE free parameters are `alpha, beta` with `gamma = 1 - alpha - beta`; bounds `[1e-6, 1-1e-6]` each; constraint `alpha + beta ≤ 1 - 1e-6`; warm start `(0.05, 0.90)`.
- `VL` = mean-centered sample variance `mean((r - r̄)²)`, applied on every path (fit and fixed), not just the fit path.
- No caching of fitted weights across requests — refit on every call.
- `scipy>=1.13.0` becomes a direct (declared) dependency of `backend/requirements.txt`.
- Existing tests that call `forecast_garch_11` without `fit_weights` must keep passing unmodified (default `fit_weights=False`).
- Run tests from the repo root: `cd C:\Project_Volatality_Trading_by_Cursor && pytest backend/tests/quant/test_garch.py -v` (or the full suite where noted).

---

### Task 1: `_sigma2_path` helper + mean-centered VL

**Files:**
- Modify: `backend/quant/signals/garch.py`
- Test: `backend/tests/quant/test_garch.py`

**Interfaces:**
- Produces: `_sigma2_path(returns: Sequence[float], *, vl: float, gamma: float, alpha: float, beta: float) -> list[float]` — `path[i]` is the one-step-ahead variance forecast made after observing `returns[0..i]` (i.e. the forecast for `returns[i+1]`).
- Produces: `forecast_garch_11`'s `VL` computation changes from `mean(r**2)` to `mean((r - r̄)**2)`; `GarchForecastResult.vl` reflects this everywhere it's returned.

This task is a pure refactor + one bug fix — no MLE yet, no new params on `forecast_garch_11`. It must reproduce `forecast_garch_11`'s existing numeric behavior for `VL`-independent assertions and change only the `VL` value itself.

- [ ] **Step 1: Write the failing test for mean-centered VL**

Add to `backend/tests/quant/test_garch.py`:

```python
def test_vl_is_mean_centered_not_mean_of_squares():
    """§3.4 secondary issue: VL must be mean((r-r̄)²), not mean(r²), for drifting series."""
    # Constant positive drift: every return is 0.01, so r̄ = 0.01 and
    # mean-centered variance is exactly 0.0 -- but mean(r²) would be 0.0001.
    returns = [0.01] * 25
    result = forecast_garch_11(returns, min_observations=20)
    assert result.vl is not None
    assert result.vl == pytest.approx(0.0, abs=1e-12)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Project_Volatality_Trading_by_Cursor && pytest backend/tests/quant/test_garch.py::test_vl_is_mean_centered_not_mean_of_squares -v`
Expected: FAIL — `result.vl` is `0.0001`, not `~0.0`, because the current code computes `mean(r**2)`.

- [ ] **Step 3: Add `_sigma2_path` and switch `VL` to mean-centered variance**

In `backend/quant/signals/garch.py`, add this helper near the top (after `log_returns_from_prices`, before `garch_one_step`):

```python
def _sigma2_path(
    returns: Sequence[float],
    *,
    vl: float,
    gamma: float,
    alpha: float,
    beta: float,
) -> list[float]:
    """Recursive one-step-ahead variance path.

    ``path[i]`` is the forecast produced after observing ``returns[0..i]`` —
    i.e. it's the variance forecast *for* ``returns[i+1]``. Shared by the
    plain filter and the MLE fit objective so both walk the identical
    recursion.
    """
    sigma2 = vl
    path: list[float] = []
    for r in returns:
        prior_u2 = r * r
        prior_sigma2 = sigma2
        sigma2 = gamma * vl + alpha * prior_u2 + beta * prior_sigma2
        path.append(sigma2)
    return path
```

Then in `forecast_garch_11`, replace:

```python
    # Long-run variance VL = sample variance of log returns (H5)
    vl = sum(r * r for r in cleaned) / n
```

with:

```python
    # Long-run variance VL = mean-centered sample variance of log returns (H5)
    mean_r = sum(cleaned) / n
    vl = sum((r - mean_r) ** 2 for r in cleaned) / n
```

And replace the manual loop:

```python
    # Initialize σ² with VL; iterate so last step is today's forecast (H6–H8)
    sigma2 = vl
    prior_u2 = cleaned[0] ** 2
    for r in cleaned:
        prior_u2 = r * r
        prior_sigma2 = sigma2
        sigma2 = gamma * vl + alpha * prior_u2 + beta * prior_sigma2
```

with a call to the new helper:

```python
    # Walk the recursive variance path; last entry is today's forecast (H6–H8)
    path = _sigma2_path(cleaned, vl=vl, gamma=gamma, alpha=alpha, beta=beta)
    sigma2 = path[-1]
    prior_u2 = cleaned[-1] ** 2
    prior_sigma2 = path[-2] if len(path) > 1 else vl
```

(The rest of `forecast_garch_11` — building `daily`, `annual`, and the returned `GarchForecastResult` — is unchanged in this task.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Project_Volatality_Trading_by_Cursor && pytest backend/tests/quant/test_garch.py -v`
Expected: all pass, including the new `test_vl_is_mean_centered_not_mean_of_squares` and all four pre-existing tests (`test_vt4_worked_example_annualized_vol` uses `garch_one_step`, untouched; the other three call `forecast_garch_11` and only depend on VL's *sign*/usability, not its exact old value).

- [ ] **Step 5: Commit**

```bash
git add backend/quant/signals/garch.py backend/tests/quant/test_garch.py
git commit -m "Fix GARCH VL to use mean-centered sample variance, not mean(r^2)

§3.4 secondary issue: VL was mean(r^2), i.e. treated returns as zero-mean.
Correct sample variance is mean((r-r_bar)^2). Immaterial for near-zero-drift
daily equity returns but wrong for a trending name. Also factors the
recursive variance walk into _sigma2_path() so the upcoming MLE fit
objective can share the exact same recursion the forecast uses."
```

---

### Task 2: `fit_garch_11_mle` — standalone MLE fitting function

**Files:**
- Modify: `backend/quant/signals/garch.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/quant/test_garch.py`

**Interfaces:**
- Consumes: `_sigma2_path` from Task 1.
- Produces: `FittedGarchWeights` (frozen dataclass: `gamma: float`, `alpha: float`, `beta: float`).
- Produces: `fit_garch_11_mle(cleaned_returns: Sequence[float], vl: float, *, initial: tuple[float, float] = (0.05, 0.90)) -> FittedGarchWeights | None` — `None` means "fit failed/degenerate," caller decides what that means (Task 3).

This task adds fitting in isolation — `forecast_garch_11` is not wired to it yet, so no existing behavior changes.

- [ ] **Step 1: Add scipy as a direct dependency**

In `backend/requirements.txt`, after the `numpy>=2.0.0` line, add:

```
scipy>=1.13.0
```

Run: `cd C:\Project_Volatality_Trading_by_Cursor && python -m pip install -r backend/requirements-dev.txt`
Expected: installs cleanly (scipy is already present transitively via chromadb in this environment, so this should be a no-op version check).

- [ ] **Step 2: Write the failing test — fit recovers known generating weights**

Add to `backend/tests/quant/test_garch.py`:

```python
import random

from backend.quant.signals.garch import FittedGarchWeights, fit_garch_11_mle


def _simulate_garch_returns(
    n: int, *, gamma: float, alpha: float, beta: float, vl: float, seed: int = 7
) -> list[float]:
    """Simulate a GARCH(1,1) return series from known weights (for fit-recovery tests)."""
    rng = random.Random(seed)
    sigma2 = vl
    returns: list[float] = []
    for _ in range(n):
        r = rng.gauss(0.0, math.sqrt(sigma2))
        returns.append(r)
        sigma2 = gamma * vl + alpha * (r * r) + beta * sigma2
    return returns


def test_fit_garch_11_mle_recovers_known_weights_approximately():
    true_gamma, true_alpha, true_beta = 0.10, 0.15, 0.75
    vl = 0.0002
    returns = _simulate_garch_returns(
        400, gamma=true_gamma, alpha=true_alpha, beta=true_beta, vl=vl
    )
    fitted = fit_garch_11_mle(returns, vl)
    assert fitted is not None
    assert isinstance(fitted, FittedGarchWeights)
    assert abs((fitted.gamma + fitted.alpha + fitted.beta) - 1.0) < 1e-6
    # Loose tolerance: MLE on a single 400-point path is noisy, this only
    # asserts the fit lands in the right neighborhood, not exact recovery.
    assert abs(fitted.alpha - true_alpha) < 0.15
    assert abs(fitted.beta - true_beta) < 0.20


def test_fit_garch_11_mle_returns_none_on_degenerate_input():
    # All-zero returns: sigma2 path collapses toward 0, likelihood is degenerate.
    fitted = fit_garch_11_mle([0.0] * 100, vl=0.0)
    assert fitted is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd C:\Project_Volatality_Trading_by_Cursor && pytest backend/tests/quant/test_garch.py::test_fit_garch_11_mle_recovers_known_weights_approximately backend/tests/quant/test_garch.py::test_fit_garch_11_mle_returns_none_on_degenerate_input -v`
Expected: FAIL with `ImportError`/`cannot import name 'fit_garch_11_mle'`.

- [ ] **Step 4: Implement `fit_garch_11_mle`**

In `backend/quant/signals/garch.py`, add the import at the top of the file (with the other imports):

```python
from scipy.optimize import minimize
```

Add the dataclass and objective/fit functions after `_sigma2_path`:

```python
@dataclass(frozen=True, slots=True)
class FittedGarchWeights:
    """MLE-fit GARCH(1,1) weights for one symbol's return history."""

    gamma: float
    alpha: float
    beta: float


def _negative_log_likelihood(
    params: Sequence[float], cleaned: Sequence[float], vl: float
) -> float:
    alpha, beta = params
    gamma = 1.0 - alpha - beta
    path = _sigma2_path(cleaned, vl=vl, gamma=gamma, alpha=alpha, beta=beta)
    total = 0.0
    for sigma2_t, r_next in zip(path[:-1], cleaned[1:]):
        if sigma2_t <= 0 or math.isnan(sigma2_t) or math.isinf(sigma2_t):
            return math.inf
        total += math.log(sigma2_t) + (r_next * r_next) / sigma2_t
    return 0.5 * total


def fit_garch_11_mle(
    cleaned_returns: Sequence[float],
    vl: float,
    *,
    initial: tuple[float, float] = (0.05, 0.90),
) -> FittedGarchWeights | None:
    """MLE-fit (gamma, alpha, beta) to ``cleaned_returns`` via Gaussian log-likelihood.

    Returns ``None`` if the optimizer doesn't converge or the fitted weights
    produce a degenerate (non-positive/non-finite) variance path — caller
    decides what "fit failed" means (Task 3: fail-closed to distorted).
    """
    if vl <= 0 or len(cleaned_returns) < 2:
        return None

    eps = 1e-6
    bounds = [(eps, 1.0 - eps), (eps, 1.0 - eps)]
    constraints = [{"type": "ineq", "fun": lambda p: (1.0 - eps) - (p[0] + p[1])}]

    cleaned = list(cleaned_returns)
    result = minimize(
        _negative_log_likelihood,
        x0=list(initial),
        args=(cleaned, vl),
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )
    if not result.success:
        return None

    alpha, beta = float(result.x[0]), float(result.x[1])
    gamma = 1.0 - alpha - beta
    if gamma <= 0 or alpha <= 0 or beta <= 0:
        return None

    path = _sigma2_path(cleaned, vl=vl, gamma=gamma, alpha=alpha, beta=beta)
    if any(s <= 0 or math.isnan(s) or math.isinf(s) for s in path):
        return None

    return FittedGarchWeights(gamma=gamma, alpha=alpha, beta=beta)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:\Project_Volatality_Trading_by_Cursor && pytest backend/tests/quant/test_garch.py -v`
Expected: all pass, including the two new fit tests and every test from Task 1.

- [ ] **Step 6: Commit**

```bash
git add backend/quant/signals/garch.py backend/requirements.txt backend/tests/quant/test_garch.py
git commit -m "Add fit_garch_11_mle: per-symbol MLE fit for GARCH(1,1) weights

Standalone function, not yet wired into forecast_garch_11 (next commit).
Fits alpha,beta via scipy.optimize.minimize (SLSQP) with gamma=1-alpha-beta,
bounds [1e-6, 1-1e-6], stationarity constraint alpha+beta<=1-1e-6, warm-started
at the current fixed defaults. Returns None on non-convergence or a degenerate
resulting variance path so callers can fail closed.

Declares scipy>=1.13.0 as a direct dependency (was already present
transitively via chromadb, but this makes it a real import)."
```

---

### Task 3: Wire the three-tier fit/fallback/distorted logic into `forecast_garch_11`

**Files:**
- Modify: `backend/quant/signals/garch.py`
- Test: `backend/tests/quant/test_garch.py`

**Interfaces:**
- Consumes: `fit_garch_11_mle`, `FittedGarchWeights` from Task 2; `_sigma2_path` from Task 1.
- Produces: `forecast_garch_11(..., fit_weights: bool = False, fit_min_observations: int = 60)` — new keyword-only params, default `fit_weights=False` preserves current behavior for every existing caller.
- Produces: `GarchForecastResult` gains `fitted: bool = False`, `gamma_used: float | None = None`, `alpha_used: float | None = None`, `beta_used: float | None = None`.
- Produces: new `reason` value `"garch_fit_failed"` for the fit-failure early return.

- [ ] **Step 1: Write the failing tests for all three tiers**

Add to `backend/tests/quant/test_garch.py`:

```python
def test_below_fit_floor_uses_fixed_weights_not_distorted():
    """20 <= n < fit_min_observations: fixed weights, fitted=False, still usable."""
    returns = [0.01, -0.008, 0.005, -0.003] * 10  # n=40
    result = forecast_garch_11(
        returns, min_observations=20, fit_weights=True, fit_min_observations=60
    )
    assert result.usable
    assert result.fitted is False
    assert result.gamma_used == pytest.approx(0.05)
    assert result.alpha_used == pytest.approx(0.05)
    assert result.beta_used == pytest.approx(0.90)


def test_at_fit_floor_fits_and_marks_fitted():
    true_gamma, true_alpha, true_beta = 0.08, 0.12, 0.80
    vl = 0.0002
    returns = _simulate_garch_returns(
        90, gamma=true_gamma, alpha=true_alpha, beta=true_beta, vl=vl, seed=11
    )
    result = forecast_garch_11(
        returns, min_observations=20, fit_weights=True, fit_min_observations=60
    )
    assert result.usable
    assert result.fitted is True
    assert result.gamma_used is not None
    assert abs(result.gamma_used + result.alpha_used + result.beta_used - 1.0) < 1e-6


def test_fit_failure_forces_distorted(monkeypatch):
    import backend.quant.signals.garch as garch_module

    monkeypatch.setattr(garch_module, "fit_garch_11_mle", lambda *a, **k: None)
    returns = [0.01, -0.008, 0.005, -0.003] * 20  # n=80, above fit_min_observations
    result = garch_module.forecast_garch_11(
        returns, min_observations=20, fit_weights=True, fit_min_observations=60
    )
    assert result.garch_distorted is True
    assert result.usable is False
    assert result.reason == "garch_fit_failed"


def test_fit_weights_false_is_default_and_unaffected_by_fit_floor():
    """Backward compatibility: fit_weights defaults False, existing callers untouched."""
    returns = [0.01, -0.008, 0.005, -0.003] * 25  # n=100, would clear fit floor
    result = forecast_garch_11(returns, min_observations=20)
    assert result.usable
    assert result.fitted is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Project_Volatality_Trading_by_Cursor && pytest backend/tests/quant/test_garch.py -v -k "fit_floor or fits_and_marks or fit_failure or fit_weights_false"`
Expected: FAIL — `forecast_garch_11() got an unexpected keyword argument 'fit_weights'`.

- [ ] **Step 3: Update `GarchForecastResult` and `forecast_garch_11`**

In `backend/quant/signals/garch.py`, update the dataclass:

```python
@dataclass(frozen=True, slots=True)
class GarchForecastResult:
    """One-step GARCH(1,1) forecast with distortion / sufficiency flags."""

    sigma_daily: float | None
    sigma_annual: float | None
    vl: float | None
    prior_u2: float | None
    prior_sigma2: float | None
    forecast_sigma2: float | None
    garch_distorted: bool
    insufficient_history: bool
    reason: str | None = None
    observations: int = 0
    fitted: bool = False
    gamma_used: float | None = None
    alpha_used: float | None = None
    beta_used: float | None = None

    @property
    def usable(self) -> bool:
        return (
            not self.garch_distorted
            and not self.insufficient_history
            and self.sigma_annual is not None
            and self.sigma_annual > 0
        )
```

Update `forecast_garch_11`'s signature:

```python
def forecast_garch_11(
    log_returns: Sequence[float],
    *,
    gamma: float = 0.05,
    alpha: float = 0.05,
    beta: float = 0.90,
    annualization_factor: int = 252,
    min_observations: int = 20,
    gap_detected: bool = False,
    fit_weights: bool = False,
    fit_min_observations: int = 60,
) -> GarchForecastResult:
    """Walk GARCH(1,1) through a log-return series; return one-step-ahead annualized vol.

    ``gap_detected`` (MD-10) forces ``garch_distorted`` so cheap-vol entries are blocked.

    ``fit_weights``: when True and ``n >= fit_min_observations``, fits
    (gamma, alpha, beta) per this return series via MLE instead of using the
    fixed ``gamma``/``alpha``/``beta`` arguments; a failed/non-converged fit
    forces ``garch_distorted`` (``reason="garch_fit_failed"``). Below
    ``fit_min_observations`` (but at/above ``min_observations``) the fixed
    weights are used, unchanged from today's behavior.
    """
```

After the existing `zero_sample_variance` early return (which now uses the mean-centered `vl` from Task 1) and before the recursive-walk section, insert the fit-selection block, then adapt the final section to use whichever weights were selected:

```python
    fitted = False
    use_gamma, use_alpha, use_beta = gamma, alpha, beta
    if fit_weights and n >= fit_min_observations:
        fit = fit_garch_11_mle(cleaned, vl)
        if fit is None:
            return GarchForecastResult(
                sigma_daily=None,
                sigma_annual=None,
                vl=vl,
                prior_u2=None,
                prior_sigma2=None,
                forecast_sigma2=None,
                garch_distorted=True,
                insufficient_history=False,
                reason="garch_fit_failed",
                observations=n,
            )
        use_gamma, use_alpha, use_beta = fit.gamma, fit.alpha, fit.beta
        fitted = True

    # Walk the recursive variance path; last entry is today's forecast (H6–H8)
    path = _sigma2_path(cleaned, vl=vl, gamma=use_gamma, alpha=use_alpha, beta=use_beta)
    sigma2 = path[-1]
    prior_u2 = cleaned[-1] ** 2
    prior_sigma2 = path[-2] if len(path) > 1 else vl

    daily = math.sqrt(max(sigma2, 0.0))
    annual = daily * math.sqrt(float(annualization_factor))
    return GarchForecastResult(
        sigma_daily=daily,
        sigma_annual=annual,
        vl=vl,
        prior_u2=prior_u2,
        prior_sigma2=prior_sigma2,
        forecast_sigma2=sigma2,
        garch_distorted=False,
        insufficient_history=False,
        reason=None,
        observations=n,
        fitted=fitted,
        gamma_used=use_gamma,
        alpha_used=use_alpha,
        beta_used=use_beta,
    )
```

This replaces the Task-1 version of the "walk the path" section (the one without `use_gamma`/`use_alpha`/`use_beta`) — the local `gamma`, `alpha`, `beta` parameters remain the fixed-weight fallback values and are what `_assert_weights` still validates at the top of the function, unchanged from today.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Project_Volatality_Trading_by_Cursor && pytest backend/tests/quant/test_garch.py -v`
Expected: all pass — every test from Tasks 1–2 plus the four new tier tests.

- [ ] **Step 5: Commit**

```bash
git add backend/quant/signals/garch.py backend/tests/quant/test_garch.py
git commit -m "Wire MLE fit into forecast_garch_11 with three-tier fallback

n < min_observations (20): insufficient_history, unchanged.
min_observations <= n < fit_min_observations (60): fixed weights, fitted=False,
  not distorted -- same output as before this change.
n >= fit_min_observations: MLE-fit weights; failure to converge or a
  degenerate resulting variance path forces garch_distorted=True with
  reason=\"garch_fit_failed\" (fail closed, no silent fallback once fitting
  is attempted).

fit_weights defaults False so every existing caller is unaffected.
GarchForecastResult now reports fitted/gamma_used/alpha_used/beta_used so
downstream code and logs can see whether a forecast was actually fit."
```

---

### Task 4: Wire config into `quant_snapshot.py`, update config defaults + schema

**Files:**
- Modify: `backend/services/quant_snapshot.py:108-115`
- Modify: `backend/config/trading_parameters.defaults.json`
- Modify: `backend/schemas/trading_parameters.schema.json`
- Test: `backend/tests/test_quant_snapshot.py` (verify only — no edits expected)

**Interfaces:**
- Consumes: `forecast_garch_11(..., fit_weights: bool, fit_min_observations: int)` from Task 3.
- Consumes: `gcfg` dict already built in `build_quant_snapshot` (`backend/services/quant_snapshot.py:66`).

- [ ] **Step 1: Update the config defaults**

In `backend/config/trading_parameters.defaults.json`, in the `garch_forecast` object, change:

```json
  "garch_forecast": {
    "gamma_weight": 0.05,
    "alpha_weight": 0.05,
    "beta_weight": 0.9,
    "annualization_factor": 252,
    "block_when_distorted": true,
    "min_observations": 20,
    "max_log_return_gap": 0.25
  },
```

to:

```json
  "garch_forecast": {
    "gamma_weight": 0.05,
    "alpha_weight": 0.05,
    "beta_weight": 0.9,
    "annualization_factor": 252,
    "block_when_distorted": true,
    "min_observations": 20,
    "max_log_return_gap": 0.25,
    "enable_mle_fit": true,
    "fit_min_observations": 60
  },
```

- [ ] **Step 2: Update the JSON schema**

In `backend/schemas/trading_parameters.schema.json`, find the `GarchForecastParams` definition:

```json
    "GarchForecastParams": {
      "type": "object",
      "description": "Part H — GARCH(1,1) forecast weights.",
      "additionalProperties": false,
      "properties": {
        "gamma_weight": { "type": "number", "minimum": 0, "maximum": 1 },
        "alpha_weight": { "type": "number", "minimum": 0, "maximum": 1 },
        "beta_weight": { "type": "number", "minimum": 0, "maximum": 1 },
        "annualization_factor": { "type": "integer", "const": 252 },
        "block_when_distorted": { "type": "boolean" }
      }
    },
```

Replace with (adds the two new fields, and reconciles the two pre-existing fields — `min_observations`, `max_log_return_gap` — that are already in `trading_parameters.defaults.json` but were missing from this schema object):

```json
    "GarchForecastParams": {
      "type": "object",
      "description": "Part H — GARCH(1,1) forecast weights.",
      "additionalProperties": false,
      "properties": {
        "gamma_weight": { "type": "number", "minimum": 0, "maximum": 1 },
        "alpha_weight": { "type": "number", "minimum": 0, "maximum": 1 },
        "beta_weight": { "type": "number", "minimum": 0, "maximum": 1 },
        "annualization_factor": { "type": "integer", "const": 252 },
        "block_when_distorted": { "type": "boolean" },
        "min_observations": { "type": "integer", "minimum": 1 },
        "max_log_return_gap": { "type": "number", "minimum": 0 },
        "enable_mle_fit": { "type": "boolean" },
        "fit_min_observations": { "type": "integer", "minimum": 1 }
      }
    },
```

- [ ] **Step 3: Wire the call site**

In `backend/services/quant_snapshot.py`, replace:

```python
        result = forecast_garch_11(
            log_returns_from_prices(history),
            gamma=float(gcfg.get("gamma_weight", 0.05)),
            alpha=float(gcfg.get("alpha_weight", 0.05)),
            beta=float(gcfg.get("beta_weight", 0.9)),
            annualization_factor=int(gcfg.get("annualization_factor", 252)),
            min_observations=min_obs,
        )
```

with:

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

- [ ] **Step 4: Run the quant_snapshot suite to confirm no regression**

Run: `cd C:\Project_Volatality_Trading_by_Cursor && pytest backend/tests/test_quant_snapshot.py -v`
Expected: both existing tests pass unchanged — `test_flat_spot_history_marks_garch_unusable` (5 prices, hits the pre-existing `insufficient_history`/`flat` path, untouched) and `test_real_history_yields_usable_garch` (40 prices → 39 log returns, below the new `fit_min_observations=60` default, so it lands on the fixed-weight fallback tier and stays `usable=True` exactly as before).

- [ ] **Step 5: Run the GARCH suite once more for full confidence**

Run: `cd C:\Project_Volatality_Trading_by_Cursor && pytest backend/tests/quant/test_garch.py backend/tests/test_quant_snapshot.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/quant_snapshot.py backend/config/trading_parameters.defaults.json backend/schemas/trading_parameters.schema.json
git commit -m "Wire GARCH MLE fit into quant_snapshot via config

New garch_forecast.enable_mle_fit (default true) and
garch_forecast.fit_min_observations (default 60) config keys drive
forecast_garch_11's fit_weights/fit_min_observations. Both existing
quant_snapshot tests use <60 returns so they stay on the unchanged
fixed-weight fallback tier -- verified, no test changes needed.

Also reconciles GarchForecastParams schema with fields
(min_observations, max_log_return_gap) that were already present in
trading_parameters.defaults.json but missing from the schema object."
```

---

### Task 5: Documentation — Trading_Parameters.md and Improve_Recoemmendation_Engine.md

**Files:**
- Modify: `Docs/Trading_Parameters.md:311-329`
- Modify: `Improve_Recoemmendation_Engine.md` (§3.4 block and the low-priority backlog entry `F34`)

**Interfaces:** None — documentation only, no code/test changes in this task.

- [ ] **Step 1: Update Part H in `Docs/Trading_Parameters.md`**

Replace the section (lines 311–329):

```markdown
## Part H — GARCH(1,1) Forecast Parameters (Vol Trading & Gamma Cheap-Vol Mode)

Used by **Simple Volatility Trading** and **Gamma Scalping mode 1 (cheap vol)**.

| # | Parameter | Symbol | Typical Value | Type | Required When |
|---|---|---|---|---|---|
| H1 | **Long-run variance weight** | γ (gamma) | 5% | Weight | IV < GARCH entry |
| H2 | **Prior squared return weight** | α (alpha) | 5% | Weight | IV < GARCH entry |
| H3 | **Prior variance weight** | β (beta) | 90% | Weight | IV < GARCH entry |
| H4 | **Weight constraint** | γ+α+β | 100% | Constraint | Model validity |
| H5 | **Long-run variance VL** | VL | From sample var of log returns | Computed | Forecast |
| H6 | **Prior squared return** | u²ₙ₋₁ | From return series | Computed | Forecast |
| H7 | **Prior variance** | σ²ₙ₋₁ | From series | Computed | Forecast |
| H8 | **Daily variance forecast** | σ²ₙ | γ·VL + α·u² + β·σ²ₙ₋₁ | Computed | Signal |
| H9 | **Daily volatility** | σ_daily | √σ²ₙ | Computed | Signal |
| H10 | **Annualized forecast vol** | σ_annual | σ_daily × √252 | Percent | **Compare to option IV** |
| H11 | **Post-shock block flag** | `garch_distorted` | Boolean | Risk | Block cheap-vol after black swan |

**Entry condition (cheap vol):** `IV < σ_annual (GARCH forecast)` — annualized option IV must be **below** forecast.
```

with:

```markdown
## Part H — GARCH(1,1) Forecast Parameters (Vol Trading & Gamma Cheap-Vol Mode)

Used by **Simple Volatility Trading** and **Gamma Scalping mode 1 (cheap vol)**.

Weights are **MLE-fit per symbol** (`backend/quant/signals/garch.py::fit_garch_11_mle`,
`scipy.optimize.minimize`) when there's enough history to fit reliably;
otherwise the fixed values below are used as a fallback. Three tiers, keyed
off the number of log returns `n` for that symbol:

| `n` | Weights used | `garch_distorted`? |
|---|---|---|
| `n < min_observations` (20) | none — no forecast | Yes (`insufficient_history`) |
| `min_observations ≤ n < fit_min_observations` (60) | Fixed (H1–H3 below) | No |
| `n ≥ fit_min_observations` (60) | MLE-fit per symbol | No, unless the fit fails to converge (`garch_fit_failed`) |

| # | Parameter | Symbol | Typical Value | Type | Required When |
|---|---|---|---|---|---|
| H1 | **Long-run variance weight (fixed fallback)** | γ (gamma) | 5% | Weight | Fallback tier only — see above |
| H2 | **Prior squared return weight (fixed fallback)** | α (alpha) | 5% | Weight | Fallback tier only — see above |
| H3 | **Prior variance weight (fixed fallback)** | β (beta) | 90% | Weight | Fallback tier only — see above |
| H4 | **Weight constraint** | γ+α+β | 100% | Constraint | Model validity (both fixed and fitted) |
| H5 | **Long-run variance VL** | VL | Mean-centered sample variance of log returns: `mean((r-r̄)²)` | Computed | Forecast |
| H6 | **Prior squared return** | u²ₙ₋₁ | From return series | Computed | Forecast |
| H7 | **Prior variance** | σ²ₙ₋₁ | From series | Computed | Forecast |
| H8 | **Daily variance forecast** | σ²ₙ | γ·VL + α·u² + β·σ²ₙ₋₁ | Computed | Signal |
| H9 | **Daily volatility** | σ_daily | √σ²ₙ | Computed | Signal |
| H10 | **Annualized forecast vol** | σ_annual | σ_daily × √252 | Percent | **Compare to option IV** |
| H11 | **Post-shock block flag** | `garch_distorted` | Boolean | Risk | Block cheap-vol after black swan or a failed fit |

**Entry condition (cheap vol):** `IV < σ_annual (GARCH forecast)` — annualized option IV must be **below** forecast.

**Observability:** `GarchForecastResult.fitted` (and `.gamma_used`/`.alpha_used`/`.beta_used`)
report whether a given forecast used fitted or fixed weights — check these
before treating "the model was fit" as true for a specific symbol/cycle.
```

- [ ] **Step 2: Close out §3.4 in `Improve_Recoemmendation_Engine.md`**

Find the current §3.4 block:

```markdown
### 3.4 GARCH(1,1) forecast uses fixed, unfitted weights — not MLE-estimated
`backend/quant/signals/garch.py` — `gamma=0.05, alpha=0.05, beta=0.9` are config
constants (sum-to-1 enforced), not parameters fit to each symbol's own return
series via maximum likelihood. This is a legitimate simplification for a
paper-trading system, but any language claiming "the model was fit" would be
inaccurate — it's a fixed-weight GARCH-shaped recursive filter. Also: `VL`
(long-run variance) is computed as `mean(r²)`, i.e., treats returns as zero-mean
rather than subtracting the sample mean first — a minor deviation from textbook
sample variance, immaterial for near-zero-drift daily equity returns but worth
knowing about if a strategy chases a name with real drift.
- **Fix (optional, P1\P2-adjacent):** either (a) explicitly document that weights
  are fixed-by-config, not fitted, everywhere the model is described in
  Docs/Trading_Parameters.md, or (b) add a periodic MLE re-fit job if per-symbol
  responsiveness matters more than stability.
```

Replace with:

```markdown
### 3.4 GARCH(1,1) forecast uses fixed, unfitted weights — not MLE-estimated — ✅ FIXED 2026-08-04
`backend/quant/signals/garch.py` — was `gamma=0.05, alpha=0.05, beta=0.9` config
constants applied to every symbol identically, not parameters fit to each
symbol's own return series via maximum likelihood. Also, `VL` (long-run
variance) was computed as `mean(r²)`, treating returns as zero-mean rather
than subtracting the sample mean first.
- **Resolution:** `fit_garch_11_mle()` fits `(γ,α,β)` per symbol via
  `scipy.optimize.minimize` (SLSQP) when there are ≥ `fit_min_observations`
  (default 60, config `garch_forecast.fit_min_observations`) log returns;
  between `min_observations` (20) and that floor, the fixed weights above
  remain the deliberate fallback (`fitted=False`, not distorted — same
  behavior as before this fix). A non-converged/degenerate fit at or above
  the floor now fails closed: `garch_distorted=True`,
  `reason="garch_fit_failed"`, rather than silently reusing fixed weights.
  `VL` now uses mean-centered sample variance, applied on both the fit and
  fallback paths. `GarchForecastResult.fitted`/`.gamma_used`/`.alpha_used`/
  `.beta_used` make it observable, per forecast, whether the weights were
  actually fit. See `Docs/superpowers/specs/2026-08-04-garch-mle-fit-design.md`
  and `backend/tests/quant/test_garch.py`.
```

Also find the low-priority backlog list entry:

```markdown
        F34["§3.4 GARCH weights fixed,<br/>not MLE-fit (by design)"]
```

Replace with:

```markdown
        F34["§3.4 GARCH weights fixed,<br/>not MLE-fit — ✅ FIXED 2026-08-04"]
```

- [ ] **Step 3: Commit**

```bash
git add "Docs/Trading_Parameters.md" "Improve_Recoemmendation_Engine.md"
git commit -m "Docs: reflect MLE-fit GARCH weights, close out §3.4

Part H now documents the three-tier fit/fallback/distorted behavior and the
mean-centered VL fix instead of implying fixed weights throughout.
Improve_Recoemmendation_Engine.md §3.4 and backlog item F34 marked resolved."
```

---

### Task 6: Full backend suite verification

**Files:** None modified — verification only.

- [ ] **Step 1: Run the full default test selection**

Run: `cd C:\Project_Volatality_Trading_by_Cursor && pytest -m "not integration" -v`
Expected: all tests pass, no regressions outside `test_garch.py`/`test_quant_snapshot.py`.

- [ ] **Step 2: Run the full suite including integration-marked tests**

Run: `cd C:\Project_Volatality_Trading_by_Cursor && pytest -v`
Expected: passes, or fails only on tests already known to require live broker/network access unrelated to this change (note which, if any, in your final report).

- [ ] **Step 3: Spot-check on non-synthetic data (per the spec's Open Risk)**

Run a short interactive check that the fit doesn't misbehave on a real-shaped daily-close series (adapt path/symbol as available in the repo's fixtures, e.g. via `backend/tests/quant/test_garch.py`'s existing `test_forecast_from_price_history_usable` price generator extended to ≥60 points, or any real historical closes already present in test fixtures):

```python
import math
from backend.quant.signals.garch import forecast_garch_11, log_returns_from_prices

prices = [100 * (1 + 0.01 * math.sin(i / 4) + 0.0003 * i) for i in range(90)]
returns = log_returns_from_prices(prices)
result = forecast_garch_11(returns, min_observations=20, fit_weights=True, fit_min_observations=60)
print(result.fitted, result.usable, result.sigma_annual, result.gamma_used, result.alpha_used, result.beta_used)
```

Expected: `fitted=True`, `usable=True`, `sigma_annual` in a sane range (roughly `0.01`–`2.0`, matching the tolerance already used in `test_forecast_from_price_history_usable`). If it instead reliably returns `garch_fit_failed`, flag this in your final report before considering the task done — it would mean the fail-closed path triggers too eagerly on realistic data and the bounds/constraints need revisiting.

No commit for this task — it's a verification gate before declaring the plan complete.
