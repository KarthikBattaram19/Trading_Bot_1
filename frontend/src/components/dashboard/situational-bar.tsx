"use client";

import { useEffect, useState } from "react";
import { pauseBot, resumeBot } from "@/lib/api";
import { formatCurrency, formatGreek, formatPct } from "@/lib/utils";
import type { BotStatus } from "@/types/decisions";
import { Icon, StatusPill } from "@/components/ui/primitives";

interface SituationalBarProps {
  status: BotStatus;
}

/**
 * Persistent "Global Metrics" command bar (Stitch: topbar-height 64px).
 * Market-wide metrics + bot state on the left, isolated Kill Switch on the right.
 * NIFTY / INDIA VIX are global illustrative marks (not part of bot state yet).
 */
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
    <header className="sticky top-0 z-40 border-b border-outline-variant bg-surface/95 backdrop-blur">
      <div className="flex h-topbar-height items-center justify-between gap-4 px-6">
        <div className="flex min-w-0 items-center gap-4">
          <Icon name="security" className="shrink-0 text-primary" />
          <h1 className="hidden text-headline-md font-bold text-primary sm:block">
            Global Metrics
          </h1>

          <div className="ml-2 flex items-center gap-6 border-l border-outline-variant pl-6">
            <GlobalMetric
              label="NIFTY 50"
              value="22,453.20"
              change="▲ 0.45%"
              positive
            />
            <GlobalMetric
              label="INDIA VIX"
              value="14.82"
              change="▼ 1.20%"
              positive={false}
            />
          </div>

          <div className="ml-2 hidden items-center gap-3 border-l border-outline-variant pl-6 lg:flex">
            <StatusPill tone="neutral">{status.execution_mode}</StatusPill>
            {status.supervision_mode && (
              <StatusPill tone="neutral">{status.supervision_mode}</StatusPill>
            )}
            <StatusPill
              tone={status.scheduler_mode === "paused" ? "warning" : "success"}
            >
              {status.scheduler_mode}
            </StatusPill>
            {status.one_trade_locked && (
              <StatusPill tone="warning">One-trade locked</StatusPill>
            )}
          </div>
        </div>

        <div className="flex items-center gap-6">
          <div className="hidden items-center gap-5 xl:flex">
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
          </div>

          <button
            type="button"
            disabled={busy}
            onClick={handleKillSwitch}
            className={
              armed
                ? "flex items-center gap-2 rounded-md border border-error/60 px-5 py-2 text-label-caps uppercase text-error transition-colors hover:bg-error/10 active:scale-95 disabled:opacity-50"
                : "kill-switch-glow flex items-center gap-2 rounded-md bg-[#ef4444] px-5 py-2 text-label-caps uppercase text-white transition-colors hover:bg-error-container hover:text-on-error-container active:scale-95 disabled:opacity-50"
            }
          >
            <Icon name="power_settings_new" className="text-[18px]" />
            {busy ? "…" : armed ? "Disarm" : "Kill Switch"}
          </button>
        </div>
      </div>

      {(breakers.length > 0 || armed) && (
        <div className="flex items-center gap-2 border-t border-error/30 bg-error/10 px-6 py-2 text-data-sm text-error">
          <Icon name="warning" className="text-[16px]" />
          Active breakers: {breakers.join(", ") || "kill_switch"}
        </div>
      )}
    </header>
  );
}

function GlobalMetric({
  label,
  value,
  change,
  positive,
}: {
  label: string;
  value: string;
  change: string;
  positive: boolean;
}) {
  return (
    <div className="flex flex-col">
      <span className="text-label-caps uppercase text-on-surface-variant">
        {label}
      </span>
      <span className="font-mono text-data-md text-on-surface">
        {value}{" "}
        <span
          className={
            positive ? "text-[10px] text-secondary" : "text-[10px] text-error"
          }
        >
          {change}
        </span>
      </span>
    </div>
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
      <div className="text-label-caps uppercase text-on-surface-variant">
        {label}
      </div>
      <div
        className={
          warn
            ? "font-mono text-data-md text-tertiary"
            : positive === true
              ? "font-mono text-data-md text-secondary"
              : positive === false
                ? "font-mono text-data-md text-error"
                : "font-mono text-data-md text-on-surface"
        }
      >
        {value}
      </div>
    </div>
  );
}

function GreekStrip({ greeks }: { greeks: BotStatus["portfolio_greeks"] }) {
  return (
    <div className="hidden items-center gap-3 font-mono text-data-sm text-on-surface-variant 2xl:flex">
      <span className="text-outline">Portfolio</span>
      <span>Δ {formatGreek(greeks.total_delta)}</span>
      <span>Γ {formatGreek(greeks.total_gamma)}</span>
      <span>ν {formatGreek(greeks.total_vega)}</span>
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

  return <span className="font-mono text-tertiary">{display} left</span>;
}
