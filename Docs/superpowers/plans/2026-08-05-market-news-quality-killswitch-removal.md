# Market_News quality upgrade + kill-switch removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Market_News.txt` drive real source-trust-tiered, always-on SH-4
news gating, and remove every kill-switch mechanism from the bot — the
Market_News-driven `kill_event` auto-flatten/auto-block, and the separate
global manual Kill Switch (persisted arm/disarm, risk-gate block,
pause/resume endpoints, all UI) — end to end across backend, frontend, docs,
and tests.

**Architecture:** `Market_News.txt` is parsed by
`backend/services/market_news/curation.py` into three things: `monitors`,
`windows`, and `bot_priority` — nothing else in the file is machine-read.
`bot_priority`'s list order already doubles as the ranking key
`ingest.py::_rank_for_window` uses, so making it a complete, tier-ordered
list of all 7 ingested sources is what turns "trust tiers" from prose into
enforced ranking. The kill-switch removal deletes two independently-wired
mechanisms: (1) `MarketNewsSummary.kill_event`, computed in
`classifier.py::aggregate_packet_flags` from a post-shock regex hit, consumed
by `strategy_selection.py` (blocks new SH-4 entries, forces post-entry
flatten) and `paper_sim/automation.py` (flattens open positions); (2) the
global `KillSwitchState` (disk-persisted), consumed by
`execution/risk_gate.py` (blocks all order submission),
`paper_sim/automation.py` (skips the tick loop), `routers/bot.py`
(`/bot/pause`, `/bot/resume`), and the frontend `SituationalBar` /
`dashboard` / `risk` pages.

**Tech Stack:** Python 3 / FastAPI / Pydantic (backend), Next.js / React /
TypeScript (frontend), pytest (`asyncio_mode=auto`).

## Global Constraints

- No fills outside `paper_sim` — this plan does not touch that boundary.
- `pytest -m "not integration"` must pass after every task that touches
  Python code.
- Quant signals (GARCH, IV z-score) remain primary; only the news overlay
  and kill mechanisms change.
- Windows-only dev environment — Bash tool commands run under Git Bash;
  `pytest`/`npm` commands below assume the repo root as CWD.
- Every removal task must leave **zero** matches for
  `kill_switch|kill_event|KillSwitch` in `backend/` and `frontend/src/`
  except historical prose in `Docs/bot_health/BACKLOG.md` and this plan/spec.

---

### Task 1: `Market_News.txt` — trust tiers, always-on ingestion, no kill language

**Files:**
- Modify: `Market_News.txt`
- Test: `backend/tests/test_market_news.py` (`test_curation_contract_loads_market_news_txt`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `load_curation_contract().bot_priority` — a 7-element tuple in
  tier order `("nse", "sebi", "reuters", "moneycontrol", "economic_times",
  "pulse", "cnbc_tv18")` — Task 2 relies on this exact order and exact
  source-id spelling (must match `curation.py`'s `SOURCE_ALIASES`/
  `normalize_source_id` output).

- [ ] **Step 1: Update the failing/changing assertion in the test first**

Edit `backend/tests/test_market_news.py::test_curation_contract_loads_market_news_txt`
(currently lines 37-45) to assert the full expanded priority list:

```python
def test_curation_contract_loads_market_news_txt():
    contract = load_curation_contract()
    assert contract.loaded is True
    assert contract.bot_priority == (
        "nse",
        "sebi",
        "reuters",
        "moneycontrol",
        "economic_times",
        "pulse",
        "cnbc_tv18",
    )
    assert "nse" in contract.windows["session"] or "pulse" in contract.windows["session"]
    assert normalize_source_id("Reuters India") == "reuters"
    assert normalize_source_id("SEBI circulars") == "sebi"
```

- [ ] **Step 2: Run it to confirm it fails against the current file**

Run: `pytest backend/tests/test_market_news.py::test_curation_contract_loads_market_news_txt -v`
Expected: FAIL — current `bot_priority` is `("reuters", "moneycontrol", "economic_times", "nse", "sebi")` (5 items, Reuters first).

- [ ] **Step 3: Rewrite `Market_News.txt`**

Replace the file's contents with:

```markdown
# Market News — India curation contract

> **Used by:** Architecture §8.8, `Docs/Trading_Strategies.md` (Table SH-4 news overlay), `Docs/Paper_Simulator.md`, `Docs/Trading_Parameters.md` Part U

Ops-editable list of preferred India news sources and pull windows for **sentiment / event flags**. Quant signals (GARCH, IV z-score) stay primary; this file defines **what to read, in what priority, and when it's expected to be fresh** so the bot can gate strategy selection and paper-sim automation.

## Monitor

- Moneycontrol — company-specific developments
- NSE India — official announcements and filings
- The Economic Times – Markets — macroeconomic news
- Reuters India — fast, factual coverage with minimal speculation
- Pulse by Zerodha — consolidated headlines
- SEBI circulars — regulatory notices
- CNBC TV18 — market TV coverage

## Recommended daily workflow

All 7 curated sources are ingested continuously, every cycle, regardless of
time of day — nothing is skipped outside its window. The windows below
describe when each source is *expected* to publish fresh headlines, for
dashboard/staleness display only; they are **not** a ranking penalty. An
off-window source with a real headline still ranks by its trust tier
(below), never last by default.

### Before market open (8:00–9:00 AM IST)

- Reuters India
- Economic Times Markets
- CNBC TV18

### During market hours

- Moneycontrol Live
- Pulse by Zerodha
- NSE announcements

### After market close

- Economic Times analysis
- Company earnings
- FII/DII activity
- Sector performance

## For the AI trading bot / paper-sim

Build the news ingestion pipeline (`backend/services/market_news/` or equivalent) around this priority order — a trust tier, highest first. Within a tier, list order is the tie-break. This list is the actual ranking key the bot uses (`curation.py::_rank_for_window`), and also weights how much each source's tone counts toward `dominant_tone` when sources disagree (`classifier.py`) — higher tiers dominate lower ones.

1. NSE India (Tier 1 — official/regulatory)
2. SEBI circulars (Tier 1 — official/regulatory)
3. Reuters (Tier 2 — wire, low-noise)
4. Moneycontrol (Tier 3 — general market press)
5. Economic Times (Tier 3 — general market press)
6. Pulse by Zerodha (Tier 4 — aggregator)
7. CNBC TV18 (Tier 4 — TV)

This mix feeds sentiment and event-driven gates for:

- Live recommendations (`GET /api/v1/recommendations` → `market_news`)
- Paper simulator (`GET /api/v1/paper-sim/news` + `/signals`) acting per `Trading_Strategies.md`

Map classified tone / topics / symbol tags through Table SH-4 (Architecture §8.8.4). Shock/crisis tone is still classified and shown (topic tag, bearish sentiment, macro risk flag) — it does not auto-flatten positions or auto-block entries on its own; it flows through the same bearish-tone `early_exit` path as any other adverse headline.
```

- [ ] **Step 4: Run the test again to confirm it passes**

Run: `pytest backend/tests/test_market_news.py::test_curation_contract_loads_market_news_txt -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Market_News.txt backend/tests/test_market_news.py
git commit -m "Rewrite Market_News.txt with trust-tier priority and always-on ingestion"
```

---

### Task 2: `curation.py` — trust-tier ranking replaces window-based ranking

**Files:**
- Modify: `backend/services/market_news/ingest.py:176-189` (`_rank_for_window`)
- Test: `backend/tests/test_market_news.py` (new test)

**Interfaces:**
- Consumes: `CurationContract.bot_priority` (Task 1's 7-item tuple),
  `CurationContract.sources_for_window` (unchanged signature).
- Produces: `load_raw_headlines(...)` ranks purely by
  `(bot_priority index, time_published)` — later tasks / callers see no
  signature change, only ordering change. `sources_for_window` stays used
  only for `paper_news_packet`'s `window_sources` display field
  (`service.py:209`), not for ranking.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_market_news.py`:

```python
def test_rank_for_window_uses_trust_tier_not_window_membership():
    """An off-window Tier-1 source (NSE) must outrank an in-window Tier-4
    source (Pulse) — windows are freshness labels, not a ranking penalty."""
    from backend.services.market_news.ingest import RawHeadline, _rank_for_window

    contract = load_curation_contract()
    items = [
        RawHeadline(
            title="Pulse roundup",
            summary="s",
            source="Pulse by Zerodha",
            source_id="pulse",
            time_published="20260730T090000",
        ),
        RawHeadline(
            title="NSE circular",
            summary="s",
            source="NSE India",
            source_id="nse",
            time_published="20260730T090000",
        ),
    ]
    # "pre_open" window's in-window sources do not include nse or pulse,
    # so with window-ranking removed, trust tier alone decides order.
    ranked = _rank_for_window(items, contract, "pre_open")
    assert ranked[0].source_id == "nse"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest backend/tests/test_market_news.py::test_rank_for_window_uses_trust_tier_not_window_membership -v`
Expected: FAIL (current code sorts `pulse` and `nse` as equally "out of window" — order falls back to `time_published` tie, or window inclusion logic changes result unpredictably; either way it doesn't reliably assert `nse` first without the fix).

- [ ] **Step 3: Rewrite `_rank_for_window`**

Replace `backend/services/market_news/ingest.py:176-189`:

```python
def _rank_for_window(
    items: list[RawHeadline],
    contract: CurationContract,
    workflow_window: str | None,
) -> list[RawHeadline]:
    """Rank by trust tier (``bot_priority`` order), then recency.

    ``workflow_window`` is accepted for call-site compatibility but no
    longer biases ranking — all curated sources are always in play
    regardless of time of day (Market_News.txt).
    """
    _ = workflow_window
    priority = {sid: idx for idx, sid in enumerate(contract.bot_priority)}

    def sort_key(item: RawHeadline) -> tuple[int, str]:
        pri = priority.get(item.source_id, 100)
        return (pri, item.time_published)

    return sorted(items, key=sort_key)
```

- [ ] **Step 4: Run the new test and the full market_news suite**

Run: `pytest backend/tests/test_market_news.py -v`
Expected: All PASS, including the new test and
`test_curation_contract_loads_market_news_txt` from Task 1.

- [ ] **Step 5: Commit**

```bash
git add backend/services/market_news/ingest.py backend/tests/test_market_news.py
git commit -m "Rank Market_News headlines by trust tier only, not workflow window"
```

---

### Task 3: `classifier.py` — trust-tier weighted tone aggregation

**Files:**
- Modify: `backend/services/market_news/classifier.py:200-268` (`aggregate_packet_flags`)
- Test: `backend/tests/test_market_news.py` (new test)

**Interfaces:**
- Consumes: `ClassifiedHeadline.source_id` (already present on every
  classified headline).
- Produces: `aggregate_packet_flags(...)`'s `dominant_tone` now favors
  higher-trust sources when tone disagrees — no change to the function's
  signature or the other returned keys.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_market_news.py`:

```python
def test_dominant_tone_weighted_by_source_trust_tier():
    """A single Tier-1 (NSE) bearish headline must outweigh two Tier-4
    (CNBC/Pulse) bullish headlines on dominant_tone."""
    from backend.services.market_news.classifier import (
        aggregate_packet_flags,
        classify_headline,
    )

    bearish_nse = classify_headline(
        title="NSE flags sharp guidance cut, downgrade wave hits sector",
        summary="Regulatory filing shows weak outlook.",
        source="NSE India",
        source_id="nse",
        time_published="20260730T090000",
    )
    bullish_cnbc = classify_headline(
        title="Markets rally as traders cheer surge in sentiment",
        summary="Upgrade chatter on CNBC panel.",
        source="CNBC TV18",
        source_id="cnbc_tv18",
        time_published="20260730T090100",
    )
    bullish_pulse = classify_headline(
        title="Rebound continues, gains extend into afternoon session",
        summary="Roundup shows broad recovery.",
        source="Pulse by Zerodha",
        source_id="pulse",
        time_published="20260730T090200",
    )
    flags = aggregate_packet_flags([bearish_nse, bullish_cnbc, bullish_pulse])
    assert flags["dominant_tone"] == "bearish"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest backend/tests/test_market_news.py::test_dominant_tone_weighted_by_source_trust_tier -v`
Expected: FAIL — today every headline contributes `abs(score) + 0.25`
unweighted, so 2 bullish headlines (~0.4-0.5 combined) beat 1 bearish
(~0.65+0.25), or land close/tied depending on regex hit counts; the test is
written to require a >2x tier-1 weight to win deterministically, which the
current code doesn't apply.

- [ ] **Step 3: Add trust-tier weights and apply them in aggregation**

Add near the top of `backend/services/market_news/classifier.py` (after the
existing module-level regex constants, before `ClassifiedHeadline`):

```python
# Trust tier weight for dominant_tone aggregation — mirrors Market_News.txt's
# "For the AI trading bot" priority order (Tier 1 official/regulatory down to
# Tier 4 aggregator/TV). Higher tiers dominate when sources disagree on tone.
_SOURCE_TRUST_WEIGHT: dict[str, float] = {
    "nse": 2.0,
    "sebi": 2.0,
    "reuters": 1.5,
    "moneycontrol": 1.0,
    "economic_times": 1.0,
    "pulse": 0.6,
    "cnbc_tv18": 0.6,
}
_DEFAULT_TRUST_WEIGHT = 1.0


def _trust_weight(source_id: str) -> float:
    return _SOURCE_TRUST_WEIGHT.get(source_id, _DEFAULT_TRUST_WEIGHT)
```

Then in `aggregate_packet_flags`, change the tone-scoring loop
(currently `backend/services/market_news/classifier.py:228-229`):

```python
    for item in items:
        tone_scores[item.tone] = tone_scores.get(item.tone, 0.0) + abs(item.sentiment_score) + 0.25
```

to:

```python
    for item in items:
        weight = _trust_weight(item.source_id)
        tone_scores[item.tone] = (
            tone_scores.get(item.tone, 0.0) + (abs(item.sentiment_score) + 0.25) * weight
        )
```

- [ ] **Step 4: Run the new test and the full market_news suite**

Run: `pytest backend/tests/test_market_news.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/market_news/classifier.py backend/tests/test_market_news.py
git commit -m "Weight Market_News dominant_tone aggregation by source trust tier"
```

---

### Task 4: Remove `kill_event` from the data model, classifier, and service layer

**Files:**
- Modify: `backend/models/recommendations.py:165` (drop `kill_event` field)
- Modify: `backend/services/market_news/classifier.py:200-338` (`aggregate_packet_flags`, `_interpretation`)
- Modify: `backend/services/market_news/service.py:222` (drop from `paper_news_packet`)
- Modify: `backend/tests/test_market_news.py` (drop `kill_event`/`"kill_event"` assertions)

**Interfaces:**
- Consumes: nothing new.
- Produces: `MarketNewsSummary` no longer has `kill_event`.
  `aggregate_packet_flags(...)`'s return dict no longer has a `"kill_event"`
  key, and `"kill_event"` is no longer a possible value of `"news_impact"`
  (post-shock now falls through to the same `dominant_tone == "bearish"` →
  `"early_exit"` branch as any other adverse headline). Task 5 and Task 6
  depend on `news.kill_event` and `news_impact == "kill_event"` no longer
  existing anywhere.

- [ ] **Step 1: Update `test_market_news.py` first — remove `kill_event` assertions**

In `test_classifier_tone_topics_symbols` (lines 61-74), replace:

```python
    flags = aggregate_packet_flags([shock])
    assert flags["news_post_shock"] is True
    assert flags["kill_event"] is True
    assert flags["news_impact"] == "kill_event"
    assert "post-shock" in flags["macro_risk_flags"]
```

with:

```python
    flags = aggregate_packet_flags([shock])
    assert flags["news_post_shock"] is True
    assert "kill_event" not in flags
    assert flags["news_impact"] == "early_exit"
    assert "post-shock" in flags["macro_risk_flags"]
```

In `test_get_market_news_from_fixture` (lines 85-91), remove `"kill_event"`
from the allowed `news_impact` set:

```python
    assert summary.news_impact in {
        "none",
        "take_profit",
        "rehedge_aggressive",
        "early_exit",
    }
```

- [ ] **Step 2: Run to confirm these two tests now fail against current code**

Run: `pytest backend/tests/test_market_news.py::test_classifier_tone_topics_symbols -v`
Expected: FAIL — `flags["kill_event"]` still exists and is `True` today.

- [ ] **Step 3: Drop the field from `MarketNewsSummary`**

In `backend/models/recommendations.py`, delete line 165:

```python
    kill_event: bool = False  # U10
```

- [ ] **Step 4: Remove `kill_event` computation and the forced post-shock kill branch in `classifier.py`**

In `aggregate_packet_flags` (`backend/services/market_news/classifier.py`),
remove the `kill_event` key and stop forcing `news_impact = "kill_event"`
on post-shock. Change:

```python
    news_not_blocking = not post_shock and dominant_tone != "bearish"
    kill_event = post_shock
    if post_shock:
        news_impact = "kill_event"
    elif event_imminent and dominant_tone == "bearish":
        news_impact = "early_exit"
    elif _any_breaking_bullish(items):
        news_impact = "rehedge_aggressive"
    elif dominant_tone == "bearish":
        news_impact = "early_exit"
    else:
        news_impact = "none"
```

to:

```python
    news_not_blocking = not post_shock and dominant_tone != "bearish"
    if event_imminent and dominant_tone == "bearish":
        news_impact = "early_exit"
    elif _any_breaking_bullish(items):
        news_impact = "rehedge_aggressive"
    elif dominant_tone == "bearish":
        news_impact = "early_exit"
    else:
        news_impact = "none"
```

Post-shock still forces `dominant_tone = "bearish"` earlier in the function
(unchanged, line ~247-248) and still contributes `"post-shock"` /
`"crisis_tone"` to `flags` (unchanged, lines ~258-260) — so it still shows up
as bearish tone + macro flags, just without a distinct forced impact value.

Then remove `"kill_event": kill_event,` from the returned dict (near the end
of the function, currently):

```python
    return {
        "dominant_tone": dominant_tone,
        "dominant_sentiment": sentiment_map[dominant_tone],
        "topics": topic_set,
        "symbol_tags": symbol_set,
        "earnings_mentions": earnings,
        "macro_risk_flags": flags,
        "news_not_blocking": news_not_blocking,
        "news_event_imminent": event_imminent,
        "news_post_shock": post_shock,
        "news_impact": news_impact,
        "kill_event": kill_event,
        "interpretation": interpretation,
    }
```

remove the `"kill_event": kill_event,` line.

Also update the empty-items early return (top of `aggregate_packet_flags`,
currently includes `"kill_event": False,`) — remove that key from the dict
there too.

Finally, in `_interpretation`'s post-shock branch (currently references
"block model-driven vol trades until normalization"), reword to match the
new non-blocking behavior:

```python
    if post_shock:
        return (
            "Crisis / post-shock tone in curated India headlines — "
            "tagged bearish and flagged for visibility (SH-4 news overlay); "
            "no automated flatten or block."
        )
```

- [ ] **Step 5: Remove `kill_event` from `paper_news_packet`**

In `backend/services/market_news/service.py`, delete line 222:

```python
        "kill_event": summary.kill_event,
```

- [ ] **Step 6: Run the updated tests**

Run: `pytest backend/tests/test_market_news.py -v`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/models/recommendations.py backend/services/market_news/classifier.py backend/services/market_news/service.py backend/tests/test_market_news.py
git commit -m "Remove Market_News-driven kill_event field and forced post-shock block"
```

---

### Task 5: Remove `kill_event` from `strategy_selection.py`

**Files:**
- Modify: `backend/services/strategy_selection.py`
- Modify: `backend/tests/test_strategy_selection.py`
- Modify: `backend/tests/test_signals.py`

**Interfaces:**
- Consumes: `MarketNewsSummary` without `kill_event` (Task 4).
- Produces: `PostEntryAction` no longer includes `"kill_event"`;
  `post_entry_news_action(...)` never returns `"kill_event"`;
  `news_blocks_model_trades(...)` no longer treats post-shock/crisis tone as
  a block reason (still blocks on `regulatory_surprise`). Task 6 depends on
  `post_entry_news_action` never returning `"kill_event"`.

- [ ] **Step 1: Update the tests first**

In `backend/tests/test_strategy_selection.py`:

Remove `kill_event=...` from every `_news(**overrides)` call and from the
`base` dict in the `_news` helper (line 43: delete `kill_event=False,`).

`test_n03_post_shock_blocks_all_vol` (lines 95-111) — remove `kill_event=True`
and `news_impact="kill_event"`, keep `news_post_shock=True`:

```python
def test_n03_post_shock_blocks_all_vol():
    """N-03: Post-shock / crisis → blocked / stand_aside."""
    news = _news(
        dominant_tone="bearish",
        news_post_shock=True,
        news_not_blocking=False,
        news_impact="early_exit",
        macro_risk_flags=["post-shock", "crisis_tone"],
    )
    sel = select_strategy_sh4(
        _quant(iv_annualized=0.20, garch_forecast=0.35, iv_z_score=-2.4),
        news,
    )
    assert sel.selected_strategy == StrategyType.blocked
    packet = select_strategy_packet(_quant(), news)
    assert packet["recommendation"] in {"blocked", "stand_aside"}
```

(`news_blocks_model_trades` still returns `True` here because
`news.news_post_shock` and the `"post-shock"`/`"crisis_tone"` flags remain —
only `kill_event` itself is gone; this test's *intent* — post-shock blocks
model trades — is unchanged and still holds after Task 5's code edit below.)

`test_n04_unplanned_news_kill_flattens` (lines 120-126) — this test's whole
premise (`kill_event` flatten) no longer exists. Replace it with a test of
the new behavior: post-shock after entry now flows through `early_exit`
like any bearish signal:

```python
def test_n04_post_shock_after_entry_is_early_exit_not_a_hard_kill():
    """N-04 (revised): Post-shock/unplanned news after entry is tagged
    bearish and routes through the normal early_exit path — there is no
    separate hard-kill action."""
    news = _news(
        news_impact="early_exit",
        news_post_shock=True,
        dominant_tone="bearish",
        news_not_blocking=False,
    )
    assert (
        post_entry_news_action(news, setup_designed_for_event=False, position_open=True)
        == "early_exit"
    )
```

`test_n04_designed_earnings_setup_not_killed_by_event_flag_alone`
(lines 129-140) — remove `kill_event=False,`:

```python
def test_n04_designed_earnings_setup_not_killed_by_event_flag_alone():
    news = _news(
        news_event_imminent=True,
        news_impact="early_exit",
        news_post_shock=False,
    )
    assert (
        post_entry_news_action(news, setup_designed_for_event=True, position_open=True)
        == "early_exit"
    )
```

At lines 227-237 and 266-276 (`force_news` payloads in the
`/paper-sim/strategies/select` endpoint tests), delete the
`"kill_event": False,` line from both dicts.

Also grep-check the rest of the file (lines 141-255, not shown above) for
any remaining `kill_event=` or `"kill_event"` occurrences and remove them
the same way — every `_news(...)` call site loses `kill_event=...` if
present.

In `backend/tests/test_signals.py`: remove `kill_event=False,` from the
`_news`-style helper (~line 46) and remove the two `"kill_event": False,`
lines from the JSON-body dicts (~lines 232, 271).

- [ ] **Step 2: Run to confirm failures against current code**

Run: `pytest backend/tests/test_strategy_selection.py -v`
Expected: FAIL — `MarketNewsSummary.model_validate` calls with no
`kill_event` key still succeed (field has a default), but
`post_entry_news_action` still checks `news.kill_event` (now always `False`
by default) so `test_n04_post_shock_after_entry_is_early_exit_not_a_hard_kill`
fails because the function's post-shock branch hasn't been removed yet —
actually with `kill_event` always `False` by default and `news_impact`
explicitly set to `"early_exit"`, this specific new test may already pass
before the code change; that's fine — the important failing case is
`test_n03_post_shock_blocks_all_vol`'s `news_impact="early_exit"` combined
with the old code's `if news.kill_event or news.news_impact == "kill_event"`
branch, which no longer matches, so confirm the suite runs and note which
pass/fail before Step 3; the real gate is Step 4 below (full green run).

- [ ] **Step 3: Remove `kill_event` from `strategy_selection.py`**

Remove `"kill_event",` from the `PostEntryAction` literal
(`backend/services/strategy_selection.py:33-39`):

```python
PostEntryAction = Literal[
    "none",
    "take_profit",
    "rehedge_aggressive",
    "early_exit",
]
```

In `news_blocks_model_trades` (lines 82-91), remove the `kill_event` check:

```python
def news_blocks_model_trades(news: MarketNewsSummary) -> bool:
    """True when crisis / post-shock / regulatory surprise should block model vol entries."""
    flags = _macro_flags_lower(news)
    if news.news_post_shock:
        return True
    if "crisis_tone" in flags or "post-shock" in flags:
        return True
    if "regulatory_surprise" in flags:
        return True
    return False
```

In `select_strategy_sh4`'s kill/block row (lines 187-211), remove the
`kill_event` branch from the reason string and simplify:

```python
    # --- Kill / block row (post-shock, H11/K4, regulatory) ---
    if quant.garch_distorted or news_blocks_model_trades(news):
        reason = (
            "garch_distorted=true"
            if quant.garch_distorted
            else "news_post_shock / crisis / regulatory block"
        )
        return StrategySelectionLogic(
            selected_strategy=StrategyType.blocked,
            scenario_tag="Post-shock — models distorted",
            cross_strategy_matrix_ref="Table SH-4: reduce/block all vol strategies",
            primary_signal=reason,
            rejected_strategies=[
                "simple_volatility",
                "gamma_scalping",
                "vega_scalping",
            ],
            news_impact=(
                "Crisis / post-shock / regulatory — block model trades (SH-4, H11, K4)"
            ),
        )
```

In `post_entry_news_action` (lines 410-438), remove the kill branch entirely:

```python
def post_entry_news_action(
    news: MarketNewsSummary,
    *,
    setup_designed_for_event: bool = False,
    position_open: bool = True,
) -> PostEntryAction:
    """Map packet news_impact to post-entry management (N-05, N-06).

    Breaking favorable news → rehedge_aggressive / take_profit (do not widen stops).
    Quiet + adverse → early_exit.
    """
    if not position_open:
        return "none"

    impact = (news.news_impact or "none").lower()
    if impact in {"rehedge_aggressive", "take_profit"}:
        return "rehedge_aggressive" if impact == "rehedge_aggressive" else "take_profit"
    if impact == "early_exit":
        return "early_exit"
    if news.dominant_tone == "bearish" and not news.news_not_blocking:
        return "early_exit"
    return "none"
```

(`setup_designed_for_event` is now unused inside the function body but stays
in the signature — `select_strategy_packet` still passes it, and removing a
public keyword argument is a bigger, unrelated API change out of scope here.)

In `select_strategy_packet` (lines 441-481), remove the `news.kill_event`
reference:

```python
        "recommendation": action if action != "blocked" else "stand_aside",
```

(This replaces the old `action if action != "blocked" else ("stand_aside" if
not news.kill_event else "blocked")` — `action` is never `"blocked"` unless
`select_strategy_sh4` returned `StrategyType.blocked`, which now happens
without any `kill_event` involvement, so collapsing to plain `"stand_aside"`
matches every remaining caller/test's expectation of `{"blocked",
"stand_aside"}`.)

And remove `"kill_event": news.kill_event,` from the `"market_news"` dict at
the end of `select_strategy_packet`.

- [ ] **Step 4: Run the full strategy_selection and signals suites**

Run: `pytest backend/tests/test_strategy_selection.py backend/tests/test_signals.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/strategy_selection.py backend/tests/test_strategy_selection.py backend/tests/test_signals.py
git commit -m "Remove kill_event from strategy_selection; post-shock now routes through early_exit"
```

---

### Task 6: Remove `kill_event` from `paper_sim/automation.py`

**Files:**
- Modify: `backend/paper_sim/automation.py`
- Modify: `backend/tests/test_automation.py`

**Interfaces:**
- Consumes: `post_entry_news_action(...)` (Task 5) never returns
  `"kill_event"`.
- Produces: `PaperAutomation._last_signal` no longer has a `"kill_event"`
  key; the flatten-trigger set no longer includes `"kill_event"` (harmless —
  it can never appear — but kept accurate).

- [ ] **Step 1: Update the test first**

In `backend/tests/test_automation.py`, find the test around line ~190-202
that patches `get_market_news` with
`_neutral_news(news_impact="kill_event", kill_event=True)` and asserts a
flatten happens. Replace it to use `news_impact="early_exit"` with
`news_post_shock=True` instead (the new equivalent post-shock-after-entry
signal), and remove `kill_event=False` from the `_neutral_news` helper
(line 63):

```python
def _neutral_news(**overrides) -> MarketNewsSummary:
    base = dict(
        headline_count=1,
        dominant_sentiment="Neutral",
        dominant_tone="neutral",
        earnings_mentions=0,
        macro_risk_flags=[],
        topics=[],
        symbol_tags=[],
        news_not_blocking=True,
        news_event_imminent=False,
        news_post_shock=False,
        news_impact="none",
        source_freshness={"reuters": datetime.now(timezone.utc)},
        workflow_window="session",
        interpretation="test",
        items=[],
    )
    base.update(overrides)
    return MarketNewsSummary.model_validate(base)
```

```python
    with patch(
        "backend.services.market_news.get_market_news",
        return_value=_neutral_news(news_impact="early_exit", news_post_shock=True),
    ):
        tick = await engine.automation.tick()

    assert any(a.get("action") == "flatten" for a in tick["actions"])
    assert engine.positions(status="open") == []
```

- [ ] **Step 2: Run to confirm current code still passes this variant**

Run: `pytest backend/tests/test_automation.py -k flatten -v`
Expected: PASS already (this path uses the existing `"early_exit"` branch of
the flatten-trigger set `{"kill_event", "early_exit", "take_profit"}`) — no
red state expected here; this step is a sanity check, not a TDD gate, since
the behavior under test doesn't change.

- [ ] **Step 3: Remove `kill_event` plumbing from `automation.py`**

In `PaperAutomation.tick` (`backend/paper_sim/automation.py`), remove
`"kill_event": news.kill_event,` from `_last_signal`:

```python
        self._last_signal = {
            "news_impact": news.news_impact,
            "post_entry_action": news_action,
            "dominant_tone": news.dominant_tone,
        }
```

And update the flatten-trigger set to drop the now-impossible value:

```python
        # PS-06: news early_exit / take_profit prefer flatten over re-hedge
        if news_action in {"early_exit", "take_profit"}:
```

- [ ] **Step 4: Run the full automation suite**

Run: `pytest backend/tests/test_automation.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/paper_sim/automation.py backend/tests/test_automation.py
git commit -m "Remove kill_event from paper_sim automation flatten trigger"
```

---

### Task 7: Delete the global manual Kill Switch — backend

**Files:**
- Delete: `backend/services/kill_switch_state.py`
- Modify: `backend/routers/bot.py`
- Modify: `backend/execution/risk_gate.py`
- Modify: `backend/execution/circuit_breakers.py`
- Modify: `backend/paper_sim/engine.py:214-219, 229-239` (the `_gate_ticks`/pre-trade-gate call site)
- Modify: `backend/paper_sim/automation.py`
- Modify: `backend/services/risk_snapshot.py`
- Delete: `backend/tests/test_kill_switch_state.py`
- Modify: `backend/tests/test_risk_gate.py`
- Modify: `backend/tests/test_automation.py`
- Modify: `backend/tests/test_phase0.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PreTradeContext` has no `kill_switch_armed` field;
  `evaluate_pre_trade_gate` has no `"kill_switch"` check;
  `routers/bot.py` has no `is_kill_switch_armed`, `/bot/pause`, `/bot/resume`;
  `PaperAutomation.state` never returns `"paused_kill_switch"`;
  `build_risk_snapshot()` has no `kill_switch_armed` key and
  `circuit_breakers_active` never contains `"kill_switch"`. Task 8
  (frontend) depends on all of these being gone from the API responses.

- [ ] **Step 1: Delete the kill-switch test file and its conftest fixture first**

Delete `backend/tests/test_kill_switch_state.py` entirely.

In `backend/tests/conftest.py`, remove the `_isolated_kill_switch_state`
fixture (lines 14-20), leaving only the `_market_news_offline_by_default`
fixture:

```python
"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _market_news_offline_by_default(monkeypatch: pytest.MonkeyPatch):
    """Keep Market_News on the bundled fixture unless a test enables live."""
    monkeypatch.setenv("MARKET_NEWS_LIVE", "0")
```

In `backend/tests/test_phase0.py`, remove lines 54, 57-63 (the
`kill_switch_armed` assertion and the `/bot/pause` / `/bot/resume` block):

```python
    bot = client.get("/api/v1/bot/status")
    assert bot.status_code == 200
    bot_body = bot.json()
    assert bot_body["execution_mode"] == "shadow"
    assert bot_body.get("place_order_enabled") is False
```

In `backend/tests/test_automation.py`, delete the entire
`test_ps08_kill_switch_skips_hedges` test function (lines ~260-283).

In `backend/tests/test_risk_gate.py`, delete `test_kill_switch_blocks`
(lines 60-63) and remove every `kill_switch_armed=False,` keyword argument
from the remaining `PreTradeContext(...)` calls in that file (lines 71, 84,
100, 109, 120, 132, 145, 152 per the earlier grep — each `PreTradeContext(`
call site loses that one line).

- [ ] **Step 2: Run to confirm these now fail (still importing deleted things)**

Run: `pytest backend/tests/ -k "kill_switch or ps08_kill_switch" -v`
Expected: Collection errors / FAIL — `kill_switch_state` module and
`kill_switch_armed` field still exist to import against at this point is
fine (tests were edited, not the code yet); the real check is Step 4.

- [ ] **Step 3: Remove the kill-switch code**

Delete `backend/services/kill_switch_state.py`.

In `backend/routers/bot.py`, remove the import, `is_kill_switch_armed`, and
both endpoints:

```python
"""Bot status, feed health, and global index marks."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.integrations.registry import (
    get_default_broker_provider,
    get_execution_mode,
    paper_stack_guard_status,
    place_order_enabled,
)
from backend.models.recommendations import FeedSource
from backend.services.feed_health import get_feed_sources
from backend.services.supervision_mode import get_supervision_mode
from backend.services.trade_executor import get_active_trade_id, is_one_trade_locked

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["bot"])


@router.get("/bot/status")
async def bot_status():
    supervision = get_supervision_mode()
    guard = paper_stack_guard_status()
    metrics: dict = {
        "daily_pnl": 0.0,
        "win_rate": 0.0,
        "drawdown_pct": 0.0,
        "portfolio_greeks": {
            "total_delta": 0.0,
            "total_gamma": 0.0,
            "total_theta": 0.0,
            "total_vega": 0.0,
        },
        "circuit_breakers_active": [],
    }
    try:
        from backend.services.risk_snapshot import bot_metrics_from_risk

        metrics.update(bot_metrics_from_risk())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Bot status risk metrics unavailable: %s", exc)

    return {
        "execution_mode": get_execution_mode().value,
        "requested_execution_mode": guard["requested_execution_mode"],
        "deploy_stack": guard["deploy_stack"],
        "live_blocked": guard["live_blocked"],
        "supervision_mode": supervision,
        "default_broker": get_default_broker_provider(),
        "autonomy": "supervised" if supervision == "supervised" else supervision,
        "scheduler_mode": "active",
        "regime": "mixed_vol",
        "daily_pnl": metrics["daily_pnl"],
        "win_rate": metrics["win_rate"],
        "drawdown_pct": metrics["drawdown_pct"],
        "portfolio_greeks": metrics["portfolio_greeks"],
        "circuit_breakers_active": metrics["circuit_breakers_active"],
        "pending_count": 0,
        "one_trade_locked": is_one_trade_locked(),
        "active_trade_id": get_active_trade_id(),
        "place_order_enabled": place_order_enabled(),
        "api_health": "ok",
        "phase": "1",
    }


async def _ensure_ws_for_feed_ui() -> None:
    """Best-effort A2 connect when ICICI credentials/session can open livestream."""
    try:
        from backend.integrations.icici_direct.market_data import get_market_data_adapter
        from backend.integrations.icici_direct.session_manager import get_session_manager

        health = get_session_manager().health()
        if health.get("authenticated") or health.get("credentials_ready"):
            await get_market_data_adapter().ensure_ws_connected()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Feed UI WS ensure skipped: %s", exc)


@router.get("/feeds/status")
async def list_feed_status() -> list[FeedSource]:
    """ICICI Direct + Market_News feed health (MCP registry retired — plan §1 / 0.3)."""
    await _ensure_ws_for_feed_ui()
    return get_feed_sources()


@router.get("/market/indices")
async def market_indices():
    """NIFTY 50 + India VIX marks for the situational bar (ICICI Direct quotes)."""
    from backend.integrations.icici_direct.market_data import get_market_data_adapter

    await _ensure_ws_for_feed_ui()
    marks = await get_market_data_adapter().get_global_indices()
    return {
        "as_of": marks[0].ts.isoformat() if marks and marks[0].ts else None,
        "indices": [m.model_dump(mode="json") for m in marks],
    }
```

In `backend/execution/risk_gate.py`, remove `kill_switch_armed: bool = False`
from `PreTradeContext` (line 90) and remove the "Kill-switch" check block
(lines 250-258):

```python
    # Buying power
    if ctx.buying_power_ok is not None:
```

(i.e. delete the `# Kill-switch` comment and its `checks.append(_check(...))`
block entirely, leaving the `# Buying power` block immediately after
`# Bot health / error rate`.)

In `backend/execution/circuit_breakers.py`, update the stale docstring on
`active_breaker_ids` (line 132) — it no longer applies:

```python
def active_breaker_ids(breakers: tuple[BreakerStatus, ...] | list[BreakerStatus]) -> list[str]:
    """Ids currently in warn/danger."""
    return [b.id for b in breakers if b.tone in ("warn", "danger")]
```

In `backend/paper_sim/engine.py`, remove the kill-switch check
(lines 214-219) and the `kill_switch_armed=kill_armed,` line from the
`PreTradeContext(...)` call (line 232):

```python
        freshness = self._gate_ticks(ticks_for_gate)

        snap = self.ledger.snapshot()
        buying_ok = snap.cash_inr > 0
        drawdown_pct = 0.0
        if snap.starting_capital_inr > 0:
            equity = snap.equity_inr
            drawdown_pct = max(
                0.0,
                (snap.starting_capital_inr - equity) / snap.starting_capital_inr * 100.0,
            )
        gate = evaluate_pre_trade_gate(
            PreTradeContext(
                feeds_fresh=bool(freshness.get("ok", True)),
                buying_power_ok=buying_ok,
                drawdown_pct=drawdown_pct,
                quantity=int(resolved_legs[0]["quantity"]) if resolved_legs else None,
                lotsize=int(resolved_legs[0]["lotsize"]) if resolved_legs else None,
            ),
            thresholds=self.config.pre_trade_thresholds(),
        )
```

In `backend/paper_sim/automation.py`, remove `_is_kill_switch_armed`
(lines 73-79), the `"paused_kill_switch"` state value (line 30), the
`state` property's kill-switch branch (lines 105-106), and the tick-loop
skip branch (lines 226-231):

```python
AutomationState = Literal["stopped", "running", "degraded"]
```

```python
    @property
    def state(self) -> AutomationState:
        if not self._running:
            return "stopped"
        if self._last_error:
            return "degraded"
        return "running"
```

```python
    async def tick(self) -> dict[str, Any]:
        """One automation cycle — callable from tests without starting the loop."""
        self._ticks += 1
        self._last_tick_at = datetime.now(timezone.utc)
        actions: list[dict[str, Any]] = []

        # Refresh marks (PS-09: skip actions if refresh fails / stale)
        try:
```

(i.e. delete the `_is_kill_switch_armed` function and the `if
_is_kill_switch_armed(): ...` block that preceded the marks-refresh `try`.)

In `backend/services/risk_snapshot.py`:
- Remove the `an earnings or news event appears...` line from
  `SHARED_KILL_CONDITIONS` (line 20) — see Task 8 for why (mirrors the
  `Trading_Strategies.md` edit).
- Remove the `is_kill_switch_armed` import and all `kill_armed` /
  `"kill_switch"` handling in `build_risk_snapshot()` and `_risk_events`:

```python
SHARED_KILL_CONDITIONS = [
    "liquidity collapses or spreads blow out beyond limits",
    "a hedge leg becomes unavailable",
    "the model input is stale or clearly corrupted",
    "required neutrality cannot be restored within cost limits",
    "residual delta or vega exposure exceeds portfolio limits",
    "the strategy's core assumption no longer holds",
]
```

```python
def _risk_events(
    *,
    breakers: list[dict[str, Any]],
    freeze_reason: str | None,
    greeks_passed: bool,
    account_updated_at: datetime | None,
    open_positions: int,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    now = _now()

    def add(level: str, text: str, when: datetime | None = None) -> None:
        ts = when or now
        events.append(
            {
                "level": level,
                "text": text,
                "ts": ts.isoformat(),
            }
        )

    if freeze_reason:
        add("warn", f"Learning adaptation frozen: {freeze_reason}")
```

(keep the rest of `_risk_events` unchanged — only drop the `kill_armed`
parameter and its `if kill_armed:` branch.)

In `build_risk_snapshot()`:

```python
    from backend.paper_sim.service import get_paper_engine
    from backend.services.feed_health import get_feed_sources
    from backend.services.learning_service import get_learning_service
```

```python
    breaker_dicts = [b.as_dict() for b in breakers]
    active = active_breaker_ids(breakers)
```

```python
    return {
        "as_of": _now().isoformat(),
        "equity_inr": round(equity, 2),
        "starting_capital_inr": round(starting, 2),
        "reserved_margin_inr": round(float(account.reserved_margin_inr), 2),
        "cash_inr": round(float(account.cash_inr), 2),
        "realized_pnl": round(float(account.realized_pnl), 2),
        "unrealized_pnl": round(float(account.unrealized_pnl), 2),
        "session_pnl": round(session_pnl, 2),
        "daily_pnl": round(session_pnl, 2),
        "drawdown_pct": round(drawdown, 2),
        "win_rate": round(float(win_rate), 4),
        "open_positions": int(account.open_positions),
        "portfolio_greeks": greeks,
        "greek_limits": greek_rows,
        "greeks_within_limits": bool(greek_check.passed),
        "greeks_failures": list(greek_check.failures),
        "circuit_breakers": breaker_dicts,
        "circuit_breakers_active": active,
        "feed_age_sec": feed_age,
        "events": _risk_events(
            breakers=breaker_dicts,
            freeze_reason=learning.freeze_reason,
            greeks_passed=bool(greek_check.passed),
            account_updated_at=account.updated_at,
            open_positions=int(account.open_positions),
        ),
        "shared_kill_conditions": list(SHARED_KILL_CONDITIONS),
        "limits": {
            "max_drawdown_pct": thr.max_drawdown_pct,
            "max_daily_loss_pct": thr.max_daily_loss_pct,
            "max_consecutive_losses": thr.max_consecutive_losses,
            "quote_stale_threshold_sec": thr.quote_stale_threshold_sec,
            "max_abs_total_delta": greek_thr.max_abs_total_delta,
            "max_abs_total_gamma": greek_thr.max_abs_total_gamma,
            "max_abs_total_vega": greek_thr.max_abs_total_vega,
            "min_total_theta": greek_thr.min_total_theta,
        },
    }
```

And in `bot_metrics_from_risk()`, no change needed (it doesn't touch
`kill_switch_armed` directly — it forwards `circuit_breakers_active`, which
now simply never contains `"kill_switch"`).

- [ ] **Step 4: Run the full backend test suite**

Run: `pytest backend/ -m "not integration" -v`
Expected: All PASS. Specifically confirm:
`pytest backend/tests/test_risk_gate.py backend/tests/test_automation.py backend/tests/test_phase0.py -v`

- [ ] **Step 5: Commit**

```bash
git add -A backend/services/kill_switch_state.py backend/routers/bot.py backend/execution/risk_gate.py backend/execution/circuit_breakers.py backend/paper_sim/engine.py backend/paper_sim/automation.py backend/services/risk_snapshot.py backend/tests/test_kill_switch_state.py backend/tests/test_risk_gate.py backend/tests/test_automation.py backend/tests/test_phase0.py backend/tests/conftest.py
git commit -m "Remove the global manual Kill Switch (state, risk-gate, pause/resume) from the backend"
```

---

### Task 8: Delete the global manual Kill Switch — frontend

**Files:**
- Modify: `frontend/src/components/dashboard/situational-bar.tsx`
- Modify: `frontend/src/app/dashboard/page.tsx`
- Modify: `frontend/src/app/risk/page.tsx`
- Modify: `frontend/src/types/decisions.ts`
- Modify: `frontend/src/types/risk.ts`
- Modify: `frontend/src/lib/mock-data.ts`
- Modify: `frontend/src/lib/risk-mock.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/app/globals.css`
- Modify: `frontend/src/components/dashboard/kill-conditions.tsx`

**Interfaces:**
- Consumes: backend responses with no `kill_switch_armed` field (Task 7).
- Produces: no component references `kill_switch_armed`, `pauseBot`,
  `resumeBot`, or `.kill-switch-glow`.

- [ ] **Step 1: `frontend/src/lib/api.ts` — remove `pauseBot`/`resumeBot`**

Delete the `pauseBot` and `resumeBot` exported functions entirely (the block
shown at lines 182-197 in the current file).

- [ ] **Step 2: `frontend/src/components/dashboard/situational-bar.tsx` — remove the Kill Switch button**

Replace the file's `SituationalBar` function so it no longer imports
`pauseBot`/`resumeBot`, tracks `armed` state, or renders the button:

```tsx
"use client";

import { useEffect, useState } from "react";
import { getMarketIndices } from "@/lib/api";
import { formatGreek, formatCurrency, formatPct } from "@/lib/utils";
import type { BotStatus } from "@/types/decisions";
import type { IndexMark } from "@/types/market";
import { Icon, StatusPill } from "@/components/ui/primitives";

interface SituationalBarProps {
  status: BotStatus;
}

const INDEX_POLL_MS = 15_000;

/**
 * Persistent "Global Metrics" command bar (Stitch: topbar-height 64px).
 * Market-wide metrics + bot state on the left.
 * NIFTY / INDIA VIX come from GET /api/v1/market/indices (ICICI Direct quotes).
 */
export function SituationalBar({ status }: SituationalBarProps) {
  const [indices, setIndices] = useState<IndexMark[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await getMarketIndices();
        if (!cancelled) setIndices(data.indices ?? []);
      } catch {
        if (!cancelled) setIndices([]);
      }
    }

    void load();
    const id = setInterval(() => void load(), INDEX_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const breakers = status.circuit_breakers_active;

  const nifty = indices.find((m) => m.stock_code === "NIFTY") ?? indices[0];
  const vix =
    indices.find((m) => m.stock_code === "INDVIX") ??
    indices.find((m) => m.label.toUpperCase().includes("VIX")) ??
    indices[1];

  return (
    <header className="sticky top-0 z-40 border-b border-outline-variant bg-surface/95 backdrop-blur">
      <div className="flex h-topbar-height items-center justify-between gap-4 px-6">
        <div className="flex min-w-0 items-center gap-4">
          <Icon name="security" className="shrink-0 text-primary" />
          <h1 className="hidden text-headline-md font-bold text-primary sm:block">
            Global Metrics
          </h1>

          <div className="ml-2 flex items-center gap-6 border-l border-outline-variant pl-6">
            <GlobalMetric mark={nifty} fallbackLabel="NIFTY 50" />
            <GlobalMetric mark={vix} fallbackLabel="INDIA VIX" />
          </div>

          <div className="ml-2 hidden items-center gap-3 border-l border-outline-variant pl-6 lg:flex">
            <StatusPill
              tone={
                status.execution_mode === "paper"
                  ? "success"
                  : status.execution_mode === "live"
                    ? "danger"
                    : "neutral"
              }
            >
              {status.execution_mode}
            </StatusPill>
            {status.supervision_mode && (
              <StatusPill tone="neutral">{status.supervision_mode}</StatusPill>
            )}
            <StatusPill
              tone={status.scheduler_mode === "paused" ? "warning" : "success"}
            >
              {status.scheduler_mode}
            </StatusPill>
            {status.one_trade_locked && (
              <StatusPill tone="warning">One-trade locked</StatusPill>
            )}
          </div>
        </div>

        <div className="flex items-center gap-6">
          <div className="hidden items-center gap-5 xl:flex">
            <Metric
              label="Daily P&L"
              value={formatCurrency(status.daily_pnl)}
              positive={status.daily_pnl >= 0}
            />
            <Metric label="Win rate" value={formatPct(status.win_rate)} />
            <Metric
              label="Drawdown"
              value={`${status.drawdown_pct.toFixed(1)}%`}
              warn={status.drawdown_pct > 5}
            />
            <GreekStrip greeks={status.portfolio_greeks} />
          </div>
        </div>
      </div>

      {breakers.length > 0 && (
        <div className="flex items-center gap-2 border-t border-error/30 bg-error/10 px-6 py-2 text-data-sm text-error">
          <Icon name="warning" className="text-[16px]" />
          Active breakers: {breakers.join(", ")}
        </div>
      )}
    </header>
  );
}
```

(Keep the rest of the file — `formatIndexValue`, `formatChange`,
`GlobalMetric`, `Metric`, `GreekStrip`, `CountdownTimer` — unchanged below
this point.)

- [ ] **Step 3: `frontend/src/app/dashboard/page.tsx` — remove the "Kill Switch Status" stat card**

Remove `const killArmed = Boolean(status.kill_switch_armed);` (line 36) and
the `StatCard` block (lines 77-82):

```tsx
          <section className="grid grid-cols-1 gap-gutter md:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Execution Mode"
              value={status.execution_mode.toUpperCase()}
              tone={mode === "paper" ? "success" : mode === "live" ? "danger" : "warning"}
              pill={executionPill}
            />
            <StatCard
              label="Supervision"
              value={supervision.toUpperCase()}
              pill={{ tone: "warning", text: "MANUAL" }}
            />
            <StatCard
              label="Scheduler"
              value={status.scheduler_mode.toUpperCase()}
              pill={{
                tone: status.scheduler_mode === "paused" ? "warning" : "success",
                text: status.scheduler_mode === "paused" ? "PAUSED" : "ACTIVE",
              }}
            />
          </section>
```

(3-column grid content now — leave `md:grid-cols-2 lg:grid-cols-4` as-is;
it'll just render one fewer card, which is fine for this grid.)

- [ ] **Step 4: `frontend/src/app/risk/page.tsx` — remove `kill_switch_armed` from `activeTone`**

Change:

```tsx
  const activeTone =
    risk.circuit_breakers_active.length === 0
      ? "success"
      : risk.circuit_breakers.some((b) => b.tone === "danger") ||
          risk.kill_switch_armed
        ? "danger"
        : "warning";
```

to:

```tsx
  const activeTone =
    risk.circuit_breakers_active.length === 0
      ? "success"
      : risk.circuit_breakers.some((b) => b.tone === "danger")
        ? "danger"
        : "warning";
```

- [ ] **Step 5: Update the TypeScript DTOs**

In `frontend/src/types/decisions.ts`, remove `kill_switch_armed?: boolean;`
from `BotStatus` (line 127).

In `frontend/src/types/risk.ts`, remove `kill_switch_armed: boolean;` from
`RiskSnapshot` (line 55).

- [ ] **Step 6: Update mock data**

In `frontend/src/lib/mock-data.ts`, remove `kill_switch_armed: false,`
(line 25) and remove the `{ id: "kill_switch", label: "Kill-switch
inactive", status: "pass" },` gate entry (line 125).

In `frontend/src/lib/risk-mock.ts`, remove `kill_switch_armed: false,`
(line 73).

- [ ] **Step 7: Remove the CSS rule**

In `frontend/src/app/globals.css`, remove the `.kill-switch-glow` rule and
its comment (lines 49-53):

```css
@layer utilities {
}
```

(If the `@layer utilities { }` block becomes empty and there's nothing else
in it, remove the empty block too — check the surrounding lines before
deleting to confirm nothing else shares that block.)

- [ ] **Step 8: Update `kill-conditions.tsx`'s default list**

In `frontend/src/components/dashboard/kill-conditions.tsx`, remove the
earnings/news line from `DEFAULT_KILL_CONDITIONS` (line 35) so it matches
the updated `Docs/Trading_Strategies.md` (Task 9):

```tsx
const DEFAULT_KILL_CONDITIONS = [
  "liquidity collapses or spreads blow out beyond limits",
  "a hedge leg becomes unavailable",
  "the model input is stale or clearly corrupted",
  "required neutrality cannot be restored within cost limits",
  "residual delta or vega exposure exceeds portfolio limits",
  "the strategy's core assumption no longer holds",
];
```

(This component — `KillConditions`/`SharedKillConditions` — displays the
*other*, still-standing Shared Kill Conditions list; it is not the manual
Kill Switch and is out of scope to rename or remove.)

- [ ] **Step 9: Typecheck/build the frontend**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no TypeScript errors referencing
`kill_switch_armed`, `pauseBot`, or `resumeBot`.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/dashboard/situational-bar.tsx frontend/src/app/dashboard/page.tsx frontend/src/app/risk/page.tsx frontend/src/types/decisions.ts frontend/src/types/risk.ts frontend/src/lib/mock-data.ts frontend/src/lib/risk-mock.ts frontend/src/lib/api.ts frontend/src/app/globals.css frontend/src/components/dashboard/kill-conditions.tsx
git commit -m "Remove Kill Switch UI (button, status card, breaker text) from the frontend"
```

---

### Task 9: Docs and config consistency

**Files:**
- Modify: `Docs/Trading_Strategies.md`
- Modify: `backend/schemas/trading_parameters.schema.json`
- Modify: `backend/config/trading_parameters.defaults.json`
- Modify: `CLAUDE.md`
- Modify: `Docs/bot_health/BACKLOG.md`

**Interfaces:**
- Consumes: nothing (docs/config only, no code paths read these strings at
  runtime).
- Produces: project docs consistent with the removed mechanisms — no test
  depends on this task, but Task 10's grep sweep checks it.

- [ ] **Step 1: `Docs/Trading_Strategies.md` — Shared Kill Conditions bullet**

Remove the line `- an earnings or news event appears that the setup was not
designed to absorb` from the `### Shared Kill Conditions` list (around line
155).

- [ ] **Step 2: `Docs/Trading_Strategies.md` — SH-4 news-overlay table rows**

In the "News / event flag (from Market_News) | Effect on SH-4 row" table
(around lines 1317-1323), update the two affected rows:

```markdown
| News / event flag (from Market_News) | Effect on SH-4 row |
|---|---|
| No adverse event; normal tone | Allow cheap-vol / normal-regime row |
| Earnings or company event imminent | Force earnings-gap row; block plain long-vega through event |
| Crisis / post-shock tone | Tag bearish + macro flag; route through early_exit like any adverse tone — no automated hard block |
| Breaking news after long-vol entry | Prefer take-profit / aggressive re-hedge (do not widen stops) |
```

(Drop the old "Unplanned news the setup was not designed for | Shared Kill →
abort or flatten" row entirely — that mechanism no longer exists.)

Also update the "Hard constraints extracted from the sources" bullet list
(around line 1335) if it mentions Shared Kill by name in a way that implies
an automated news-driven kill still exists — check the exact wording at
that line and adjust only if it does; the listed hard constraints there
(never short vol, never `<10 DTE`, IV(long)<IV(short) block, earnings-hold
block, 3pp IV-drop exit, same-session vega flatten) are unrelated to this
change and must not be touched.

- [ ] **Step 3: `trading_parameters.schema.json` + `.defaults.json`**

In `backend/schemas/trading_parameters.schema.json`, remove
`"kill_event": { "type": "boolean" },` from the `kill_conditions` properties
block (line 624).

In `backend/config/trading_parameters.defaults.json`, remove
`"kill_event": false,` from the `kill_conditions` object (line 214).

- [ ] **Step 4: `CLAUDE.md` P0 bullet**

Change line 73:

```markdown
- **P0**: wire recommend → supervised approve → `paper_sim` → learning as one real ledger (no fills outside `paper_sim`); enforce breakers/market-hours durably (survives restart, not dashboard-only).
```

(drops "/kill-switch" from "breakers/market-hours/kill-switch"; keeps
breakers and market-hours enforcement as still-required P0 items.)

- [ ] **Step 5: `Docs/bot_health/BACKLOG.md` — supersede the resolved item**

Find the resolved item at lines 67-77 ("Kill-switch armed state was an
in-memory global..."). Append a new line directly after its existing
`resolved 2026-08-04, evidence: ...` sentence, on its own line within the
same bullet, without deleting the original text:

```markdown
  **Superseded 2026-08-05:** the kill-switch mechanism itself (this
  persisted-state fix included) was removed entirely per operator decision —
  the bot now has no manual kill switch. See
  `Docs/superpowers/specs/2026-08-05-market-news-quality-killswitch-removal-design.md`.
```

- [ ] **Step 6: Commit**

```bash
git add Docs/Trading_Strategies.md backend/schemas/trading_parameters.schema.json backend/config/trading_parameters.defaults.json CLAUDE.md Docs/bot_health/BACKLOG.md
git commit -m "Update docs/config for kill_event and kill-switch removal"
```

---

### Task 10: Final verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Grep sweep for orphaned references**

Run: `grep -rniE "kill_switch|kill_event|killswitch" backend/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx"`
Expected: Zero matches. (`Market_News.txt`, `Docs/`, and this plan/spec are
outside these two directories and are allowed to still mention the concept
historically/descriptively.)

- [ ] **Step 2: Full backend test suite**

Run: `pytest -m "not integration" -v`
Expected: All PASS, zero errors, zero skips beyond pre-existing
`integration`-marked exclusions.

- [ ] **Step 3: Frontend build**

Run: `cd frontend && npm run build`
Expected: Success, no TypeScript errors.

- [ ] **Step 4: Manual spot-check of `Market_News.txt` contract parsing**

Run: `python -c "from backend.services.market_news.curation import load_curation_contract; c = load_curation_contract(); print(c.bot_priority); print(c.loaded)"`
Expected: prints the 7-tuple in tier order and `True`.

- [ ] **Step 5: Final commit (only if any of the above required fixes)**

```bash
git add -A
git commit -m "Fix remaining references found in final kill-switch removal sweep"
```

(Skip this step if Steps 1-4 all passed clean with nothing to fix.)
