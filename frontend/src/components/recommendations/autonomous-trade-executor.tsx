"use client";

import type { AutonomousExecutionResult } from "@/types/trades";
import { Badge, Card } from "@/components/ui/primitives";

interface AutonomousTradeExecutorProps {
  executionResult: AutonomousExecutionResult | null;
}

export function AutonomousTradeExecutor({ executionResult }: AutonomousTradeExecutorProps) {
  if (!executionResult) return null;

  const isLocked =
    !executionResult.executed &&
    executionResult.attempts.length === 0 &&
    executionResult.message.includes("One-trade scope locked");

  return (
    <Card className="border-accent/40 bg-accent/5 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-medium text-white">Autonomous trade execution</h2>
            <Badge variant="pass">full autonomy</Badge>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            Trade opened in the same cycle as recommendations — rank #1, fallback #2 → #3
          </p>
        </div>
      </div>

      {isLocked && (
        <p className="mt-3 text-sm text-status-fail">{executionResult.message}</p>
      )}

      {!isLocked && (
        <div className="mt-3 space-y-2">
          <p
            className={
              executionResult.executed ? "text-sm text-status-pass" : "text-sm text-status-fail"
            }
          >
            {executionResult.message}
            {executionResult.trade_id && (
              <span className="ml-2 font-mono text-xs text-gray-500">
                ({executionResult.trade_id})
              </span>
            )}
          </p>
          {executionResult.attempts.length > 0 && (
            <ul className="space-y-1">
              {executionResult.attempts.map((attempt) => (
                <li
                  key={attempt.rank}
                  className="flex flex-wrap items-center gap-2 font-mono text-xs"
                >
                  <span className="text-gray-500">#{attempt.rank}</span>
                  <span className="text-white">{attempt.underlying_symbol}</span>
                  {attempt.success ? (
                    <Badge variant="pass">opened</Badge>
                  ) : (
                    <>
                      <Badge variant="fail">failed</Badge>
                      <span className="text-status-fail">{attempt.error}</span>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
