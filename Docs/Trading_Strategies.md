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
- No single option leg may exceed **INR 1,00,000** investment allocation; stock/underlying legs are rejected by the project hard lock.
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
- short-option margin / carry costs where relevant
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
- **Tradeable universe — options-only hard lock:** Call/Put option legs only. No stock/underlying trading, no cash-share hedge, and no T11 spot cap. Cash-equity and index underlyings may be selected when their options pass liquidity, ATM, premium, sizing, and risk gates (`Trading_Parameters.md` Part T).
- only **high-liquidity** instruments may be traded (minimum volume, open interest, and spread gates)
- contract granularity makes perfect hedging difficult
- high-priced underlyings are allowed when the selected Call/Put options pass the gates; `und_price` remains a pricing and ATM-selection input, not a tradeable leg
- low-liquidity options can erase edge through spread costs
- short locates and borrow fees may invalidate otherwise attractive setups
- frequent hedging can turn a mathematically attractive trade into a net loser after costs

### Shared Pre-Trade Checklist
No trade should be submitted unless all answers below are acceptable:

1. Is the signal objective and reproducible?
2. Is total entry deployment at or below **INR 1,00,000**, with no leg above **INR 1,00,000**?
3. Does the structure contain Call/Put legs only, with no stock/underlying leg or cash-share hedge path?
4. Is the instrument **highly liquid** enough to enter and exit cleanly (volume, OI, spread)?
5. Is the trade small enough to rebalance within the per-leg capital cap?
6. Are event risks known and intentional?
7. Does the strategy match the current regime instead of fighting it?
8. Are margin and cost assumptions still valid now?
9. Is there a clear exit, stop, and time-based decommission rule?

### Shared Kill Conditions
Abort or flatten if any of the following becomes true:

- liquidity collapses or spreads blow out beyond limits
- a hedge leg becomes unavailable
- the model input is stale or clearly corrupted
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

The source books justify the `2-sigma` trigger with the empirical rule: roughly `68%` of observations fall within `1σ` of the mean, `95%` within `2σ`, and `99.7%` within `3σ`. In the book's illustrative series of `300` points, `292` fell inside the `±2σ` band. A `2σ` excursion is therefore a genuinely uncommon reading — but only if the series really is stationary. The source explicitly warns that applying this logic to a non-stationary series (the classic Bollinger-Bands-on-price mistake) is "trying to score a goal with moving goalposts."

Intermediate case to respect: a series can keep a **fixed mean but a variable standard deviation**. That is less damaging than a drifting mean, but it still degrades the signal — the bands widen and narrow while the mean holds.

### Volatility Forecasting
The source volatility books build up through three estimators; only the last is the trading forecast:

1. **Moving Average (MA)** — plain average of squared log returns; every return carries equal weight. Source example: variance `0.031692%`, daily volatility `1.7802%`. Not used in practice — equal weighting is unrealistic.
2. **EWMA** — recursive, `sigma_n^2 = lambda * sigma_(n-1)^2 + (1 - lambda) * u_(n-1)^2`, source example `lambda = 90%` giving `sigma_n^2 = 0.036541%`. Recent returns get more weight, decaying exponentially.
3. **GARCH(1,1)** — EWMA plus a long-run variance term, which is what makes it mean-reverting. This is the institutional forecast:

- `sigma_n^2 = gamma * VL + alpha * u_(n-1)^2 + beta * sigma_(n-1)^2`

with source-example weights:

- `gamma = 5%`
- `alpha = 5%`
- `beta = 90%`
- constraint: they must sum to `100%`

`VL` (long-run variance) is computed as the **sample variance of the log returns in the series**. Log returns — not simple returns — are used because simple returns are asymmetric on the way up versus the way down (`+5%` up vs `-4.76%` down for the same `$5` move), while log returns are symmetric (`±4.879%`).

Annualization:

- `sigma_annual = sigma_daily * sqrt(252)`

`252` is business days per year. The source flags that some countries annualize on **calendar** days instead — the project must annualize IV and GARCH on the same basis before comparing them, or the cheap-vol signal is meaningless.

Model-risk caveat from the source: econometric models only work when the market is reasonably normal. After extreme events (2008, 2020), GARCH gets distorted and produces **false cheap-vol signals** — many options will show `IV < GARCH` for the wrong reason. The source's advice is to wait for the market to normalize.

### Common Option Exposures

- `Delta`: directional sensitivity
- `Gamma`: rate of change of delta with underlying movement
- `Theta`: time decay
- `Vega`: sensitivity to implied volatility

Long options generally imply:

- positive gamma
- positive vega
- negative theta

Two source intuitions the bot should encode explicitly:

- Delta is also the **approximate probability the option finishes ITM / is exercised**.
- The closer delta is to `50%` (i.e. the more ATM the option), the **more pronounced every other Greek** is. This is the real reason ATM strikes are mandated, not just payoff symmetry.

Contract-multiplier note: the source's worked examples assume `1 contract = 1 option` for arithmetic simplicity but state that a real contract normally carries `100` options. The bot must always convert Greeks and capital caps to the actual exchange lot size (NSE lot sizes vary per underlying) before sizing.

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
The source books allow two delta-hedging paths, but this project hard-locks execution to the options-only path:

1. `long calls + short underlying` — source-only reference; rejected by bot execution
2. `long calls + long puts` in the proportions required to neutralize delta — project path

For options-only delta neutrality (same strike and expiration), define total option count `N`:

- number of **call** contracts = `N × put delta`
- number of **put** contracts = `N × call delta`

This works because call delta and put delta at the same strike/expiry sum to `100%`. Source example: with call delta `52.27%` and put delta `47.73%` on a target book of `10,000` options, the neutral split is `4,773` calls and `5,227` puts — *not* `5,000/5,000`, which would leave the book delta-positive.

Source-only variant, rejected here: the stock hedge could also be built as `long puts + long stock`, but the source notes this requires **more margin** than `long calls + short stock` and that **puts tend to be less liquid**. Both stock paths are rejected by the project hard lock regardless.

**Leverage warning (source, load-bearing for sizing):** the options-only hedge is *naturally leveraged*. In the source's own comparison at the same underlying, the options-only book cost `$9,773.97` and produced gamma `1,622`, theta `-168`, vega `562`, while hedging the same calls with `2,495` short shares required `$124,748` of margin and produced only gamma `774`, theta `-84`, vega `268`. Same thesis, roughly **double the Greek exposure at ~8% of the capital**. Because this project is options-only by policy, every position inherits that leverage: size to the Greek exposure, not to the premium outlay, and keep both the per-trade and per-leg **INR 1,00,000** caps binding.

Project interpretation: use Call/Put combinations only. Any stock/underlying leg or cash-share hedge request fails with `OPTIONS_ONLY_REQUIRED`.

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

This is the most favorable path for the strategy. Source worked example: a `$330,000` long-vol book on an oil company; a corruption-scandal headline takes the stock from `$40` to `$32` (`-20%`) and IV from `30%` to `50%`; the book goes from `$333,640` to `$915,563`, a P/L of `$581,923`, in hours. The source's own instruction at that point is **neutralize the portfolio delta or close the entire position to protect the profit** — it does not tell the trader to ride it. That is the behavior the bot must copy: a black swan is a take-profit/re-hedge trigger, not a reason to widen risk. (Note the example's capital scale is far above this project's **INR 1,00,000** per-trade cap and is retained only as a directional illustration of convexity.)

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

Source IV path around earnings (encode this as a calendar-driven state machine):

- IV **rises** in the days-to-weeks leading up to the release, as uncertainty builds
- IV **spikes** one day before
- IV **drops sharply** immediately after, because the uncertainty the premium was pricing has been resolved

The source's constructive advice for simple volatility trading is therefore **trade the run-up, not the event**: dynamically delta hedge during the pre-earnings window for as long as `GARCH(1,1)` still says volatility is cheap, and be flat before the release.

Source counter-example showing why holding through is wrong: a `5%` gap **up** produces genuinely large gamma gains, but the accompanying `30%` collapse in implied volatility turns the position into a loss of roughly `50%`. Gamma being right does not save a naked-vega book.

Also explicitly forbidden by the source: shorting volatility to harvest the post-earnings IV crush. The vega gain is real, but the negative gamma it creates erodes it, and the risk profile is unbounded. This project never sells volatility (see Vega Scalping rule 5).

#### Scenario E: High-Priced Underlying In Small Account
Condition:

- high spot (`und_price` > **INR 1000**) raises per-lot premium and margin; there is **no** spot cap under the options-only hard lock

Action:

- allow the Call/Put structure if execution quality, liquidity, ATM, premium, and risk gates pass
- cash equities and index underlyings are both eligible when gates pass
- reject only if the Call/Put structure itself fails a gate (not solely on spot)

### Failure Modes

- IV does not rise despite the forecast
- GARCH is distorted after crisis periods
- theta bleed outpaces gamma
- liquidity is poor
- requested stock hedge is rejected; residual delta must be handled with Call/Put sizing or the trade is rejected
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
Source construction includes a stock hedge, but project execution uses the options-only four-leg construction.

Source-aligned reference (not executable in this bot):

- buy short-dated calls
- short longer-dated calls in a quantity that neutralizes vega
- short stock to neutralize residual delta — rejected by project hard lock

The source also explains *why* it reaches for calls rather than puts in the stock-hedge version: long calls leave the book delta-**positive**, which is neutralized by **short**ing the underlying (cheaper margin); a put-based version would leave it delta-negative and require **buying** the underlying (more margin), and puts are typically less liquid. This reasoning is source-only — the project has no stock leg either way — but it is retained because the same liquidity asymmetry between calls and puts still applies to leg selection.

Reason:

- shorter-dated options have more gamma and theta, less vega
- longer-dated options have more vega, less gamma and theta

Source reference pair: two same-strike calls at `35` DTE and `63` DTE. The `35`-day option carries more gamma and more theta; the `63`-day option carries more vega. That gap is the entire engine of the trade.

By selling fewer or differently sized longer-dated options against the near-dated long options, the portfolio can neutralize vega while keeping net gamma positive. Shorting the long-dated leg does introduce some negative gamma — but not enough to cancel the book's positive gamma, and it usefully **reduces theta** at the same time.

### Required Options-Only Construction
The project uses the four-leg options-only version:

- short-dated long calls
- longer-dated short calls
- short-dated long puts
- longer-dated short puts

**Mirror rule (source construction, do not improvise):** start from the vega-neutral call pair (buy short-dated calls, short long-dated calls), which leaves the book vega-neutral but delta-positive. Then **mirror the same quantities, strikes, and expiries in puts**. Because calls carry positive delta and puts negative delta, the sum of `(short-dated call delta + long-dated put delta)` equals the sum of `(long-dated call delta + short-dated put delta)`; the mirrored book is delta-neutral *and* stays vega-neutral. The bot should solve the call pair first and derive the put pair by mirroring, then verify both Greeks numerically rather than re-solving all four legs independently.

Use case:

- no stock/underlying trading path
- higher structural complexity
- much stronger need for synchronized execution

### Risk/Reward Framing (Source)
The source is explicit that gamma scalping is **less risky than the simple volatility trade because vega exposure is minimized — and correspondingly less rewarding**. In a vega-neutral book the only losses available are:

- the market not moving away from the hedge point (theta bleed), and
- distortion between the implied volatilities of the two expiries

Intraday, theta accrues day-over-day, so a same-session gamma scalp is theoretically delta-neutral, vega-neutral, *and* effectively theta-free — pure gamma extraction. In that mode **IV term-structure distortion is the only real loss source**, which is why the term-structure gate below is not optional.

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

#### Required Entry
- choose same-strike short-dated and longer-dated options
- buy the shorter-dated call(s)
- short the longer-dated call(s) until vega is neutralized
- add the matching short-dated put(s) and longer-dated put(s) needed to solve delta and vega neutrality

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

The reason for the compromise: longer expiry means more vega (the edge being harvested) but less gamma and theta — yet vega scalping is a fast trade, so the contract needs heavy liquidity, and long-dated chains often do not have it. The source's own worked example uses an ATM option roughly **two months from expiration**, which is a reasonable default starting point for the project's expiry search, subject to the liquidity gates winning any tie.

### Entry Rules
Primary source rule:

- enter only when intraday implied volatility is `2` standard deviations below its intraday mean

Do not invert the rule.

The source material is explicit:

- never treat `2-sigma above mean` as a short-volatility entry

### Position Construction
Project structure:

1. calls and puts combined to neutralize delta
2. no stock/underlying hedge path

Project preference:

- choose the Call/Put construction only when liquidity, slippage, and margin gates pass

**Source risk note that must not be lost:** the source presents the options-only delta hedge as the *leveraged and therefore riskier* way to run this trade, and says the same operation carries less risk when delta is neutralized with the underlying. This project has removed the lower-risk path by policy (options-only hard lock), so the leverage is structural and permanent. The compensating controls are the **INR 1,00,000** per-trade and per-leg caps, the liquidity gates, and mandatory same-day flattening — none of them may be relaxed to "make room" for a bigger vega scalp.

**Execution-speed note:** the source states intraday IV can move in a matter of seconds, so both the opening and the closing of a vega scalp must be algorithmic. A human cannot leg this trade in time, and a half-built delta hedge in a moving market is a directional bet, not a vol trade.

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

- **remaining legs of the intended multi-leg opening structure** (Phase 1+ on paper-sim — **no additional consent**; same open-trade capital / freshness / lot / Part T rules as the first entry)
- delta-maintenance hedges
- risk-reduction exits
- stop logic
- same-day flattening for vega scalping
- alerts for lost neutrality or abnormal costs

Consent applies to the **discretionary entry decision**. Completing the bot's intended multi-leg opening basket after that entry does **not** require a second Approve.

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
| Volatility Trading (54 pp.) | Option selection rules, trading rules 1–10, MA/EWMA/GARCH lineage + worked example, Company Z walkthrough, black-swan example, earnings IV-crush example, 10 practical aspects | Cheap-vol entry, delta hedge, gamma-theta management, event gating |
| Gamma Scalping (55 pp.) | Greeks-vs-time (35 vs 63 DTE), three entry modes, options-only mirror construction, Intel earnings example, management rules 1–2, 10 practical aspects | Vega-neutral construction, earnings gap, intraday scalp |
| Vega Scalping (52 pp.) | Stationarity vs non-stationarity, seven intraday rules, IV mean-reversion worked example, 7 practical aspects | Intraday IV z-score entry and same-day exit |

**Shared-chapter note:** chapters 1–6 (Introduction, Basics of Derivatives, Stock Option Properties, Black-Scholes, Option Greeks, Forecasting Volatility) are **identical across all three books**. The GARCH numbers, gamma-theta breakeven derivation, delta-hedge-without-stocks example, and the Greeks-vs-time relationship therefore apply to all three strategies and are consolidated here rather than repeated per strategy. Only chapters 7+ differ.

---

### Volatility Trading — Source Tables

#### Table VT-1: Option Selection Rules

| # | Rule | Bot Interpretation |
|---|---|---|
| 1 | Trade only high-liquidity options | Block illiquid chains; abs floors vol≥2000 / OI≥20000; ATM vol >150% and OI >130% of ≤20d avg (n≥10); spread < 0.5% |
| 1a | Options-only hard lock | Call/Put legs only; no stock/underlying trading, no T11 spot cap, and no index exclusion when other gates pass |
| 2 | Choose ATM strike | Delta nearest 50% → symmetric payoff *and* maximum magnitude on every other Greek |
| 3 | Choose the **next** expiration date, ~15–30 DTE | More gamma/theta, less vega |
| 4 | Avoid <10 DTE routinely | Black-Scholes distortions; extreme Greek risk |

**Source numbering note:** the Volatility Trading book states these as two rules — `1) Choose Only High Liquidity Options` and `2) Choose the ATM options with a close expiration date` — with the DTE band (~15–30) and the `<10 DTE` warning given in the surrounding prose and in practical aspect #6. Rows 3 and 4 above are that prose promoted to enforceable gates; row 1a is project policy, not source.

#### Table VT-2: Core Volatility Trading Rules (Source Numbering)

| # | Rule | Bot Interpretation |
|---|---|---|
| 3 | Enter when option **implied volatility (IV) is below** the GARCH(1,1) forecast | Primary cheap-vol signal; IV must be lower than GARCH |
| 4 | Delta hedging is prerequisite, not the strategy | Must neutralize delta before managing gamma/vega/theta |
| 5 | Always long options (positive gamma); never short vol for this strategy | Long calls or long call+put structures only |
| 6 | Delta hedge via (a) long calls + short stock, or (b) long calls + long puts same strike/expiry | Project executes only path (b); path (a) is source-only and rejected |
| 7 | Stock hedge: buy X calls ≈ long `X × call delta` shares; hedge by shorting that many shares. Source adds: the mirror version (buy puts, buy stock) works but needs **more margin**, and puts are **less liquid** | Source-only reference; rejected by project hard lock. The call-vs-put liquidity asymmetry still informs leg choice |
| 8 | Options-only hedge: total contracts N; **calls = N × put delta**; **puts = N × call delta** (call delta + put delta = 100% at same strike/expiry) | Lower margin; stronger Greek leverage. Source example: 10,000 options at call δ 52.27% → 4,773 calls + 5,227 puts, not 5,000/5,000 |
| 9 | Re-hedge when price moves away from last hedge point by gamma-theta breakeven (~1%) | Automated rebalance trigger; direction-agnostic (up or down) |
| 10 | Re-hedge by increasing or decreasing position | Track realized P/L and floating P/L separately |

**Rule 9 mechanics (source):** if the book is delta-positive after an up-move, neutrality is restored by any of — sell the underlying (rejected here), buy more puts, or shed some calls. Buying puts *increases* size; shedding calls *decreases* size and realizes part of the gain. Both are legal; the bot must record which path it took and keep the realized/floating split (Rule 10).

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

Predecessor estimators from the same source series (useful as sanity checks / fallbacks, not as trade signals):

| Model | Formula | Source Result |
|---|---|---|
| Moving Average | mean of squared log returns (equal weights) | variance 0.031692%; σ 1.7802% |
| EWMA (λ = 90%) | `σ_n² = λ·σ_(n-1)² + (1-λ)·u_(n-1)²` = 90%·0.036595% + 10%·0.036051% | σ_n² = 0.036541% |
| GARCH(1,1) | EWMA + long-run variance term (mean reversion) | σ_n² = 0.0362757% |

**Interpretation:** Compare annualized GARCH forecast to annualized option IV. IV below forecast = cheap vol entry candidate. `√252` assumes business-day annualization — confirm the IV feed uses the same convention (the source warns some markets annualize on calendar days) before comparing. `VL` = sample variance of the log-return window. After black swan events, GARCH may be distorted and will emit **false** `IV < GARCH` signals across many chains at once — block or downgrade signals until normalization (a broad simultaneous cheap-vol reading is itself a distortion tell).

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
| Setup | Stock at $20; nearest-ATM strike is **$20.20** (exact ATM rarely exists); start 10 call + 10 put contracts = 20 total | Initial portfolio delta −92.56 (not neutral) |
| Hedge attempt A | Adjust **puts**: exact neutrality needs **8.3** contracts, must round down to 8 | Best delta +16.47 (too long) |
| Hedge attempt B | Adjust **calls** instead (better in this example) | Delta −2.04; margin $1,190.08 (larger position → slightly more margin) |
| Price move | Spot +1% to $20.20 (≈ breakeven distance) | Floating P/L +$12.39 (~1% on margin); delta +125.82 |
| Re-hedge | Sell 2 call contracts (reduce size) | Realized +$19.26; floating −$6.88; sum unchanged vs pre-hedge floating |
| Carry | Breakeven paid once → D+0 becomes D+1 | Theta of one day is covered |
| Overnight | −2% gap; IV 20% → 22% | Floating +$120.40 (gamma from yesterday + gap, plus vega, minus theta) |
| Total trade | Realized $19.26 + floating $120.40 | **$139.66 profit on ~$1,200 margin (~11.6%)** |

**Interpretation:** Small contract counts prevent perfect delta neutrality (with 100 contracts the 8.3 would have been 83 and the hedge far cleaner). Bot must log residual delta, evaluate **both** the call-adjust and put-adjust paths and pick the lower absolute residual delta, note that reducing contract count also reduces Greek magnitude, and track realized vs floating P/L on every rebalance.

**Source's own attribution of the P/L:** gamma gains are what *pay for theta*; the vega gain from IV 20% → 22% is where the actual profit came from. The source states plainly that "it's extremely important that the implied volatility rises so that significant profits can arise." A cheap-vol trade that only ever pays its theta is not a winning trade — the bot should not treat repeated breakeven payments alone as success.

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
| IV falls and price quiet | Exit early; vega losses dominate (quiet tape means breakeven is *also* hard to reach — the two failures compound) |
| Entered on IV cheap vs GARCH, but IV then falls **more than 3 percentage points** | Treat as failed thesis and exit. Source: it is "extremely rare for vega to fall more than three percentage points if IV is lower than the GARCH(1,1)" — so a 3+ point drop means the forecast, not the market, was wrong |
| Multiple days elapsed | Do not carry. Source: institutional traders don't hold these many days — the position grows complex and, as price drifts from the original hedge point, the Greeks become much less pronounced |

#### Table VT-9: Black Swan While Long Volatility (Source Worked Example)

| Field | Value | Bot Interpretation |
|---|---|---|
| Position | Simple volatility trade on an oil company, ~$330,000 deployed | Scale is source-only; project cap is INR 1,00,000 per trade |
| Shock | Corruption headline; stock $40 → $32 (−20%) | Unscheduled, unhedgeable event |
| IV response | 30% → 50% | Long vega pays alongside gamma |
| P/L | +$581,923 ($333,640 → $915,563) in hours | Convexity, not prediction |
| Prescribed action | **Neutralize delta or close the whole position** to protect the profit | Hard-code as a take-profit / re-hedge trigger; never "let it run" |

**Interpretation:** This is the payoff the strategy exists to capture, but the source treats a black swan as an *exit event*, not a trend to ride. Pair with Shared Kill Conditions: an unplanned event the setup was not designed for is a flatten trigger even when it is currently profitable.

#### Table VT-10: Earnings IV Crush — Why Simple Vol Avoids The Event

| Phase | IV Behavior | Bot Action |
|---|---|---|
| Days-to-weeks before release | IV rises as uncertainty builds | Valid dynamic-delta-hedge window **if** `IV < GARCH` still holds |
| One day before | IV spikes | Prepare to be flat; do not initiate simple long-vol |
| Immediately after release | IV drops sharply as uncertainty resolves | Must be flat; this is the crush |
| Source counter-example | 5% gap **up** with IV −30% | Large gamma gain, but ~**50% net loss** — vega dominates |
| Tempting inversion | Short vol to harvest the crush | **Forbidden** — negative gamma erodes the vega gain and the risk is unbounded |

**Interpretation:** For simple volatility trading, earnings is a window to trade *into*, not *through*. Gate on the earnings calendar (and the `Market_News.txt` overlay) to force flat-before-release. If the intent is to capture the gap itself, that is a gamma-scalping trade, not this one.

#### Table VT-11: Options-Only Hedge Is Leveraged (Source Comparison)

| Metric | Options-only (calls + puts) | Calls + short stock |
|---|---|---|
| Capital / margin to open | $9,773.97 | $124,748 (2,495 shares @ $50) |
| Gamma | 1,622 | 774 |
| Theta | −168 | −84 |
| Vega | 562 | 268 |

**Interpretation:** Same thesis, roughly double the Greek exposure at ~8% of the capital — the source calls the options-only delta hedge "naturally leveraged." Since this project is options-only by hard lock, that leverage is permanent and not a choice. Size on **Greek exposure and worst-case loss**, not on premium outlay, and treat the INR 1,00,000 per-trade / per-leg caps as binding limits rather than targets.

#### Table VT-12: Volatility Index Stationarity (Context Only)

| Regime | Source VIX Level | Bot Use |
|---|---|---|
| Baseline / relative low | 8%–12% | Historically followed by a rise; supportive context for long-vol |
| Common intermediate peak | ~25% | Frequent mean-reversion ceiling |
| Larger stress peak | ~48% | Elevated regime |
| 2008 financial crisis | ~96% | Model-distortion regime |
| 2020 pandemic | ~85% | Model-distortion regime |

**Interpretation:** Volatility indices are stationary in a way price is not, which is why relative lows tend to be followed by rises. The source is explicit that reading VIX highs/lows is **anecdotal and not the institutional method** — the `IV vs GARCH(1,1)` comparison remains the signal. For this project the analogue is **India VIX**, and it should be used only as a regime/context filter and a distortion tripwire (see the P1 backlog item on India VIX regime filters), never as a standalone entry.

---

### Gamma Scalping — Source Tables

#### Table GS-1: Greeks Versus Time To Expiration

| Greek | Relationship To Expiry | Near-Dated Option | Far-Dated Option |
|---|---|---|---|
| Gamma | Inversely proportional | Higher | Lower |
| Theta | Inversely proportional | Higher (more decay) | Lower |
| Vega | Directly proportional | Lower | Higher |

Source reference pair (same strike, two expiries): **35 DTE vs 63 DTE** calls — the 35-day leg shows more gamma and more theta, the 63-day leg more vega. Use a comparable near/far separation when solving the structure; too small a gap leaves nothing to hedge with.

**Interpretation:** The source stock hedge is not executable in this project. Use the four-leg Call/Put construction to target delta neutral, vega neutral, gamma positive, theta negative. Shorting the far-dated leg adds some negative gamma (net gamma stays positive) and usefully **reduces theta** — the structure is a deliberate trade of vega exposure for a smaller but cheaper-to-carry gamma position.

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
| 1 | Select same-strike short-dated and long-dated calls and puts | Required four-leg project construction |
| 2 | Buy short-dated calls and puts | Provides gamma and theta |
| 3 | Short long-dated calls until portfolio vega ≈ 0 — solve the **call pair first** | Book is now vega-neutral but delta-positive |
| 4 | **Mirror** the identical quantities, strikes, and expiries in puts | Call/put delta signs cancel; book becomes delta-neutral and stays vega-neutral. No stock/underlying leg or cash-share hedge path |
| 5 | Verify all four Greeks numerically after solving | Do not assume the mirror is exact after rounding to lot size; log residual delta and residual vega |

**Delta identity behind step 4 (source):** `δ(short-dated call) + δ(long-dated put)` = `δ(long-dated call) + δ(short-dated put)`. This is why mirroring works and why the bot should derive the put pair rather than re-solving four legs independently.

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
| Post-entry 20% IV drop (vega-neutral book, IV 40% base) | Minimal P/L impact | Validates vega hedge purpose |
| Options-only book, price +5% with IV −30% | Gamma gains survive the crush | The same shock that costs a simple long-vol book ~50% (Table VT-10) is absorbed here |

**Source warning:** term-structure distortion is described as the **hidden problem** of this strategy. IV is directly proportional to time to expiry *on average*, but the two expiries oscillate independently. Entering when the short-dated IV sits at a local maximum and the long-dated IV at a local minimum produces a loss when those IVs correct toward their "correct" relationship — even though the book was vega-neutral at entry. Optimal geometry is `IV(long expiry) > IV(short expiry)`; the forbidden entry is `IV(long) < IV(short)`.

#### Table GS-9: Gamma Scalping Risk/Reward Profile (Source)

| Aspect | Source Position | Bot Interpretation |
|---|---|---|
| Risk vs simple vol trade | **Lower** — vega exposure is minimized | Preferred structure when IV direction is uncertain |
| Reward vs simple vol trade | **Lower** — no vega upside to capture | Do not expect simple-vol-sized outcomes; score net of costs |
| Worst case | Market does not move away from the hedge point + theta bleed | Bounded and known at entry |
| Only other loss source | IV term-structure distortion between the two expiries | Gate at entry (Table GS-8); monitor post-entry |
| Intraday mode | Theta accrues day-to-day, so a same-session scalp is delta-neutral, vega-neutral, and effectively theta-free | Pure gamma extraction; term-structure distortion becomes the **sole** loss source |
| Execution requirement | Source: "at least three simultaneous trades" (four in the options-only version) | Highest execution bar of the three strategies; algorithmic multi-leg submit is mandatory, manual legging will fail |

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
| Instrument | ATM option, ~**2 months** from expiration | Longer expiry = more vega, but liquidity must still pass |
| Entry trigger | IV crosses −2σ below intraday mean | Long vol via delta-neutral calls+puts |
| IV distance to mean | ~2 percentage points | Proxy for expected vega capture |
| Position cost to open | $16,533 | Size reference |
| Profit at mean reversion | $1,652 | ~10% return; source explicitly **excludes** likely gamma add-on |
| Risk scaling | Source: higher profit ⇒ higher risk; a **larger σ ⇒ higher risk** | Widen-band setups are not free upside — size down as intraday σ rises |
| Leverage note | Options-only hard lock | Source calls the options-only version the *leveraged and riskier* path and says the stock-hedge version carries less risk. Project has removed the lower-risk path by policy — compensate with the INR 1,00,000 caps, liquidity gates, and same-day flatten |
| Opportunity frequency | Some days offer several setups; some offer none, or IV is not stationary at all | Never force a trade; no-signal is the expected outcome on many sessions |

#### Table VS-5: Vega Scalping Failure And Antifragile Scenarios

| Scenario | P/L Effect | Bot Action |
|---|---|---|
| IV reverts to mean | Profit | Standard exit |
| Breaking news spikes IV | Profit (long vega) | Take profit; do not wait for perfect mean touch |
| Quiet tape; IV drifts lower | Loss | Stop at 3σ–4σ; same-day flatten |
| IV variance unstable (fixed mean, variable σ) | Signal degradation — bands move while mean holds | Block new entries; less severe than a drifting mean but still disqualifying |

**Source framing:** "the only way to lose money with Vega Scalping is if the market doesn't move for too long," which lets IV fall far enough to hit the stop. Conversely, any breaking news mid-trade is a *win* because long vega gains on the IV spike — the strategy is antifragile in the same sense as the other two. The bot should therefore treat a quiet, low-participation tape as the actual enemy, and should not interpret a news-driven IV spike as a reason to hold out for a textbook mean touch.

#### Table VS-6: Why 2σ — Empirical Rule Basis (Source)

| Band | Expected Coverage | Bot Interpretation |
|---|---|---|
| ±1σ | ~68% | Routine noise; no signal |
| ±2σ | ~95% (source demo: 292 of 300 points) | Entry threshold — genuinely uncommon reading |
| ±3σ | ~99.7% | Stop level (conservative setting) |
| ±4σ | Beyond the empirical rule | Stop level (higher risk tolerance) |

**Interpretation:** The 2σ trigger is not arbitrary — it is the empirical-rule tail. Its validity depends entirely on the series being stationary; the source's warning is that applying the same bands to a non-stationary series is the Bollinger-Bands-on-price error ("moving goalposts"). The bot must therefore validate intraday stationarity **before** trusting the z-score, not merely compute it.

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
| 1 | Stock price and IV affect margin | Pre-trade margin model uses spot and IV. Higher IV → richer premium → more capital per unit of exposure |
| 2 | Small contract counts | Expect imperfect delta/vega neutrality; enforce minimum size or reject. Source: fine-tuning improves roughly in proportion to contract count (8.3→8 vs 83) |
| 3 | Algorithmic execution | Multi-leg synchronized submit; no manual legging in production. Source leg counts: simple vol **2** simultaneous orders, gamma scalping **3+** (4 options-only), vega scalping **2** but with seconds-scale IV drift. Algos may also slice to limit liquidity/trapping risk. Explicitly an *execution* algo — it does not analyze the market |
| 4 | GARCH after black swans | Block cheap-vol signals until model normalizes |
| 5 | Gamma/theta vs vega vs time | Use Table GS-1 for expiry selection |
| 6 | Avoid <10 DTE | Hard filter except research mode |
| 7 | Liquidity | Spread and OI filters; critical for long-dated gamma legs |
| 8 | Re-hedge by increasing or decreasing | Preserve realized + floating P/L ledger |
| 9 | Greek equilibrium is local | Recompute Greeks after every material move |
| 10 | Goal Seek / numerical hedge solve | Solve contract counts numerically; do not guess ratios. Same technique derives the gamma-theta breakeven: solve for the spot move that makes P/L equal the day's theta |

**Source coverage note:** the Volatility Trading and Gamma Scalping books both list all 10 items (Gamma Scalping restates #2, #3 and #8 in terms of Delta **and** Vega). The Vega Scalping book lists only 7 — it omits the GARCH-after-black-swans, increase/decrease-position, and Greek-equilibrium items, since a same-day trade with no theta carry does not need them. This project applies all 10 to all three strategies; the omission is a scope difference in the source, not a permission.

#### Table SH-2: Delta Hedge Construction Comparison

| Method | Legs | Margin | Liquidity | Neutralization Quality |
|---|---|---|---|---|
| Long calls + short stock | 2 | Source-only | Not executable | Rejected by `OPTIONS_ONLY_REQUIRED` |
| Long calls + long puts | 2+ | Lower | Option-only | Sensitive to contract granularity |
| Gamma: calls spread + stock | 3+ | Source-only | Not executable | Rejected by `OPTIONS_ONLY_REQUIRED` |
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
| Crisis / post-shock tone | Tag bearish + macro flag; route through early_exit like any adverse tone — no automated hard block |
| Breaking news after long-vol entry | Prefer take-profit / aggressive re-hedge (do not widen stops) |

---

### Bot Ingestion Notes For This Section

When indexing this document for RAG or strategy engines:

- Tag each table with `strategy`, `topic`, and `source_doc` metadata (for example: `doc-gamma`, `gamma-theta-breakeven`).
- Prefer retrieving entire table + interpretation chunk together; rows split across chunks lose execution context.
- Numeric examples (Company Z, Intel, black swan, earnings crush, leverage comparison, vega example) are calibration references in USD at source scale, **not** guaranteed future performance and **not** sizing guidance — the project's INR 1,00,000 per-trade / per-leg caps always win.
- Rule 5 in Vega Scalping (never short vol at +2σ) is a hard constraint, not a suggestion. So is the project's options-only lock.
- Hard constraints extracted from the sources, for direct encoding: never short volatility (any strategy); never trade `<10 DTE` outside research mode; never enter gamma scalping with `IV(long expiry) < IV(short expiry)`; never hold a simple volatility trade through an earnings release; exit a cheap-vol trade if IV falls more than 3 percentage points against the GARCH thesis; flatten every vega scalp same session.

## Document Status
This file is intended to be the canonical high-level trade-execution reference for the project. The section **Complete Source Tables And Interpretations** consolidates all execution-critical tables and numbered rules from the three source PDFs. It should be updated whenever:

- a strategy rule changes
- new scenario handling is added
- broker or margin constraints change
- execution infrastructure improves
- backtest evidence invalidates a source-derived heuristic
- paper-sim or `Market_News.txt` wiring changes how SH-4 / kills are applied in rehearsal

**Related docs:** `Docs/Paper_Simulator.md` (paper path), `Market_News.txt` (news curation), `Docs/Trading_Parameters.md` (Part U news keys), Architecture §8.8.
