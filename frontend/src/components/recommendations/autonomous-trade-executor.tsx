"use client";

import type { AutonomousExecutionResult } from "@/types/trades";
import { Icon, StatusPill } from "@/components/ui/primitives";

interface AutonomousTradeExecutorProps {
  executionResult: AutonomousExecutionResult | null;
}

export function AutonomousTradeExecutor({
  executionResult,
}: AutonomousTradeExecutorProps) {
  if (!executionResult) return null;

  const isLocked =
    !executionResult.executed &&
    executionResult.attempts.length === 0 &&
    executionResult.message.includes("One-trade scope locked");

  return (
    <div className="rounded-md border border-primary-container bg-primary-container/20 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Icon name="rocket_launch" className="text-[24px] text-primary" />
          <div>
            <div className="flex items-center gap-2">
              <span className="text-label-caps uppercase text-primary">
                Autonomous Trade Execution
              </span>
              <StatusPill tone="success">full autonomy</StatusPill>
            </div>
            <p className="mt-1 text-data-sm text-on-surface-variant">
              Trade opened in the same cycle as recommendations — rank #1,
              fallback #2 → #3
            </p>
          </div>
        </div>
      </div>

      {isLocked && (
        <p className="mt-3 text-data-md text-error">{executionResult.message}</p>
      )}

      {!isLocked && (
        <div className="mt-3 space-y-2">
          <p
            className={
              executionResult.executed
                ? "text-data-md text-secondary"
                : "text-data-md text-error"
            }
          >
            {executionResult.message}
            {executionResult.trade_id && (
              <span className="ml-2 font-mono text-data-sm text-on-surface-variant">
                ({executionResult.trade_id})
              </span>
            )}
          </p>
          {executionResult.attempts.length > 0 && (
            <ul className="space-y-1">
              {executionResult.attempts.map((attempt) => (
                <li
                  key={attempt.rank}
                  className="flex flex-wrap items-center gap-2 font-mono text-data-sm"
                >
                  <span className="text-on-surface-variant">#{attempt.rank}</span>
                  <span className="text-on-surface">
                    {attempt.underlying_symbol}
                  </span>
                  {attempt.success ? (
                    <StatusPill tone="success">opened</StatusPill>
                  ) : (
                    <>
                      <StatusPill tone="danger">failed</StatusPill>
                      <span className="text-error">{attempt.error}</span>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
