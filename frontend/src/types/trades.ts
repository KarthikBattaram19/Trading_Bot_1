export interface TradeAttemptResult {
  rank: number;
  underlying_symbol: string;
  success: boolean;
  error?: string;
  trade_id?: string;
  order_status?: string;
}

export interface AutonomousExecutionResult {
  executed: boolean;
  selected_rank?: number;
  trade_id?: string;
  underlying_symbol?: string;
  attempts: TradeAttemptResult[];
  message: string;
}

export type RankExecutionStatus = "pending" | "attempting" | "succeeded" | "failed" | "skipped";

export function rankStatusFromResult(
  rank: number,
  result: AutonomousExecutionResult | null,
  isExecuting: boolean,
): RankExecutionStatus {
  if (!result) {
    return isExecuting && rank === 1 ? "attempting" : "pending";
  }

  const attempt = result.attempts.find((a) => a.rank === rank);
  if (!attempt) {
    if (result.executed && result.selected_rank != null && rank > result.selected_rank) {
      return "skipped";
    }
    return "pending";
  }
  if (attempt.success) return "succeeded";
  return "failed";
}
