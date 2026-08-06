"""
Table SH-4 strategy selection with Market_News overlay.

Authority: Docs/Trading_Strategies.md Table SH-4 + Architecture §8.8.4.
Quant signals (IV vs GARCH, IV z-score, RV, earnings calendar) remain primary;
news gates and prefers rows (kill / prefer). Used by recommendation_engine and
paper-sim ``POST /strategies/select``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from backend.models.recommendations import (
    MarketNewsSummary,
    StrategySelectionLogic,
    StrategyType,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "trading_parameters.defaults.json"

RecommendationAction = Literal[
    "enter_long_vol",
    "enter_gamma",
    "enter_vega",
    "stand_aside",
    "blocked",
]

PostEntryAction = Literal[
    "none",
    "take_profit",
    "rehedge_aggressive",
    "early_exit",
]


@dataclass(frozen=True)
class QuantRegimeInputs:
    """Quant inputs that cross with Market_News for SH-4 selection."""

    symbol: str
    iv_annualized: float
    garch_forecast: float
    iv_z_score: float | None = None
    days_to_earnings: int | None = None
    realized_vol_intraday: float | None = None
    garch_distorted: bool = False


def load_trading_config() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def recommendation_action(strategy: StrategySelectionLogic) -> RecommendationAction:
    """Map SH-4 selection to paper-sim /signals recommendation verb."""
    st = strategy.selected_strategy
    if st == StrategyType.blocked:
        return "blocked"
    if st == StrategyType.vega_scalping:
        return "enter_vega"
    if st == StrategyType.gamma_scalping:
        return "enter_gamma"
    if st == StrategyType.simple_volatility:
        return "enter_long_vol"
    return "stand_aside"


def _macro_flags_lower(news: MarketNewsSummary) -> str:
    return " ".join(news.macro_risk_flags).lower()


def _topics_lower(news: MarketNewsSummary) -> set[str]:
    return {t.lower() for t in news.topics}


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


def news_confirms_agitation(news: MarketNewsSummary) -> bool:
    flags = _macro_flags_lower(news)
    return (
        news.dominant_tone == "bearish"
        or "macro_agitation" in flags
        or "agitation" in flags
    )


def earnings_or_company_event(
    quant: QuantRegimeInputs,
    news: MarketNewsSummary,
) -> bool:
    """Calendar or Market_News earnings / company-event imminent (SH-4 earnings-gap row)."""
    if quant.days_to_earnings is not None and quant.days_to_earnings <= 1:
        return True
    if news.news_event_imminent:
        return True
    topics = _topics_lower(news)
    if "earnings" in topics or "corporate_action" in topics:
        # Symbol-tagged event for this underlying, or elevated packet-wide coverage.
        sym = quant.symbol.upper()
        if sym in {s.upper() for s in news.symbol_tags}:
            return True
        if news.earnings_mentions >= 1 and sym in _symbols_from_items(news):
            return True
        # Broad elevated earnings season without a clean cheap-vol path still prefers gamma.
        if "elevated_earnings_coverage" in _macro_flags_lower(news):
            return True
    return False


def _symbols_from_items(news: MarketNewsSummary) -> set[str]:
    out: set[str] = set()
    for item in news.items:
        out.update(t.upper() for t in item.tickers)
        title_u = item.title.upper()
        for tag in news.symbol_tags:
            if tag.upper() in title_u:
                out.add(tag.upper())
    out.update(s.upper() for s in news.symbol_tags)
    return out


def symbol_has_adverse_news(symbol: str, news: MarketNewsSummary) -> bool:
    """Symbol-tagged adverse / bearish item — prefer reduce / flatten (N-07)."""
    sym = symbol.upper()
    for item in news.items:
        hit = sym in {t.upper() for t in item.tickers} or sym in item.title.upper()
        if hit and item.sentiment_label.lower() in {
            "bearish",
            "somewhat-bearish",
        }:
            return True
        if hit and item.sentiment_score < -0.15:
            return True
    return False


def news_impact_for_symbol(symbol: str, news: MarketNewsSummary) -> str | None:
    for item in news.items:
        if symbol.upper() in {t.upper() for t in item.tickers} or symbol.upper() in item.title.upper():
            return f"{item.sentiment_label}: {item.title[:80]}"
    if news.news_impact and news.news_impact != "none":
        return f"packet news_impact={news.news_impact}"
    return None


def select_strategy_sh4(
    quant: QuantRegimeInputs,
    news: MarketNewsSummary,
    cfg: dict[str, Any] | None = None,
    *,
    available_strategies: set[StrategyType] | None = None,
) -> StrategySelectionLogic:
    """Cross-strategy decision matrix — Trading_Strategies.md Table SH-4 + news overlay.

    ``available_strategies`` restricts which strategies may be selected this cycle
    (coverage gate). ``None`` means all strategies are allowed.
    """
    cfg = cfg or load_trading_config()
    rejected: list[str] = []

    def _allowed(st: StrategyType) -> bool:
        if st == StrategyType.blocked:
            return True
        if available_strategies is None:
            return True
        return st in available_strategies

    def _coverage_reject(st: StrategyType) -> None:
        rejected.append(f"{st.value} — strategy_coverage_abort")

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

    if available_strategies is not None and not available_strategies:
        return StrategySelectionLogic(
            selected_strategy=StrategyType.blocked,
            scenario_tag="Strategy coverage abort — no strategies published",
            cross_strategy_matrix_ref="Table SH-4 / strategy_coverage gate",
            primary_signal="strategy_coverage_abort: no available strategies",
            rejected_strategies=[
                "simple_volatility — strategy_coverage_abort",
                "gamma_scalping — strategy_coverage_abort",
                "vega_scalping — strategy_coverage_abort",
            ],
            news_impact=news_impact_for_symbol(quant.symbol, news),
        )

    event_imminent = earnings_or_company_event(quant, news)
    vega_cfg = cfg["strategies"]["vega_scalping"]["iv_signal"]
    z_thresh = float(vega_cfg["entry_z_threshold"])
    iv_flush = quant.iv_z_score is not None and quant.iv_z_score <= z_thresh

    # --- Earnings / company event → prefer gamma; kill plain long-vega (N-02) ---
    if event_imminent:
        rejected.append("simple_volatility — plain long-vega through event (SH-4 Avoid)")
        if iv_flush:
            rejected.append(
                "vega_scalping — earnings/event overrides IV flush (news overlay)"
            )
        if _allowed(StrategyType.gamma_scalping):
            cal = (
                f"days_to_earnings={quant.days_to_earnings}"
                if quant.days_to_earnings is not None and quant.days_to_earnings <= 1
                else "news_event_imminent / earnings topic"
            )
            return StrategySelectionLogic(
                selected_strategy=StrategyType.gamma_scalping,
                entry_mode="earnings_gap_mode",
                scenario_tag="Scenario A: Earnings Gap",
                cross_strategy_matrix_ref="Table SH-4: Earnings gap → Gamma scalping",
                primary_signal=cal,
                rejected_strategies=rejected,
                news_impact=(
                    news_impact_for_symbol(quant.symbol, news)
                    or "Earnings/company event — prefer gamma earnings_gap_mode"
                ),
            )
        _coverage_reject(StrategyType.gamma_scalping)

    # --- Vega only when IV flush AND news not blocking (N-12) ---
    if iv_flush:
        if not news.news_not_blocking:
            rejected.append(
                "vega_scalping — IV z ≤ threshold but news_not_blocking=false (N-12)"
            )
            # Fall through to other rows; do not enter vega.
        elif _allowed(StrategyType.vega_scalping):
            rejected.append("simple_volatility — intraday IV flush favors vega scalp (SH-4)")
            rejected.append("gamma_scalping — no earnings/high-RV override")
            return StrategySelectionLogic(
                selected_strategy=StrategyType.vega_scalping,
                entry_mode="standard",
                scenario_tag="Scenario A: Clean Intraday IV Flush",
                cross_strategy_matrix_ref="Table SH-4: Intraday IV −2σ → Vega scalping",
                primary_signal=f"iv_z_score={quant.iv_z_score:.2f} ≤ {z_thresh}",
                rejected_strategies=rejected,
                news_impact=news_impact_for_symbol(quant.symbol, news),
            )
        else:
            _coverage_reject(StrategyType.vega_scalping)

    gamma_entry_cfg = cfg["strategies"]["gamma_scalping"]["entry_signal"]
    high_rv_thresh = float(gamma_entry_cfg["high_realized_vol_intraday_threshold"])
    iv_elevated_multiplier = float(gamma_entry_cfg["iv_elevated_vs_garch_multiplier"])

    cheap_vol = quant.iv_annualized < quant.garch_forecast
    high_rv = (
        quant.realized_vol_intraday is not None
        and quant.realized_vol_intraday > high_rv_thresh
    )
    iv_elevated = quant.iv_annualized > quant.garch_forecast * iv_elevated_multiplier
    agitation = news_confirms_agitation(news)

    # --- IV high + large realized moves (+ news agitation confirm) → gamma ---
    if iv_elevated and high_rv:
        rejected.append("simple_volatility — IV already rich vs GARCH")
        if _allowed(StrategyType.gamma_scalping):
            return StrategySelectionLogic(
                selected_strategy=StrategyType.gamma_scalping,
                entry_mode="high_realized_vol_mode",
                scenario_tag="Scenario B: High Volatility, Big Intraday Swings",
                cross_strategy_matrix_ref="Table SH-4: IV high + large realized moves → Gamma",
                primary_signal=(
                    f"IV={quant.iv_annualized:.1%} > GARCH; "
                    f"RV={quant.realized_vol_intraday:.1%}"
                    + ("; news confirms agitation" if agitation else "")
                ),
                rejected_strategies=rejected,
                news_impact=news_impact_for_symbol(quant.symbol, news),
            )
        _coverage_reject(StrategyType.gamma_scalping)

    # --- Adverse symbol news without designed event → stand aside / kill prefer ---
    if symbol_has_adverse_news(quant.symbol, news) and not news.news_not_blocking:
        rejected.extend(
            [
                "simple_volatility — adverse symbol news blocks cheap-vol row",
                "vega_scalping — news blocking",
                "gamma_scalping — unplanned adverse news (prefer flatten / defer)",
            ]
        )
        return StrategySelectionLogic(
            selected_strategy=StrategyType.blocked,
            scenario_tag="Unplanned adverse symbol news",
            cross_strategy_matrix_ref="Table SH-4 / Shared Kill — unplanned news",
            primary_signal=f"adverse news tagged {quant.symbol}",
            rejected_strategies=rejected,
            news_impact=news_impact_for_symbol(quant.symbol, news)
            or "Symbol-tagged adverse news — defer entry",
        )

    # --- Normal cheap-vol row requires no adverse news (U4) ---
    if cheap_vol:
        if not news.news_not_blocking:
            rejected.append(
                "simple_volatility — IV < GARCH but news_not_blocking=false"
            )
            rejected.append("vega_scalping — no clean news-cleared IV flush")
            if _allowed(StrategyType.gamma_scalping):
                return StrategySelectionLogic(
                    selected_strategy=StrategyType.gamma_scalping,
                    entry_mode="cheap_vol_mode",
                    scenario_tag="News overlay — defer plain long-vega; gamma if path uncertain",
                    cross_strategy_matrix_ref="Table SH-4: news gates cheap-vol row",
                    primary_signal=(
                        f"IV={quant.iv_annualized:.1%} < GARCH={quant.garch_forecast:.1%} "
                        "but news blocking — gamma preferred"
                    ),
                    rejected_strategies=rejected,
                    news_impact=news_impact_for_symbol(quant.symbol, news)
                    or "news_not_blocking=false",
                )
            _coverage_reject(StrategyType.gamma_scalping)
        else:
            rejected.append("vega_scalping — no intraday −2σ IV signal (or news blocked)")
            if _allowed(StrategyType.simple_volatility):
                return StrategySelectionLogic(
                    selected_strategy=StrategyType.simple_volatility,
                    entry_mode="cheap_vol_mode",
                    scenario_tag="Scenario A: Normal Cheap-Vol Setup",
                    cross_strategy_matrix_ref="Table SH-4: IV < GARCH → Simple vol (1st choice)",
                    primary_signal=(
                        f"IV={quant.iv_annualized:.1%} < GARCH={quant.garch_forecast:.1%}"
                    ),
                    rejected_strategies=rejected,
                    news_impact=news_impact_for_symbol(quant.symbol, news),
                )
            _coverage_reject(StrategyType.simple_volatility)
            if _allowed(StrategyType.gamma_scalping):
                return StrategySelectionLogic(
                    selected_strategy=StrategyType.gamma_scalping,
                    entry_mode="cheap_vol_mode",
                    scenario_tag="IV path uncertain — gamma preferred over plain long-vega",
                    cross_strategy_matrix_ref=(
                        "Table SH-4: Simple vol 2nd → Gamma if IV path uncertain"
                    ),
                    primary_signal=(
                        "simple_volatility coverage abort; gamma as hedge to IV direction"
                    ),
                    rejected_strategies=rejected,
                    news_impact=news_impact_for_symbol(quant.symbol, news),
                )
            _coverage_reject(StrategyType.gamma_scalping)

    # --- IV path uncertain — gamma second choice ---
    rejected.append("vega_scalping — IV not 2σ below intraday mean (or news blocked)")
    rejected.append("simple_volatility — IV not cheap vs GARCH")
    if _allowed(StrategyType.gamma_scalping):
        return StrategySelectionLogic(
            selected_strategy=StrategyType.gamma_scalping,
            entry_mode="cheap_vol_mode",
            scenario_tag="IV path uncertain — gamma preferred over plain long-vega",
            cross_strategy_matrix_ref="Table SH-4: Simple vol 2nd → Gamma if IV path uncertain",
            primary_signal=(
                "No clean cheap-vol or vega-scalp signal; gamma as hedge to IV direction"
            ),
            rejected_strategies=rejected,
            news_impact=news_impact_for_symbol(quant.symbol, news),
        )
    _coverage_reject(StrategyType.gamma_scalping)
    return StrategySelectionLogic(
        selected_strategy=StrategyType.blocked,
        scenario_tag="Strategy coverage abort — no remaining strategy",
        cross_strategy_matrix_ref="Table SH-4 / strategy_coverage gate",
        primary_signal="strategy_coverage_abort: no remaining strategy",
        rejected_strategies=rejected,
        news_impact=news_impact_for_symbol(quant.symbol, news),
    )


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


def select_strategy_packet(
    quant: QuantRegimeInputs,
    news: MarketNewsSummary,
    cfg: dict[str, Any] | None = None,
    *,
    setup_designed_for_event: bool = False,
    position_open: bool = False,
) -> dict[str, Any]:
    """SH-4 selection plus recommendation verb and optional post-entry action."""
    strategy = select_strategy_sh4(quant, news, cfg)
    action = recommendation_action(strategy)
    post = post_entry_news_action(
        news,
        setup_designed_for_event=setup_designed_for_event,
        position_open=position_open,
    )
    return {
        "selected_strategy": strategy.selected_strategy.value,
        "entry_mode": strategy.entry_mode,
        "scenario_tag": strategy.scenario_tag,
        "cross_strategy_matrix_ref": strategy.cross_strategy_matrix_ref,
        "primary_signal": strategy.primary_signal,
        "rejected_strategies": strategy.rejected_strategies,
        "news_impact": strategy.news_impact,
        "recommendation": action if action != "blocked" else "stand_aside",
        "post_entry_action": post,
        "strategy": strategy.model_dump(mode="json"),
        "market_news": {
            "dominant_tone": news.dominant_tone,
            "topics": news.topics,
            "symbol_tags": news.symbol_tags,
            "macro_risk_flags": news.macro_risk_flags,
            "news_not_blocking": news.news_not_blocking,
            "news_event_imminent": news.news_event_imminent,
            "news_post_shock": news.news_post_shock,
            "news_impact": news.news_impact,
        },
    }
