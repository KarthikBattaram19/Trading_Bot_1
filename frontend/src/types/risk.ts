/** Risk dashboard DTOs — mirrors GET /api/v1/risk/snapshot */

export type BreakerTone = "safe" | "warn" | "danger";
export type RiskEventLevel = "info" | "warn" | "danger";

export interface RiskBreaker {
  id: string;
  name: string;
  current: number;
  limit: number;
  unit: "pct" | "inr" | "count" | "sec" | string;
  pct: number;
  tone: BreakerTone;
  detail?: string | null;
}

export interface RiskGreekLimit {
  greek: string;
  key: string;
  current: number;
  limit: number;
  pct: number;
}

export interface RiskEvent {
  level: RiskEventLevel;
  text: string;
  ts: string;
}

export interface RiskSnapshot {
  as_of: string;
  equity_inr: number;
  starting_capital_inr: number;
  reserved_margin_inr: number;
  cash_inr: number;
  realized_pnl: number;
  unrealized_pnl: number;
  session_pnl: number;
  daily_pnl: number;
  drawdown_pct: number;
  win_rate: number;
  open_positions: number;
  portfolio_greeks: {
    total_delta: number;
    total_gamma: number;
    total_theta: number;
    total_vega: number;
  };
  greek_limits: RiskGreekLimit[];
  greeks_within_limits: boolean;
  greeks_failures: string[];
  circuit_breakers: RiskBreaker[];
  circuit_breakers_active: string[];
  feed_age_sec: number | null;
  events: RiskEvent[];
  shared_kill_conditions: string[];
  limits: {
    max_drawdown_pct: number;
    max_daily_loss_pct: number;
    max_consecutive_losses: number;
    quote_stale_threshold_sec: number;
    max_abs_total_delta: number;
    max_abs_total_gamma: number;
    max_abs_total_vega: number;
    min_total_theta: number;
  };
}
