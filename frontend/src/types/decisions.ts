export type StrategyModule =
  | "stat_arb"
  | "volatility"
  | "gamma_scalping"
  | "vega_scalping";

export type EntryMode =
  | "standard"
  | "cheap_vol_mode"
  | "earnings_gap_mode"
  | "high_realized_vol_mode";

export type DecisionStatus = "pending" | "approved" | "rejected" | "expired";

export type GateStatus = "pass" | "fail" | "warn";

export interface RagCitation {
  document: string;
  chapter?: string;
  page?: number;
}

export interface OptionLeg {
  leg_id: number;
  type: "call" | "put" | "stock";
  position: number;
  strike?: number;
  expiration?: string;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  mid_price?: number;
}

export interface GreeksTotals {
  total_delta: number;
  total_gamma: number;
  total_theta: number;
  total_vega: number;
}

export interface TradeEconomics {
  net_edge_after_costs: number;
  margin_estimate: number;
  expected_gamma_pnl: number;
  expected_theta_loss: number;
  total_transaction_cost: number;
  slippage_cap_bps: number;
}

export interface TradePlan {
  stop: string;
  target: string;
  time_exit: string;
}

export interface RiskGate {
  id: string;
  label: string;
  status: GateStatus;
  detail?: string;
}

export interface StrategyContext {
  /** Stat arb */
  residual_z_score?: number;
  hedge_ratio?: number;
  half_life_days?: number;
  cointegrated_windows?: number;
  economics_aligned?: boolean;
  pair_y?: string;
  pair_x?: string;
  /** Volatility */
  iv_annualized?: number;
  garch_forecast?: number;
  gamma_theta_breakeven_pct?: number;
  /** Gamma */
  entry_mode?: EntryMode;
  term_structure_ok?: boolean;
  vega_neutral_at_entry?: boolean;
  /** Vega */
  intraday_iv_z_score?: number;
  must_flatten_same_day?: boolean;
}

export interface PendingDecision {
  decision_id: string;
  signal_id: string;
  status: DecisionStatus;
  module: StrategyModule;
  underlying_symbol: string;
  confidence: number;
  regime: string;
  explanation: string;
  rationale: string;
  rag_citations: RagCitation[];
  legs: OptionLeg[];
  totals: GreeksTotals;
  economics: TradeEconomics;
  plan: TradePlan;
  event_risks: string[];
  failure_modes: string[];
  strategy_context: StrategyContext;
  risk_gates: RiskGate[];
  created_at: string;
  expires_at: string;
  scenario_tag?: string;
  alternative_strategies?: string[];
}

export interface BotStatus {
  execution_mode: "shadow" | "paper" | "live";
  supervision_mode?: "supervised" | "semi_autonomous" | "fully_autonomous";
  autonomy: "full" | "supervised";
  scheduler_mode: "active" | "learning" | "reduced" | "paused";
  regime: string;
  daily_pnl: number;
  win_rate: number;
  drawdown_pct: number;
  portfolio_greeks: GreeksTotals;
  circuit_breakers_active: string[];
  pending_count: number;
  one_trade_locked: boolean;
  active_trade_id?: string | null;
  kill_switch_armed?: boolean;
  api_health?: string;
}

export const STRATEGY_LABELS: Record<StrategyModule, string> = {
  stat_arb: "Statistical Arbitrage",
  volatility: "Simple Volatility",
  gamma_scalping: "Gamma Scalping",
  vega_scalping: "Vega Scalping",
};

export const ENTRY_MODE_LABELS: Record<EntryMode, string> = {
  standard: "Standard",
  cheap_vol_mode: "Cheap Vol",
  earnings_gap_mode: "Earnings Gap",
  high_realized_vol_mode: "High Realized Vol",
};
