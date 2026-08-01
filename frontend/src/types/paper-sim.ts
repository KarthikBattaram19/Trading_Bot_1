/** Paper simulator DTOs — mirrors backend/paper_sim/models.py */

export type PaperSide = "buy" | "sell";

export interface PaperLegPosition {
  symbol: string;
  exchange: string;
  symbol_token: string;
  side: PaperSide;
  quantity: number;
  avg_price: number;
  mark_ltp?: number | null;
  unrealized_pnl?: number;
  lotsize?: number;
}

export interface PaperPosition {
  position_id: string;
  strategy_tag?: string | null;
  underlying?: string | null;
  status: "open" | "closed";
  opened_at: string;
  closed_at?: string | null;
  legs: PaperLegPosition[];
  realized_pnl: number;
  unrealized_pnl: number;
  note?: string | null;
  intended_legs?: unknown[];
  structure_complete?: boolean;
  opening_investment_inr?: number;
  auto_complete_multi_leg?: boolean;
  hedge_point_price?: number | null;
  gamma_theta_breakeven_pct?: number | null;
  breakeven_paid_count?: number;
  rehedge_method?: string;
  last_rehedge_at?: string | null;
  total_delta?: number | null;
  total_gamma?: number | null;
  total_theta?: number | null;
  total_vega?: number | null;
}

export interface PaperAccountSnapshot {
  cash_inr: number;
  starting_capital_inr: number;
  reserved_margin_inr: number;
  equity_inr: number;
  realized_pnl: number;
  unrealized_pnl: number;
  open_positions: number;
  max_trade_investment_inr: number;
  max_leg_investment_inr: number;
  mark_provider: string;
  updated_at: string;
}

export interface PaperAutomationAction {
  action: string;
  reason?: string;
  detail?: unknown;
  position_id?: string;
  underlying?: string;
  method?: string;
  note?: string;
  realized_pnl?: number;
  at?: string;
  [key: string]: unknown;
}

export interface PaperAutomationStatus {
  state: string;
  running: boolean;
  llm_in_path?: boolean;
  started_at?: string | null;
  stopped_at?: string | null;
  last_tick_at?: string | null;
  tick_sec?: number;
  ticks?: number;
  hedges?: number;
  flattens?: number;
  skips?: number;
  last_error?: string | null;
  last_news_impact?: string | null;
  last_signal?: Record<string, unknown> | null;
  hedge_points?: Array<Record<string, unknown>>;
  last_actions?: PaperAutomationAction[];
  config?: Record<string, unknown>;
}

export interface PaperPositionsResponse {
  positions: PaperPosition[];
}
