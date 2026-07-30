/** Continual learning types — architecture §12 */

export type TradeOutcomeLabel = "win" | "loss" | "scratch";

export interface FailureMemoryMatch {
  failure_id: string;
  similarity: number;
  summary: string;
  loss_pnl_inr: number;
  lesson: string;
  strategy: string;
  underlying_symbol: string;
  closed_at: string;
}

export interface LearningInsight {
  failure_matches: FailureMemoryMatch[];
  confidence_penalty: number;
  confidence_before: number;
  confidence_after: number;
  module_win_rate?: number | null;
  module_trade_count: number;
  module_expectancy_inr?: number | null;
  learning_note: string;
}

export interface OpenTradeRecord {
  trade_id: string;
  underlying_symbol: string;
  rank: number;
  strategy: string;
  entry_mode?: string | null;
  scenario_tag: string;
  primary_signal: string;
  score: number;
  confidence: number;
  opened_at: string;
  config_snapshot_id: string;
}

export interface TradeOutcomeRecord {
  outcome_id: string;
  trade_id: string;
  underlying_symbol: string;
  rank: number;
  strategy: string;
  entry_mode?: string | null;
  scenario_tag: string;
  primary_signal: string;
  score_at_entry: number;
  confidence_at_entry: number;
  outcome: TradeOutcomeLabel;
  realized_pnl_inr: number;
  exit_reason: string;
  notes?: string | null;
  opened_at: string;
  closed_at: string;
  failure_memory_id?: string | null;
  config_snapshot_id: string;
}

export interface FailureMemoryEntry {
  failure_id: string;
  trade_id: string;
  underlying_symbol: string;
  strategy: string;
  entry_mode?: string | null;
  scenario_tag: string;
  primary_signal: string;
  market_summary: string;
  loss_pnl_inr: number;
  exit_reason: string;
  lesson: string;
  tags: string[];
  closed_at: string;
}

export interface ModuleAttribution {
  strategy: string;
  trade_count: number;
  wins: number;
  losses: number;
  scratches: number;
  win_rate: number;
  total_pnl_inr: number;
  expectancy_inr: number;
  weight: number;
}

export interface AdaptationEvent {
  adaptation_id: string;
  triggered_at: string;
  trigger: string;
  action: string;
  parameter_changes: Record<string, unknown>;
  walk_forward_passed: boolean;
  deployed: boolean;
  detail: string;
  config_snapshot_id: string;
}

export interface LearningDashboard {
  as_of: string;
  closed_trade_count: number;
  open_trade_count: number;
  win_rate: number | null;
  total_pnl_inr: number;
  profit_factor: number | null;
  failure_memory_count: number;
  adaptation_frozen: boolean;
  freeze_reason?: string | null;
  module_attribution: ModuleAttribution[];
  recent_outcomes: TradeOutcomeRecord[];
  open_trades: OpenTradeRecord[];
  failure_memories: FailureMemoryEntry[];
  adaptation_history: AdaptationEvent[];
  learning_loop_notes: string[];
}

export interface CloseTradeRequest {
  trade_id: string;
  outcome: TradeOutcomeLabel;
  realized_pnl_inr: number;
  exit_reason: string;
  notes?: string;
}

export const STRATEGY_LABELS: Record<string, string> = {
  simple_volatility: "Simple Volatility",
  gamma_scalping: "Gamma Scalping",
  vega_scalping: "Vega Scalping",
};
