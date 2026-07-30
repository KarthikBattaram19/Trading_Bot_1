import type { AutonomousExecutionResult } from "@/types/trades";
import type { LearningInsight } from "@/types/learning";

export type StrategyType =
  | "simple_volatility"
  | "gamma_scalping"
  | "vega_scalping"
  | "blocked";

export type FeedSourceStatus = "active" | "unavailable" | "stub";
export type FeedHealth = "fresh" | "stale" | "error";

export interface GateResult {
  gate_id: string;
  label: string;
  passed: boolean;
  detail?: string;
  parameter_ref?: string;
}

export interface NewsItem {
  title: string;
  summary: string;
  source: string;
  time_published: string;
  sentiment_label: string;
  sentiment_score: number;
  tickers: string[];
  topics: string[];
  relevance_to_trade?: string;
}

export interface FeedSource {
  source_id: string;
  source_name: string;
  status: FeedSourceStatus;
  capabilities: string[];
  last_fetch_at?: string;
  health: FeedHealth;
  detail?: string;
}

export interface ParameterSnapshot {
  und_price: number;
  iv_annualized: number;
  garch_forecast: number;
  iv_z_score?: number;
  days_to_earnings?: number;
  atm_premium_inr: number;
  volume: number;
  open_interest: number;
  spread_pct: number;
  dte: number;
  realized_vol_intraday?: number;
  garch_distorted: boolean;
}

export interface StrategySelectionLogic {
  selected_strategy: StrategyType;
  entry_mode?: string;
  scenario_tag: string;
  cross_strategy_matrix_ref: string;
  primary_signal: string;
  rejected_strategies: string[];
  news_impact?: string;
}

/** Transparent ranking components for insight packets. */
export interface ScoreBreakdown {
  base: number;
  strategy_boost: number;
  liquidity_boost: number;
  spread_penalty: number;
  failure_memory_penalty?: number;
  module_weight_factor?: number;
  total: number;
  components: string[];
}

/** P1.5 — hedge construction at recommendation stage. */
export interface HedgeInsight {
  method: string;
  greek_targets: string;
  structure_note: string;
}

/** P1.6 — size & margin within retail INR caps. */
export interface TradeEconomicsInsight {
  margin_estimate_inr: number;
  max_trade_budget_inr: number;
  atm_premium_inr: number;
  estimated_slippage_pct: number;
  net_edge_note: string;
}

/**
 * Complete operator insight packet for one ranked trade.
 * Aligns with Trading_Parameters.md P1 + ranking transparency.
 */
export interface InstrumentRecommendation {
  rank: number;
  underlying_symbol: string;
  score: number;
  confidence: number;
  strategy: StrategySelectionLogic;
  parameters: ParameterSnapshot;
  parameter_gates: GateResult[];
  market_summary: string;
  entry_rationale: string;
  complete_logic: string[];
  score_breakdown: ScoreBreakdown;
  hedge: HedgeInsight;
  economics: TradeEconomicsInsight;
  exit_plan: string;
  event_risks: string[];
  failure_modes: string[];
  why_this_rank: string;
  alternative_considered?: string;
  insight_checklist: string[];
  /** Continual learning overlay (§12) — failure memory + module stats */
  learning?: LearningInsight | null;
}

export interface MarketNewsSummary {
  headline_count: number;
  dominant_sentiment: string;
  earnings_mentions: number;
  macro_risk_flags: string[];
  interpretation: string;
  items: NewsItem[];
}

export interface RecommendationResponse {
  generated_at: string;
  feed_as_of: string;
  feed_sources: FeedSource[];
  market_news: MarketNewsSummary;
  universe_scanned: number;
  candidates_passing_gates: number;
  recommendations: InstrumentRecommendation[];
  analysis_notes: string[];
  /** Ranked fallback execution result from the same request cycle */
  autonomous_execution?: AutonomousExecutionResult | null;
}

export const STRATEGY_TYPE_LABELS: Record<StrategyType, string> = {
  simple_volatility: "Simple Volatility",
  gamma_scalping: "Gamma Scalping",
  vega_scalping: "Vega Scalping",
  blocked: "Blocked",
};

export const ENTRY_MODE_LABELS: Record<string, string> = {
  cheap_vol_mode: "Cheap Vol",
  earnings_gap_mode: "Earnings Gap",
  high_realized_vol_mode: "High Realized Vol",
  standard: "Standard",
};
