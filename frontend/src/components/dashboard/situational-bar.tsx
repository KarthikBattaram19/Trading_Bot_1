"use client";

import { useEffect, useState } from "react";
import { pauseBot, resumeBot } from "@/lib/api";
import { formatCurrency, formatGreek, formatPct } from "@/lib/utils";
import type { BotStatus } from "@/types/decisions";
import { Badge, Button } from "@/components/ui/primitives";

interface SituationalBarProps {
  status: BotStatus;
}

export function SituationalBar({ status }: SituationalBarProps) {
  const [busy, setBusy] = useState(false);
  const [armed, setArmed] = useState(Boolean(status.kill_switch_armed));

  async function handleKillSwitch() {
    setBusy(true);
    try {
      if (armed) {
        await resumeBot();
        setArmed(false);
      } else {
        await pauseBot();
        setArmed(true);
      }
    } finally {
      setBusy(false);
    }
  }

  const breakers =
    armed && !status.circuit_breakers_active.includes("kill_switch")
      ? [...status.circuit_breakers_active, "kill_switch"]
      : status.circuit_breakers_active;

  return (
    <header className="sticky top-0 z-10 border-b border-surface-border bg-surface/95 backdrop-blur">
      <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant="default">{status.execution_mode.toUpperCase()}</Badge>
          {status.supervision_mode && (
            <Badge variant="default">{status.supervision_mode}</Badge>
          )}
          <Badge variant="pass">{status.autonomy} autonomy</Badge>
          <Badge variant={status.scheduler_mode === "paused" ? "warn" : "pass"}>
            {status.scheduler_mode}
          </Badge>
          <span className="text-sm text-gray-400">
            Regime: <span className="text-white">{status.regime}</span>
          </span>
          {status.api_health && (
            <Badge variant={status.api_health === "ok" ? "pass" : "fail"}>
              API {status.api_health}
            </Badge>
          )}
          {status.one_trade_locked && (
            <Badge variant="warn">One-trade scope locked</Badge>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-6 text-sm">
          <Metric
            label="Daily P&L"
            value={formatCurrency(status.daily_pnl)}
            positive={status.daily_pnl >= 0}
          />
          <Metric label="Win rate" value={formatPct(status.win_rate)} />
          <Metric
            label="Drawdown"
            value={`${status.drawdown_pct.toFixed(1)}%`}
            warn={status.drawdown_pct > 5}
          />
          <GreekStrip greeks={status.portfolio_greeks} />
          <Button variant="danger" size="sm" disabled={busy} onClick={handleKillSwitch}>
            {busy ? "…" : armed ? "Disarm kill switch" : "Kill switch"}
          </Button>
        </div>
      </div>
      {(breakers.length > 0 || armed) && (
        <div className="border-t border-status-fail/30 bg-status-fail/10 px-6 py-2 text-sm text-status-fail">
          Active breakers: {breakers.join(", ") || "kill_switch"}
        </div>
      )}
    </header>
  );
}

function Metric({
  label,
  value,
  positive,
  warn,
}: {
  label: string;
  value: string;
  positive?: boolean;
  warn?: boolean;
}) {
  return (
    <div>
      <div className="text-xs text-gray-500">{label}</div>
      <div
        className={
          warn
            ? "font-mono text-status-warn"
            : positive === true
              ? "font-mono text-status-pass"
              : positive === false
                ? "font-mono text-status-fail"
                : "font-mono text-white"
        }
      >
        {value}
      </div>
    </div>
  );
}

function GreekStrip({
  greeks,
}: {
  greeks: BotStatus["portfolio_greeks"];
}) {
  return (
    <div className="hidden items-center gap-3 font-mono text-xs lg:flex">
      <span className="text-gray-500">Portfolio</span>
      <span>Δ {formatGreek(greeks.total_delta)}</span>
      <span>Γ {formatGreek(greeks.total_gamma)}</span>
      <span>V {formatGreek(greeks.total_vega)}</span>
      <span>Θ {formatGreek(greeks.total_theta)}</span>
    </div>
  );
}

export function CountdownTimer({ expiresAt }: { expiresAt: string }) {
  const [display, setDisplay] = useState("—");

  useEffect(() => {
    function tick() {
      const ms = Math.max(0, new Date(expiresAt).getTime() - Date.now());
      const min = Math.floor(ms / 60000);
      const sec = Math.floor((ms % 60000) / 1000);
      setDisplay(`${min}:${sec.toString().padStart(2, "0")}`);
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [expiresAt]);

  return <span className="font-mono text-status-pending">{display} left</span>;
}
