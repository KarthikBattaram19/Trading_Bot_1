# Trading Strategies Reference

## Purpose
This document is the single consolidated trading playbook for this project. It synthesizes the source references below:

- `Docs/Volatility Trading.pdf`
- `Docs/Gamma Scalping.pdf`
- `Docs/Vega Scalping.pdf`
- `Docs/OSS (1).xlsm` — option strategy simulator workbook; capital and leg sizing defaults

Its goal is to turn the source material into an execution-ready reference for a retail-oriented, AI-assisted trading system. It keeps the original institutional logic, but adds practical controls for:

- retail capital limits
- option liquidity constraints
- transaction costs and slippage
- supervised execution
- model-risk handling
- scenario-based trade management

This document is a trading-methodology reference for the project, not a promise of profitability and not a substitute for broker, legal, tax, or compliance review.

## Project Execution Assumptions
This project is designed around a supervised-first operating model. The practical implication for this document is:

- discretionary entries should be reviewed and approved by the operator before broker submission
- mechanical hedges, stop logic, and risk-reduction actions can be automated once a position is live
- promotion from supervised to higher autonomy should happen only after validated paper trading, realistic cost modeling, and stable live-like behavior

### Paper rehearsal path (mandatory before live)
Validate this playbook on the in-house paper simulator (`Docs/Paper_Simulator.md`, `backend/paper_sim/`) before ICICI Direct live:

- **Strategy authority:** this document (Table SH-4, scenarios, shared kill conditions, capital prerequisites).
- **News / sentiment input:** curated India sources and workflow windows in `Market_News.txt` (Architecture §8.8).
- **Quant overlay:** GARCH(1,1) cheap-vol and intraday IV z-score remain primary signals; news **gates and overlays** selection and post-entry management.
- **Automation in paper:** continuous gamma–theta re-hedge and news-driven abort/flatten run against ICICI Direct LTP marks into the local paper ledger (no Breeze API `place_order`).

## How To Use This Document
Use this reference in five steps:

1. Identify the strategy family that matches the market condition.
2. Validate the shared prerequisites in `Common Execution Framework`, including `Capital Prerequisites`.
3. Follow the strategy-specific `Entry`, `Sizing`, `Management`, and `Exit` rules.
4. Check the scenario section for the situation you are actually in.
5. Do not execute if the setup fails any kill condition, even if the signal is attractive.

## Common Execution Framework

### Shared Principles
All three source strategies rely on the same institutional ideas:

- trade volatility instead of pure direction whenever possible
- remove unwanted risk before seeking desired risk
- prefer objective signals to discretionary opinions
- keep risk small enough that re-hedging and re-allocation remain possible
- use liquidity and execution quality as part of the edge, not as afterthoughts

### Core Concepts

#### Volatility Trading
Simple volatility trading uses delta hedging to isolate a long-volatility position. The trader seeks profits when:

- gamma gains offset theta decay
- vega gains add net profit because implied volatility rises

#### Gamma Scalping
Gamma scalping extends the volatility trade by minimizing or neutralizing vega. The portfolio aims to be:

- delta neutral
- vega neutral or near-neutral
- gamma positive
- theta negative

The trader then repeatedly monetizes price movement away from the last hedge point.

#### Vega Scalping
Vega scalping is an intraday long-volatility mean-reversion trade. It relies on intraday implied volatility behaving like a stationary series often enough that sharp downside dislocations in IV revert toward the intraday mean.

### Shared Risk Rule
Never treat hedging as the strategy itself. Delta hedging is a prerequisite for volatility strategies, not the full trading edge.

### Capital Prerequisites
The following capital limits apply to **all** strategies in this playbook. They are aligned with `Docs/OSS (1).xlsm` and govern both initial trade construction and subsequent trade operations (re-hedges, size increases or decreases, and leg adjustments).

| # | Parameter | Amount (INR) | Scope |
|---|---|---|---|
| 1 | **Total capital investment** | **10,00,000** | Portfolio / account ceiling |
| 2 | **Maximum investment to open a trade** | **1,00,000** | Total capital deployed when opening a new position |
| 3 | **Maximum investment per leg** | **1,00,000** | Each leg at entry; also the cap for any single leg in subsequent trade operations |

**Operating rules:**

- Do not submit a new trade if total deployment at entry would exceed **INR 1,00,000**.
- No single leg — option, stock hedge, or other — may exceed **INR 1,00,000** investment allocation.
- Re-hedges, rolls, and position adjustments must respect the per-leg cap; split across legs if the structure requires more notional than one leg allows.
- **INR 10,00,000** is the account capital base; portfolio diversification and hedge-reserve rules still apply even when individual trades stay within the per-trade cap.

Investment for sizing purposes means capital allocated to the leg or structure (premium paid or received, stock-hedge notional, and margin requirement as applicable), not mark-to-market P/L.

### Data Requirements
The system should not generate or approve trades unless the following data is available and current:

- underlying price history
- aligned business-day calendars
- option chain data with strikes, expiries, bid, ask, mid, volume, and open interest
- implied volatility
- Greeks or a reliable pricing engine
- earnings calendar
- corporate actions calendar
- borrow availability for short stock and short options where relevant
- margin estimate

### Execution Requirements
The source material strongly implies algorithmic execution for options strategies. In this project, the minimum execution standard should be:

- spread-aware order construction
- synchronized multi-leg submission
- slippage caps
- rejection handling
- partial-fill handling
- ability to recompute hedge ratios after fill drift

Manual legging is acceptable only for observation or paper rehearsal, not as the target production workflow.

### Retail Constraints To Respect
These strategies are institutionally inspired but must be filtered through retail reality:

- total account capital is **INR 10,00,000**; maximum **INR 1,00,000** to open a trade; maximum **INR 1,00,000** per leg (see `Capital Prerequisites`)
- **Tradeable universe — underlying price cap is mode-conditional:**
  - **Options and its underlying** (any `stock` leg / cash-share hedge): select only instruments whose underlying `und_price` is ≤ **INR 1000**. Prefer liquid cash-equity NFO chains; exclude index underlyings in this mode — they cannot be stock-hedged the same way and would fail the spot cap.
  - **Options only** (Call/Put legs only): **no cap** on the price of the underlying instrument. High-priced equities and index underlyings may be selected if they pass liquidity, ATM, and premium gates (`Trading_Parameters.md` Part T).
- only **high-liquidity** instruments may be traded (minimum volume, open interest, and spread gates)
- contract granularity makes perfect hedging difficult
- high-priced underlyings increase stock-hedge margin — which is why the ₹1000 spot cap is enforced **when** the bot trades the underlying alongside options
- low-liquidity options can erase edge through spread costs
- short locates and borrow fees may invalidate otherwise attractive setups
- frequent hedging can turn a mathematically attractive trade into a net loser after costs

### Shared Pre-Trade Checklist
No trade should be submitted unless all answers below are acceptable:

1. Is the signal objective and reproducible?
2. Is total entry deployment at or below **INR 1,00,000**, with no leg above **INR 1,00,000**?
3. If trading **options and underlying**: is the cash-equity spot at or below **INR 1000**? (Skip this check for **options-only**.)
4. Is the instrument **highly liquid** enough to enter and exit cleanly (volume, OI, spread)?
5. Is the trade small enough to rebalance within the per-leg capital cap?
6. Are event risks known and intentional?
7. Does the strategy match the current regime instead of fighting it?
8. Are margin, borrow, and cost assumptions still valid now?
9. Is there a clear exit, stop, and time-based decommission rule?

### Shared Kill Conditions
Abort or flatten if any of the following becomes true:

- liquidity collapses or spreads blow out beyond limits
- a hedge leg becomes unavailable
- the model input is stale or clearly corrupted
- an earnings or news event appears that the setup was not designed to absorb
- required neutrality cannot be restored within cost limits
- residual delta or vega exposure exceeds portfolio limits
- the strategy's core assumption no longer holds

## Strategy Selection Guide

| Strategy | Best Use Case | Primary Edge | Main Risk | Typical Horizon |
|---|---|---|---|---|
| Simple Volatility Trading | Options look cheap versus forecast volatility | Long gamma plus long vega | IV does not rise, theta bleed | Same day to next day |
| Gamma Scalping | Need long gamma but want less IV risk, especially around gaps or high realized movement | Positive gamma with muted vega | Quiet market, term-structure distortion, execution complexity | Intraday to next day |
| Vega Scalping | Intraday IV drops below its mean in a liquid ATM option | IV mean reversion | IV keeps falling or loses stationarity | Intraday only |

## Shared Mathematical Reference

### Stationarity Intuition
If a series has:

- roughly stable mean
- roughly stable standard deviation

then mean-reversion logic can be used more safely. If it has a unit root or drifting mean, mean-reversion assumptions are unreliable.

### Volatility Forecasting
The source volatility books use `GARCH(1,1)` as the main institutional forecast:

- `sigma_n^2 = gamma * VL + alpha * u_(n-1)^2 + beta * sigma_(n-1)^2`

with source-example weights often described as:

- `gamma = 5%`
- `alpha = 5%`
- `beta = 90%`

Annualization:

- `sigma_annual = sigma_daily * sqrt(252)`

### Common Option Exposures

- `Delta`: directional sensitivity
- `Gamma`: rate of change of delta with underlying movement
- `Theta`: time decay
- `Vega`: sensitivity to implied volatility

Long options generally imply:

- positive gamma
- positive vega
- negative theta

## Strategy 1: Simple Volatility Trading

### Objective
Trade volatility directly by creating a delta-neutral long-volatility position when implied volatility looks cheap relative to forecast volatility.

### Core Thesis
Once delta is hedged away, the trader is no longer primarily trading direction. The position becomes a volatility trade that benefits when:

- realized movement generates gamma gains
- implied volatility rises and produces vega gains

The source books describe the ideal outcome as:

- gamma pays for theta
- vega delivers net profit

### Minimum Conditions For A Valid Setup

1. The option chain is liquid.
2. The selected option is near-ATM.
3. Time to expiry is close enough to have meaningful gamma, but not so close that risk becomes chaotic.
4. Implied volatility is below the forecast from `GARCH(1,1)`.
5. The trader can create and maintain a delta hedge.

### Option Selection
Source-aligned selection rules:

- choose only high-liquidity options
- choose the most ATM strike
- prefer a close expiry, typically around `15` to `30` DTE
- avoid less than `10` DTE for routine use

Why this matters:

- ATM improves symmetry to both upside and downside movement
- near expiry increases gamma and theta while reducing vega
- too-close expiry makes Greeks more violent and execution less forgiving

### Entry Signal
Primary source rule:

- enter when option implied volatility is below annualized `GARCH(1,1)` forecast volatility

This is a "cheap volatility" signal.

### Position Construction
The source books allow two delta-hedging paths:

1. `long calls + short underlying`
2. `long calls + long puts` in the proportions required to neutralize delta

For options-only delta neutrality (same strike and expiration), define total option count `N`:

- number of **call** contracts = `N × put delta`
- number of **put** contracts = `N × call delta`

Project interpretation:

- use stock hedge if the stock is liquid and margin permits
- use options-only hedge when capital efficiency is needed and the desk accepts larger Greek leverage

### Greek Profile To Seek

- delta approximately zero
- gamma positive
- vega positive
- theta negative

### Trade Management
The key operational reference is the gamma-theta breakeven. The source material treats it as the price movement from the last hedge point needed for gamma gains to offset one day of theta decay. It is often described as being around `1%`, but the project should calculate it from current Greeks rather than hard-code it.

Management rule:

- re-hedge when price moves away from the last hedge point by the gamma-theta breakeven

The re-hedge can be done by:

- increasing the hedge
- reducing the option position
- changing the mix of calls and puts

### Exit Rules
Source-aligned default:

- hold `D+0` or `D+1`

Carry to next day only if:

- gamma has already paid for theta at least once
- the setup still supports a long-volatility view
- there is no event likely to crush IV against the position

### Stop Logic
Simple volatility trading does not use a single universal sigma stop like vega scalping. The trade should instead be stopped or avoided when:

- IV keeps falling after entry
- realized movement is too small to pay for theta
- delta cannot be maintained cheaply
- the original forecast advantage disappears

### Scenario Guide

#### Scenario A: Normal Cheap-Vol Setup
Condition:

- `IV < GARCH forecast`
- liquid ATM option
- no extreme event distortion

Action:

- valid simple volatility trade candidate

#### Scenario B: Black Swan While Already Long Vol
Condition:

- major shock occurs after entry
- price gaps hard
- IV spikes

Action:

- take profits aggressively or re-hedge immediately
- do not assume the outsized move will persist in a tradable way

This is the most favorable path for the strategy.

#### Scenario C: Quiet Market After Entry
Condition:

- price stays near hedge point
- IV does not rise

Action:

- theta becomes the dominant force
- exit early rather than hoping for late rescue

#### Scenario D: Earnings Release Ahead
Condition:

- company earnings are imminent

Action:

- do not treat this as a routine simple volatility trade
- simple long-vol is vulnerable to post-event IV crush
- prefer gamma scalping if the goal is to capture gap risk with reduced vega exposure

#### Scenario E: High-Priced Underlying In Small Account
Condition:

- underlying price makes stock hedging capital-intensive (`und_price` > **INR 1000**)

Action:

- do **not** trade options **and** the underlying on that name (T11 rejects)
- prefer **options-only** delta hedge / construction if execution quality remains acceptable — **no underlying price cap** in that mode
- otherwise reject the trade

### Failure Modes

- IV does not rise despite the forecast
- GARCH is distorted after crisis periods
- theta bleed outpaces gamma
- liquidity is poor
- stock hedge consumes too much capital
- small contract count leaves large residual delta
- execution is too slow to preserve neutrality

### Best Practices For This Project

- compute expected edge net of spread, slippage, commissions, and financing
- calculate whether one gamma-theta payment is realistically achievable
- downgrade or block signals in post-shock regimes
- do not hold for multiple days unless the trade repeatedly proves itself

## Strategy 2: Gamma Scalping

### Objective
Capture price movement through positive gamma while reducing or neutralizing exposure to changes in implied volatility.

### Core Thesis
Simple volatility trading depends heavily on vega. Gamma scalping removes much of that dependency by combining short-dated and longer-dated options so that the portfolio remains:

- delta neutral
- vega neutral
- gamma positive
- theta negative

The trader then "scalps" the gamma effect as price moves away from the last hedge point.

### Why Gamma Scalping Exists
This strategy is especially useful when:

- you want long convexity
- realized movement is likely
- implied volatility direction is uncertain
- an earnings gap is possible
- volatility is already high, making plain long-vega trades less attractive

### Instrument Design
Source-aligned construction:

- buy short-dated calls
- short longer-dated calls in a quantity that neutralizes vega
- short stock to neutralize residual delta

Reason:

- shorter-dated options have more gamma and theta, less vega
- longer-dated options have more vega, less gamma and theta

By selling fewer or differently sized longer-dated options against the near-dated long options, the portfolio can neutralize vega while keeping net gamma positive.

### Options-Only Variant
The source material also describes a four-leg options-only version:

- short-dated long calls
- longer-dated short calls
- short-dated long puts
- longer-dated short puts

Use case:

- lower stock-margin dependence
- higher structural complexity
- much stronger need for synchronized execution

### Minimum Conditions For A Valid Setup

1. Both expiries are liquid.
2. Term structure is not obviously distorted against the trade.
3. Vega can be neutralized while keeping net gamma meaningfully positive.
4. Residual delta can be hedged within cost limits.
5. The expected realized movement is large enough to overcome theta.

### Valid Entry Modes
The source books support three main reasons to open gamma scalping:

1. `IV < GARCH forecast` and volatility appears cheap.
2. An earnings release is imminent and the goal is to capture the gap while muting IV-crush risk.
3. Volatility is already high and price is actively fluctuating, so realized movement may pay for theta even if IV later falls.

### Entry Rules

#### Standard Entry
- choose same-strike short-dated and longer-dated options
- buy the shorter-dated call(s)
- short the longer-dated call(s) until vega is neutralized
- short stock to neutralize resulting delta

#### Earnings Entry
- open the trade one day before earnings
- the goal is the overnight gap, not a long holding period

#### Intraday Gamma Entry
- valid when price is already active and hedging costs are manageable
- intraday theta is less important than overnight theta

### Greek Management
Greek neutrality is local, not permanent.

As price and time move:

- delta drifts
- vega neutrality drifts
- gamma and theta change

Therefore:

- re-hedge delta and vega whenever the move from the last hedge point reaches the gamma-theta breakeven

### Exit Rules
Exit depends on why the trade was opened:

#### Cheap-Vol Or Standard Gamma Setup
- hold `D+0` or `D+1`
- extend only if theta has been paid for and the structure remains favorable

#### Earnings Gap Setup
- close after the gap if the move delivered the intended gamma gain
- optionally extend for one more session only if realized movement remains high and the Greeks can be restored cheaply

#### Intraday Gamma Setup
- close same day unless the trade was intentionally structured for overnight exposure

### Scenario Guide

#### Scenario A: Earnings Gap Down Or Up
Condition:

- stock gaps sharply after earnings
- IV may rise or collapse

Action:

- gamma is the target exposure
- re-check delta and vega immediately after the gap
- close or re-neutralize based on whether the move exceeded the gamma-theta threshold

This is the flagship gamma-scalping scenario.

#### Scenario B: High Volatility, Big Intraday Swings
Condition:

- realized movement is large
- term-structure hedge remains stable

Action:

- re-hedge repeatedly at rule-based intervals
- lock in gamma gains as price oscillates

#### Scenario C: Quiet Market
Condition:

- price stays near hedge point

Action:

- theta slowly dominates
- close rather than forcing the trade

#### Scenario D: IV Term-Structure Distortion
Condition:

- short-dated IV is abnormally rich while longer-dated IV is abnormally cheap

Action:

- reject or reduce the trade
- the book explicitly warns that term-structure correction can create losses even if vega is neutral at entry

#### Scenario E: Post-Gap Greek Drift
Condition:

- large move happens
- delta and vega neutrality disappear

Action:

- do not assume the original hedge still exists
- either re-solve the structure or flatten

### Failure Modes

- not enough movement to beat theta
- poor liquidity in longer-dated legs
- imperfect vega hedge from coarse contract sizing
- post-shock GARCH distortion
- partial fills across three or four legs
- term-structure misalignment
- overconfidence in the "vega neutral" label after a large move

### Best Practices For This Project

- solve quantities numerically instead of using rough intuition
- store hedge point and rebalance threshold explicitly
- support separate entry modes: `cheap_vol_mode`, `earnings_gap_mode`, `high_realized_vol_mode`
- require stronger execution checks than for simple volatility trades

## Strategy 3: Vega Scalping

### Objective
Capture intraday mean reversion in implied volatility through a delta-neutral long-volatility structure.

### Core Thesis
The source book argues that although implied volatility may trend over multi-day horizons, it is often stationary enough intraday to revert toward its mean. Vega scalping exploits this by entering only after a downside dislocation in intraday IV and exiting on mean reversion.

### Defining Characteristics

- intraday only
- long volatility only
- delta neutral at entry
- gamma positive as a beneficial secondary exposure
- theta largely ignored because the trade should not be held overnight

### Minimum Conditions For A Valid Setup

1. The selected ATM option is highly liquid.
2. Intraday IV has a meaningful and stable enough mean.
3. Intraday standard deviation is not exploding in a way that invalidates the signal.
4. A delta-neutral hedge can be created immediately.
5. The trade can be flattened before the end of the session.

### Option Selection
Source-aligned rules:

- choose an ATM option
- find the best compromise between longer expiry and strong liquidity
- avoid ultra-near expiry when Greek instability becomes too high

### Entry Rules
Primary source rule:

- enter only when intraday implied volatility is `2` standard deviations below its intraday mean

Do not invert the rule.

The source material is explicit:

- never treat `2-sigma above mean` as a short-volatility entry

### Position Construction
Two possible structures:

1. long option(s) plus stock hedge
2. calls and puts combined to neutralize delta

Project preference:

- choose the construction with the better combined score for liquidity, slippage, and margin

### Exit Rules
Primary exit:

- close when IV returns to its intraday mean

Stop:

- stop at `3` or `4` standard deviations below mean, depending on configured risk tolerance

Time exit:

- flatten same day, always

### Why The Strategy Can Work
The source rationale is:

- a stationary series oscillates around a fixed mean
- if IV drops far enough below the mean, it tends to revert
- because the trade is long volatility, unexpected market agitation after entry helps rather than hurts

### Scenario Guide

#### Scenario A: Clean Intraday IV Flush
Condition:

- liquid ATM option
- IV prints at least `2-sigma` below mean
- spreads remain tight

Action:

- valid vega-scalp entry
- exit at mean reversion

#### Scenario B: News Shock After Entry
Condition:

- sudden macro or company-specific news breaks
- IV spikes

Action:

- favorable outcome
- take gains rather than waiting for a perfect textbook exit

#### Scenario C: Quiet Tape
Condition:

- market remains still
- IV continues to drift lower

Action:

- stop out at configured sigma threshold
- do not widen the stop merely because the trade was "supposed" to revert

#### Scenario D: Intraday Stationarity Breakdown
Condition:

- intraday IV mean is present but standard deviation becomes unstable

Action:

- downgrade or block new entries
- active positions should respect hard stop and same-day flattening

#### Scenario E: Illiquid Chain
Condition:

- wide spreads or thin order book

Action:

- reject the setup even if the IV signal is strong

### Failure Modes

- IV continues to fall
- variable intraday variance creates moving-goalpost behavior
- stale IV measurements
- execution latency destroys the entry edge
- residual delta remains because of coarse contract sizing
- the chain is liquid enough to enter but not liquid enough to exit cheaply

### Best Practices For This Project

- build contract-specific intraday IV history
- compute rolling mean and rolling standard deviation with outlier handling
- require same-day flattening
- log realized vega P/L separately from gamma P/L

## Cross-Strategy Scenario Map

### When Volatility Looks Cheap Versus Forecast
Preferred order:

1. simple volatility trade
2. gamma scalping if IV direction is uncertain or event risk is present

### When A Large Earnings Gap Is Likely
Preferred order:

1. gamma scalping
2. avoid simple volatility trade through the event unless explicitly justified

### When Intraday IV Flushes Hard In A Liquid ATM Option
Preferred order:

1. vega scalping

### When Realized Movement Is High But IV Is Already Elevated
Preferred order:

1. gamma scalping

Reason:

- it reduces the problem of paying rich vega while still keeping long gamma

### When The Market Is Post-Shock And Models Are Distorted
Preferred order:

- reduce or block all model-driven volatility trades until normalization

## Portfolio-Level Rules

### Diversification
Do not let one strategy dominate all risk by accident. The system should monitor:

- gross exposure
- net exposure
- sector concentration
- earnings concentration
- aggregate delta
- aggregate gamma
- aggregate vega
- aggregate theta

### Capital Allocation Policy
Hard limits (see `Capital Prerequisites`):

| Parameter | Amount (INR) |
|---|---|
| Total capital investment | **10,00,000** |
| Maximum investment to open a trade | **1,00,000** |
| Maximum investment per leg | **1,00,000** |

Within those limits, apply this hierarchy:

1. reserve capital for hedging and forced exits first
2. cap any single new trade at **INR 1,00,000** total deployment and **INR 1,00,000** per leg
3. reduce size when liquidity is thin or hedging precision is poor
4. reduce size after major shocks until models re-stabilize
5. on re-hedge or leg adjustment, re-check that no leg exceeds the per-leg cap

### Cost Awareness
Every signal should be scored after:

- commissions
- bid/ask spread
- slippage
- borrow costs
- financing
- expected re-hedge count

The project should reject any trade whose theoretical edge disappears after realistic costs.

## Supervised Execution Runbook

### Pre-Approval Packet
Before operator approval, the system should present:

- strategy type
- instrument(s)
- market condition summary
- entry rationale
- hedge construction
- size and margin estimate (within **INR 1,00,000** per trade and per leg)
- stop, target, and time exit
- known event risks
- reasons the trade could fail

### Post-Entry Automation
Once approved and filled, the system may automate:

- delta-maintenance hedges
- risk-reduction exits
- stop logic
- same-day flattening for vega scalping
- alerts for lost neutrality or abnormal costs

### Human Escalation Triggers
Require operator review if:

- a leg fails to fill
- the hedge cannot be restored
- slippage exceeds configured maximum
- a major event occurs mid-trade
- the system recommends holding beyond the default horizon

## Implementation Notes For The Project

### Strategy Modules To Support
The analytics and execution stack should maintain dedicated logic for:

- volatility forecasting
- option selection
- Greeks aggregation
- hedge solving
- scenario tagging
- execution orchestration
- post-trade attribution

### Key Metrics To Persist
At minimum, persist:

- signal timestamp
- instrument identifiers
- IV, forecast volatility, and IV z-score
- delta, gamma, vega, theta at entry and after each rebalance
- realized and unrealized P/L
- slippage and spread capture
- reason for exit

### Conservative Interpretation Of Source Claims
The source PDFs are valuable and operationally rich, but the project should interpret some claims conservatively:

- "volatility is cheap" is a probabilistic statement, not a guarantee
- "vega neutral" is local and can disappear quickly after a large move
- an elegant Greek structure can still fail because of liquidity, event risk, or execution quality

## Final Operating Rules

1. Trade only when the setup matches the strategy's intended regime.
2. Do not force a strategy into the wrong market condition.
3. Respect liquidity, margin, and event-risk filters before respecting model beauty.
4. For volatility strategies, hedge quality is part of the trade thesis.
5. Do not widen stops to rescue a broken thesis.
6. Flatten when the core assumption fails.
7. Review every completed trade to refine scenario filters, cost assumptions, and execution rules.

## Complete Source Tables And Interpretations

This section preserves every execution-critical table and rule list from the three source PDFs, with plain-language interpretation for the trading bot. Tables that appear as charts or screenshots in the originals are reconstructed here as structured reference data.

### Table Index By Source Document

| Source Document | Table / Rule Set | Primary Use For The Bot |
|---|---|---|
| Volatility Trading | Option selection rules, rules 1–10, GARCH example, Company Z walkthrough | Cheap-vol entry, delta hedge, gamma-theta management |
| Gamma Scalping | Greeks-vs-time, three entry modes, Intel earnings example, rules 1–10 | Vega-neutral construction, earnings gap, intraday scalp |
| Vega Scalping | Seven intraday rules, IV mean-reversion example | Intraday IV z-score entry and same-day exit |

---

### Volatility Trading — Source Tables

#### Table VT-1: Option Selection Rules

| # | Rule | Bot Interpretation |
|---|---|---|
| 1 | Trade only high-liquidity options | Block illiquid chains; enforce min volume (1000), min OI (10000), spread cap (2%) |
| 1a | Underlying price ≤ INR 1000 when options+underlying | Reject if spot > ₹1000 **only** when trading options with the underlying; **no spot cap** for options-only |
| 2 | Choose ATM strike | Maximizes gamma symmetry and Greek magnitude |
| 3 | Choose near expiry (~15–30 DTE) | More gamma/theta, less vega |
| 4 | Avoid <10 DTE routinely | Black-Scholes distortions; extreme Greek risk |

#### Table VT-2: Core Volatility Trading Rules (Source Numbering)

| # | Rule | Bot Interpretation |
|---|---|---|
| 3 | Enter when option **implied volatility (IV) is below** the GARCH(1,1) forecast | Primary cheap-vol signal; IV must be lower than GARCH |
| 4 | Delta hedging is prerequisite, not the strategy | Must neutralize delta before managing gamma/vega/theta |
| 5 | Always long options (positive gamma); never short vol for this strategy | Long calls or long call+put structures only |
| 6 | Delta hedge via (a) long calls + short stock, or (b) long calls + long puts same strike/expiry | Choose path by margin and liquidity score |
| 7 | Stock hedge: buy X calls ≈ long `X × call delta` shares; hedge by shorting that many shares | Default institutional path when stock is liquid |
| 8 | Options-only hedge: total contracts N; **calls = N × put delta**; **puts = N × call delta** | Lower margin; stronger Greek leverage |
| 9 | Re-hedge when price moves away from last hedge point by gamma-theta breakeven (~1%) | Automated rebalance trigger |
| 10 | Re-hedge by increasing or decreasing position | Track realized P/L and floating P/L separately |

#### Table VT-3: GARCH(1,1) Parameter Reference

| Parameter | Typical Weight | Role |
|---|---|---|
| γ (gamma) | 5% | Weight on long-run variance VL |
| α (alpha) | 5% | Weight on prior squared return |
| β (beta) | 90% | Weight on prior variance estimate |
| Constraint | γ + α + β = 100% | Must hold in implementation |

**Formula:** `σ_n² = γ·VL + α·u_(n-1)² + β·σ_(n-1)²`

#### Table VT-4: GARCH Worked Example (Source Numbers)

| Step | Calculation | Result |
|---|---|---|
| Long-run variance VL | Sample variance of log returns | 0.030753% |
| Prior squared return u_(n-1)² | From series | 0.036051% |
| Prior variance σ_(n-1)² | From series | 0.036595% |
| Today's variance σ_n² | 5%·VL + 5%·u² + 90%·σ_(n-1)² | 0.0362757% |
| Daily volatility σ_n | √(variance) | 1.9046% |
| Annualized volatility | 1.9046% × √252 | **30.23%** |

**Interpretation:** Compare annualized GARCH forecast to annualized option IV. IV below forecast = cheap vol entry candidate. After black swan events, GARCH may be distorted — block or downgrade signals until normalization.

#### Table VT-5: Gamma-Theta Breakeven Management

| Concept | Typical Value | Bot Interpretation |
|---|---|---|
| Gamma-theta breakeven | ~0.96%–1% move from last hedge point | Distance required for one day's gamma to offset one day's theta |
| Half breakeven tactic | Re-hedge at half distance twice | Alternative when full breakeven is hard to reach |
| Carry permission | Paid breakeven ≥ once | May carry D+0 → D+1 |
| Default horizon | D+0 or D+1 | Do not carry multi-day without repeated theta payment |

#### Table VT-6: Company Z Walkthrough — Small Account Delta Hedge

| Step | Action | Result |
|---|---|---|
| Setup | Stock ~$20; 10 ATM call contracts; 20 total option slots | Initial portfolio delta −92.56 (not neutral) |
| Hedge attempt A | Adjust puts to 8 contracts | Best delta +16.47 (too long) |
| Hedge attempt B | Adjust calls (preferred in example) | Delta −2.04; margin ~$1,190 |
| Price move | +1% to $20.20 (breakeven distance) | Floating P/L +$12.39 (~1% on margin); delta +125.82 |
| Re-hedge | Sell 2 call contracts (reduce size) | Realized +$19.26; floating −$6.88; total unchanged |
| Overnight | −2% gap; IV 20% → 22% | Floating +$120.40 |
| Total trade | Realized + floating | **$139.66 profit on ~$1,200 margin (~11.6%)** |

**Interpretation:** Small contract counts prevent perfect delta neutrality. Bot must log residual delta, compare call vs put adjustment paths, and track realized vs floating P/L on every rebalance.

#### Table VT-7: Greek Profile Target — Simple Volatility Trade

| Greek | Target Sign | Source Rationale |
|---|---|---|
| Delta | ≈ 0 | Remove directional exposure |
| Gamma | Positive | Gain from movement away from hedge point |
| Vega | Positive | Profit when IV rises toward GARCH forecast |
| Theta | Negative | Cost of carry; must be paid via gamma scalps |

#### Table VT-8: Volatility Trade Exit Logic

| Condition | Action |
|---|---|
| Gamma-theta breakeven paid ≥ once and thesis intact | May hold to D+1 |
| IV rises (vega gains) + gap/move | Strong close candidate |
| IV falls and price quiet | Exit early; vega losses dominate |
| IV cheap vs GARCH at entry | Expect IV rise; if IV falls 3+ points anyway | Treat as failed thesis |

---

### Gamma Scalping — Source Tables

#### Table GS-1: Greeks Versus Time To Expiration

| Greek | Relationship To Expiry | Near-Dated Option | Far-Dated Option |
|---|---|---|---|
| Gamma | Inversely proportional | Higher | Lower |
| Theta | Inversely proportional | Higher (more decay) | Lower |
| Vega | Directly proportional | Lower | Higher |

**Interpretation:** Buy short-dated calls for gamma/theta; sell fewer long-dated calls to neutralize vega; short stock to neutralize delta. Result: delta neutral, vega neutral, gamma positive, theta negative.

#### Table GS-2: Target Portfolio Profile

| Greek | Target | After Large Move |
|---|---|---|
| Delta | 0 | Drifts; must re-hedge |
| Vega | 0 | Drifts; must re-hedge |
| Gamma | Positive | Still positive but changes magnitude |
| Theta | Negative | Overnight theta matters for D+1 holds |

#### Table GS-3: When To Perform Gamma Scalping (Three Source Modes)

| Mode | Entry Condition | Primary Goal | Default Horizon |
|---|---|---|---|
| 1 — Cheap vol | IV < GARCH(1,1) | Gamma pays theta; optional vega lift | D+0 / D+1 |
| 2 — Earnings gap | Open 1 day before earnings | Capture gap gamma; mute IV crush via vega hedge | Close after gap or next session |
| 3 — High realized vol | IV already elevated; price active | Scalp gamma without betting on IV rise | Intraday or D+1 |

#### Table GS-4: Gamma Scalping Construction Steps

| Step | Action | Bot Note |
|---|---|---|
| 1 | Select same-strike short-dated and long-dated calls | Prefer calls over puts (positive delta → short stock uses less margin) |
| 2 | Buy short-dated calls | Provides gamma and theta |
| 3 | Short long-dated calls until portfolio vega ≈ 0 | Creates small negative gamma; net gamma stays positive |
| 4 | Short underlying to neutralize delta | Stock hedge path |
| Alt | Four-leg options-only | Short-dated long calls + long-dated short calls + short-dated long puts + long-dated short puts; requires synchronized algo |

#### Table GS-5: Intel Earnings Gap Example (Source)

| Field | Value | Interpretation |
|---|---|---|
| Pre-earnings price | $60.50 | |
| Post-gap price | $52.14 | −13.8% gap |
| IV change (simulation) | 35% → 45% | Vega-neutral design limits IV path dependency |
| P/L with stock delta hedge | $6,635 | Gamma-driven |
| P/L options-only structure | $13,272 (after theta) | Higher complexity, higher outcome in example |
| Post-gap Greeks | No longer delta/vega neutral | Mandatory re-solve or flatten |

#### Table GS-6: Gamma Scalping Management Rules

| Situation | Re-hedge Rule |
|---|---|
| Intraday gamma scalp | Re-neutralize delta and vega at each gamma-theta breakeven move |
| Overnight / earnings gap | Re-neutralize after gap if move ≥ gamma-theta breakeven |
| Intraday only | Theta less relevant same session; focus on gamma extraction |
| Term-structure distortion | Block entry if short-dated IV > long-dated IV (local max/min mismatch) |

#### Table GS-7: Gamma Scalping Exit Rules

| Opening Mode | Exit Rule |
|---|---|
| Cheap vol / standard | D+0 or D+1; extend only if breakeven paid and structure restorable |
| Earnings | Close after gap profit or extend one session if movement stays high |
| High realized vol intraday | Flatten same day unless intentionally structured overnight |

#### Table GS-8: IV Term-Structure Risk (Hidden Loss Source)

| Term Structure State | Risk | Bot Action |
|---|---|---|
| Short-expiry IV < long-expiry IV | Favorable | Preferred entry geometry |
| Short-expiry IV locally high; long-expiry locally low | Mean-reversion of IV spread can hurt | Reject or reduce size |
| Post-entry 20% IV drop (vega-neutral book) | Minimal P/L impact | Validates vega hedge purpose |

---

### Vega Scalping — Source Tables

#### Table VS-1: Stationarity Comparison For IV

| Series Type | Mean | Std Dev | Predictable By Mean Reversion? | Bot Use |
|---|---|---|---|---|
| Multi-day IV | Often trends | Variable | Poor intraday | Use GARCH cheap-vol frame (Vol Trading) |
| Intraday IV | Approximately fixed | Mostly stable | Yes, when stable | Vega scalping universe |
| Intraday IV with variable variance | Fixed mean | Variable σ | Degraded | Downgrade signals; tighten stops |

**Interpretation:** Vega scalping applies mean-reversion logic to intraday IV, not to price direction.

#### Table VS-2: Seven Vega Scalping Rules (Source)

| # | Rule | Bot Interpretation |
|---|---|---|
| 1 | Choose ATM option | Maximizes vega/gamma tradeoff |
| 2 | Balance longer expiry vs liquidity | Prefer liquid chain over maximum vega |
| 3 | Monitor intraday IV series | Build contract-specific IV history |
| 4 | Enter when intraday IV is 2σ below intraday mean | Long vol only; delta hedge immediately |
| 5 | Never short vol when IV is 2σ above mean | Negative gamma; explicitly forbidden |
| 6 | Exit when IV returns to intraday mean | Primary take-profit |
| 7 | Stop at 3σ or 4σ below mean | Configurable by risk tolerance |

#### Table VS-3: Vega Scalping Greek Focus (Intraday)

| Greek | Relevance Intraday | Notes |
|---|---|---|
| Delta | Neutralize at entry | Prerequisite, not the edge |
| Gamma | Secondary benefit | Helps if price moves after entry |
| Vega | Primary edge | Mean reversion of IV |
| Theta | Largely ignored | D+0 only; flatten same session |

#### Table VS-4: Vega Scalping Worked Example (Source)

| Field | Value | Interpretation |
|---|---|---|
| Entry trigger | IV crosses −2σ below intraday mean | Long vol via delta-neutral calls+puts |
| IV distance to mean | ~2 percentage points | Proxy for expected vega capture |
| Position margin | $16,533 | Size reference |
| Profit at mean reversion | $1,652 | ~10% return; excludes possible gamma add-on |
| Leverage note | Options-only vs stock hedge | Stock hedge lowers leverage and risk |

#### Table VS-5: Vega Scalping Failure And Antifragile Scenarios

| Scenario | P/L Effect | Bot Action |
|---|---|---|
| IV reverts to mean | Profit | Standard exit |
| Breaking news spikes IV | Profit (long vega) | Take profit; do not wait for perfect mean touch |
| Quiet tape; IV drifts lower | Loss | Stop at 3σ–4σ; same-day flatten |
| IV variance unstable | Signal degradation | Block new entries |

---

### Shared Volatility Implementation Tables (All Options Strategies)

#### Table SH-0: Capital Prerequisites (OSS + Project)

| # | Parameter | Amount (INR) | Bot Interpretation |
|---|---|---|---|
| 1 | Total capital investment | **10,00,000** | Account / portfolio ceiling; `total_capital` |
| 2 | Max investment to open a trade | **1,00,000** | Reject entry if summed leg allocation > cap; `max_trade_investment` |
| 3 | Max investment per leg | **1,00,000** | Reject or split legs at entry and on re-hedge/adjust; `max_leg_investment` |

**Source:** `Docs/OSS (1).xlsm`, `Capital Prerequisites` in this document.

#### Table SH-1: Numbered Practical Aspects (Gamma / Vol Books)

| # | Topic | Bot Requirement |
|---|---|---|
| 1 | Stock price and IV affect margin | Pre-trade margin model uses spot and IV |
| 2 | Small contract counts | Expect imperfect delta/vega neutrality; enforce minimum size or reject |
| 3 | Algorithmic execution | Multi-leg synchronized submit; no manual legging in production |
| 4 | GARCH after black swans | Block cheap-vol signals until model normalizes |
| 5 | Gamma/theta vs vega vs time | Use Table GS-1 for expiry selection |
| 6 | Avoid <10 DTE | Hard filter except research mode |
| 7 | Liquidity | Spread and OI filters; critical for long-dated gamma legs |
| 8 | Re-hedge by increasing or decreasing | Preserve realized + floating P/L ledger |
| 9 | Greek equilibrium is local | Recompute Greeks after every material move |
| 10 | Goal Seek / numerical hedge solve | Solve contract counts numerically; do not guess ratios |

#### Table SH-2: Delta Hedge Construction Comparison

| Method | Legs | Margin | Liquidity | Neutralization Quality |
|---|---|---|---|---|
| Long calls + short stock | 2 | Higher if stock expensive | Stock + option | Usually best for whole shares |
| Long calls + long puts | 2+ | Lower | Option-only | Sensitive to contract granularity |
| Gamma: calls spread + stock | 3+ | Medium–high | Needs long-dated liquidity | Must solve vega and delta jointly |
| Gamma: four-option box | 4 | Lower stock margin | Hardest execution | Requires algo |

#### Table SH-3: Horizon And Carry Matrix

| Strategy | Allowed Hold | Carry Condition | Must Flatten By |
|---|---|---|---|
| Simple volatility | D+0 or D+1 | Gamma-theta breakeven paid | End D+1 unless re-approved |
| Gamma scalping | D+0, D+1, or post-earnings | Mode-dependent | Earnings mode: after gap unless extended |
| Vega scalping | Intraday only | N/A | Session close always |

#### Table SH-4: Cross-Strategy Decision Matrix (Source Logic)

| Market Condition | First Choice | Second Choice | Avoid |
|---|---|---|---|
| IV < GARCH; normal regime | Simple vol | Gamma scalping if IV path uncertain | Short vol |
| Earnings gap expected | Gamma scalping | — | Plain long vega through event |
| IV high; large realized moves | Gamma scalping | — | Simple long vega |
| Intraday IV −2σ vs intraday mean | Vega scalping | — | Short vol at +2σ |
| Post-shock; GARCH distorted | Reduce all vol strategies | — | Blind GARCH entries |

**News overlay for SH-4:** Classify headlines/filings from the `Market_News.txt` pipeline (tone, topics, symbol tags, macro risk). Cross with quant regime (IV, GARCH, IV z, RV, earnings calendar) before selecting `First Choice`. Paper-sim and the live recommendation engine both apply this matrix — see Architecture §8.8.4 and `Docs/Paper_Simulator.md`.

| News / event flag (from Market_News) | Effect on SH-4 row |
|---|---|
| No adverse event; normal tone | Allow cheap-vol / normal-regime row |
| Earnings or company event imminent | Force earnings-gap row; block plain long-vega through event |
| Crisis / post-shock tone | Force post-shock row; set `garch_distorted` / block model trades |
| Breaking news after long-vol entry | Prefer take-profit / aggressive re-hedge (do not widen stops) |
| Unplanned news the setup was not designed for | Shared Kill → abort or flatten |

---

### Bot Ingestion Notes For This Section

When indexing this document for RAG or strategy engines:

- Tag each table with `strategy`, `topic`, and `source_doc` metadata (for example: `doc-gamma`, `gamma-theta-breakeven`).
- Prefer retrieving entire table + interpretation chunk together; rows split across chunks lose execution context.
- Numeric examples (Company Z, Intel, Vega example) are calibration references, not guaranteed future performance.
- Rule 5 in Vega Scalping (never short vol at +2σ) is a hard constraint, not a suggestion.

## Document Status
This file is intended to be the canonical high-level trade-execution reference for the project. The section **Complete Source Tables And Interpretations** consolidates all execution-critical tables and numbered rules from the three source PDFs. It should be updated whenever:

- a strategy rule changes
- new scenario handling is added
- broker or margin constraints change
- execution infrastructure improves
- backtest evidence invalidates a source-derived heuristic
- paper-sim or `Market_News.txt` wiring changes how SH-4 / kills are applied in rehearsal

**Related docs:** `Docs/Paper_Simulator.md` (paper path), `Market_News.txt` (news curation), `Docs/Trading_Parameters.md` (Part U news keys), Architecture §8.8.
