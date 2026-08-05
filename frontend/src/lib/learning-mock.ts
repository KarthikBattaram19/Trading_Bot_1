import type { LearningDashboard } from "@/types/learning";

/** Offline fallback — empty real metrics (matches seed-excluded §12 dashboard). */
const now = new Date().toISOString();

export const mockLearningDashboard: LearningDashboard = {
  as_of: now,
  closed_trade_count: 0,
  open_trade_count: 0,
  win_rate: null,
  total_pnl_inr: 0,
  profit_factor: null,
  failure_memory_count: 0,
  adaptation_frozen: false,
  freeze_reason: null,
  module_attribution: [
    {
      strategy: "vega_scalping",
      trade_count: 0,
      wins: 0,
      losses: 0,
      scratches: 0,
      win_rate: 0,
      total_pnl_inr: 0,
      expectancy_inr: 0,
      weight: 1.0,
    },
    {
      strategy: "gamma_scalping",
      trade_count: 0,
      wins: 0,
      losses: 0,
      scratches: 0,
      win_rate: 0,
      total_pnl_inr: 0,
      expectancy_inr: 0,
      weight: 1.0,
    },
    {
      strategy: "simple_volatility",
      trade_count: 0,
      wins: 0,
      losses: 0,
      scratches: 0,
      win_rate: 0,
      total_pnl_inr: 0,
      expectancy_inr: 0,
      weight: 1.0,
    },
  ],
  recent_outcomes: [],
  open_trades: [],
  failure_memories: [],
  adaptation_history: [],
  learning_loop_notes: [
    "Every closed trade feeds module attribution and failure memory (§12).",
    "Pre-trade: similar failure contexts penalize confidence by −0.10 (§12.6).",
    "Reporting metrics use real paper_sim ledger closes only — seed/demo fixtures are excluded.",
    "No real closed trades yet — approve a recommendation and close via paper_sim.",
  ],
};
