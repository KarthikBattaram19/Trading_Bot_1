import { useMockData } from "@/lib/utils";
import {
  mockBotStatus,
  mockPendingDecisions,
  mockDecisionLog,
  getMockDecision,
} from "@/lib/mock-data";
import { mockRecommendations } from "@/lib/recommendations-mock";
import { mockLearningDashboard } from "@/lib/learning-mock";
import {
  mockAutomationStatus,
  mockClosedPositions,
  mockOpenPositions,
  mockPaperAccount,
} from "@/lib/positions-mock";
import type { BotStatus, PendingDecision } from "@/types/decisions";
import type { AutonomousExecutionResult } from "@/types/trades";
import type {
  FeedSource,
  RecommendationResponse,
} from "@/types/recommendations";
import type {
  CloseTradeRequest,
  LearningDashboard,
  TradeOutcomeRecord,
} from "@/types/learning";
import type {
  PaperAccountSnapshot,
  PaperAutomationStatus,
  PaperPosition,
  PaperPositionsResponse,
} from "@/types/paper-sim";
import type { MarketIndicesResponse } from "@/types/market";
import type { RiskSnapshot } from "@/types/risk";
import { mockRiskSnapshot } from "@/lib/risk-mock";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const mockMarketIndices: MarketIndicesResponse = {
  as_of: new Date().toISOString(),
  indices: [
    {
      label: "NIFTY 50",
      stock_code: "NIFTY",
      exchange: "NSE",
      ltp: 22453.2,
      previous_close: 22352.4,
      change_pct: 0.45,
      ts: new Date().toISOString(),
      stale: false,
    },
    {
      label: "INDIA VIX",
      stock_code: "INDVIX",
      exchange: "NSE",
      ltp: 14.82,
      previous_close: 15.0,
      change_pct: -1.2,
      ts: new Date().toISOString(),
      stale: false,
    },
  ],
};

const mockAutonomousExecution: AutonomousExecutionResult = {
  executed: true,
  selected_rank: 2,
  trade_id: "trd_reliance_mock",
  underlying_symbol: "RELIANCE",
  attempts: [
    {
      rank: 1,
      underlying_symbol: "TATASTEEL",
      success: false,
      error: "Broker reject: vega scalp structure — insufficient liquidity at session open",
    },
    {
      rank: 2,
      underlying_symbol: "RELIANCE",
      success: true,
      trade_id: "trd_reliance_mock",
      order_status: "filled",
    },
  ],
  message: "Opened trade on rank #2 (RELIANCE) after rank(s) [1] failed",
};

function withMockAutonomousExecution(
  data: RecommendationResponse,
): RecommendationResponse {
  return {
    ...data,
    generated_at: new Date().toISOString(),
    autonomous_execution: mockAutonomousExecution,
  };
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = 45_000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      ...init,
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
    return res.json() as Promise<T>;
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error(`API ${path}: timed out after ${timeoutMs / 1000}s`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function getBotStatus(): Promise<BotStatus> {
  if (useMockData()) return mockBotStatus;
  return fetchJson<BotStatus>("/api/v1/bot/status");
}

export async function getMarketIndices(): Promise<MarketIndicesResponse> {
  if (useMockData()) {
    return {
      ...mockMarketIndices,
      as_of: new Date().toISOString(),
      indices: mockMarketIndices.indices.map((m) => ({
        ...m,
        ts: new Date().toISOString(),
      })),
    };
  }
  return fetchJson<MarketIndicesResponse>("/api/v1/market/indices");
}

export async function getPendingDecisions(): Promise<PendingDecision[]> {
  if (useMockData()) return mockPendingDecisions;
  return fetchJson<PendingDecision[]>("/api/v1/decisions/pending");
}

export async function getDecisionLog(): Promise<PendingDecision[]> {
  if (useMockData()) return mockDecisionLog;
  return fetchJson<PendingDecision[]>("/api/v1/decisions");
}

export async function getDecision(id: string): Promise<PendingDecision | null> {
  if (useMockData()) return getMockDecision(id) ?? null;
  try {
    return await fetchJson<PendingDecision>(`/api/v1/decisions/${id}`);
  } catch {
    return null;
  }
}

export async function approveDecision(id: string): Promise<void> {
  if (useMockData()) {
    console.info("[mock] approve", id);
    return;
  }
  const res = await fetch(`${API_URL}/api/v1/decisions/${id}/approve`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Approve failed: ${res.status}`);
}

export async function rejectDecision(id: string, reason?: string): Promise<void> {
  if (useMockData()) {
    console.info("[mock] reject", id, reason);
    return;
  }
  const res = await fetch(`${API_URL}/api/v1/decisions/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) throw new Error(`Reject failed: ${res.status}`);
}

export async function getApiHealth(): Promise<{
  status: string;
  execution_mode: string;
  phase?: string;
  place_order_enabled?: boolean;
  local_containers_required?: boolean;
  remote_builder?: string;
}> {
  if (useMockData()) {
    return {
      status: "ok",
      execution_mode: "shadow",
      phase: "0",
      place_order_enabled: false,
      local_containers_required: false,
      remote_builder: "nixpacks",
    };
  }
  return fetchJson<{
    status: string;
    execution_mode: string;
    phase?: string;
    place_order_enabled?: boolean;
    local_containers_required?: boolean;
    remote_builder?: string;
  }>("/health");
}

export async function getPaperSimHealth(): Promise<Record<string, unknown>> {
  if (useMockData()) {
    return {
      module: "paper_sim",
      phase: "1.1",
      status: "ready",
      separate_from_icici_live: true,
      broker_place_order: false,
      capabilities: {
        account: true,
        positions: true,
        fills: true,
        multi_leg_orders: true,
        close: true,
        reset: true,
        marks_refresh: true,
      },
    };
  }
  return fetchJson<Record<string, unknown>>("/api/v1/paper-sim/health");
}

export async function getPaperAccount(): Promise<PaperAccountSnapshot> {
  if (useMockData()) return mockPaperAccount;
  return fetchJson<PaperAccountSnapshot>("/api/v1/paper-sim/account");
}

export async function getPaperPositions(
  status: "open" | "closed" | "all" = "open",
): Promise<PaperPosition[]> {
  if (useMockData()) {
    if (status === "closed") return mockClosedPositions;
    if (status === "all") return [...mockOpenPositions, ...mockClosedPositions];
    return mockOpenPositions;
  }
  if (status === "all") {
    const [open, closed] = await Promise.all([
      fetchJson<PaperPositionsResponse>("/api/v1/paper-sim/positions?status=open"),
      fetchJson<PaperPositionsResponse>("/api/v1/paper-sim/positions?status=closed"),
    ]);
    return [...(open.positions ?? []), ...(closed.positions ?? [])];
  }
  const data = await fetchJson<PaperPositionsResponse>(
    `/api/v1/paper-sim/positions?status=${status}`,
  );
  return data.positions ?? [];
}

export async function getPaperAutomationStatus(): Promise<PaperAutomationStatus> {
  if (useMockData()) return mockAutomationStatus;
  return fetchJson<PaperAutomationStatus>("/api/v1/paper-sim/automation/status");
}

/** Flatten an open paper_sim position; learning is fed from the ledger close (§12). */
export async function closePaperPosition(
  positionId: string,
): Promise<Record<string, unknown>> {
  if (useMockData()) {
    return {
      success: true,
      path: "paper_sim",
      realized_pnl: 0,
      position: { position_id: positionId, status: "closed" },
    };
  }
  const res = await fetch(
    `${API_URL}/api/v1/paper-sim/positions/${encodeURIComponent(positionId)}/close`,
    { method: "POST" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Paper close failed: ${res.status} ${text}`);
  }
  return res.json() as Promise<Record<string, unknown>>;
}

export async function getRiskSnapshot(): Promise<RiskSnapshot> {
  if (useMockData()) {
    return {
      ...mockRiskSnapshot,
      as_of: new Date().toISOString(),
      events: mockRiskSnapshot.events.map((e) => ({
        ...e,
        ts: new Date().toISOString(),
      })),
    };
  }
  return fetchJson<RiskSnapshot>("/api/v1/risk/snapshot");
}

export async function getFeedStatus(): Promise<FeedSource[]> {
  if (useMockData()) return mockRecommendations.feed_sources;
  return fetchJson<FeedSource[]>("/api/v1/feeds/status");
}

export async function getRecommendations(): Promise<RecommendationResponse> {
  if (useMockData()) return withMockAutonomousExecution(mockRecommendations);
  return fetchJson<RecommendationResponse>("/api/v1/recommendations");
}

export async function refreshRecommendations(): Promise<RecommendationResponse> {
  if (useMockData()) {
    return withMockAutonomousExecution(mockRecommendations);
  }
  const res = await fetch(`${API_URL}/api/v1/recommendations?refresh=true`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Recommendations failed: ${res.status}`);
  return res.json() as Promise<RecommendationResponse>;
}

export async function executeAutonomousRecommendations(): Promise<AutonomousExecutionResult> {
  if (useMockData()) {
    return mockAutonomousExecution;
  }
  const res = await fetch(`${API_URL}/api/v1/recommendations/execute-autonomous`, {
    method: "POST",
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Autonomous execution failed: ${res.status} ${body}`);
  }
  return res.json() as Promise<AutonomousExecutionResult>;
}

export async function getLearningDashboard(): Promise<LearningDashboard> {
  if (useMockData()) return { ...mockLearningDashboard, as_of: new Date().toISOString() };
  return fetchJson<LearningDashboard>("/api/v1/learning/dashboard");
}

export async function recordTradeOutcome(
  body: CloseTradeRequest,
): Promise<TradeOutcomeRecord> {
  if (useMockData()) {
    const open = mockLearningDashboard.open_trades.find(
      (t) => t.trade_id === body.trade_id,
    );
    const record: TradeOutcomeRecord = {
      outcome_id: `out_mock_${Date.now()}`,
      trade_id: body.trade_id,
      underlying_symbol: open?.underlying_symbol ?? "UNKNOWN",
      rank: open?.rank ?? 0,
      strategy: open?.strategy ?? "simple_volatility",
      entry_mode: open?.entry_mode,
      scenario_tag: open?.scenario_tag ?? "",
      primary_signal: open?.primary_signal ?? "",
      score_at_entry: open?.score ?? 0,
      confidence_at_entry: open?.confidence ?? 0,
      outcome: body.outcome,
      realized_pnl_inr: body.realized_pnl_inr,
      exit_reason: body.exit_reason,
      notes: body.notes,
      opened_at: open?.opened_at ?? new Date().toISOString(),
      closed_at: new Date().toISOString(),
      failure_memory_id:
        body.outcome === "loss" ? `fm_mock_${Date.now()}` : null,
      config_snapshot_id: "defaults",
    };
    mockLearningDashboard.open_trades = mockLearningDashboard.open_trades.filter(
      (t) => t.trade_id !== body.trade_id,
    );
    mockLearningDashboard.recent_outcomes = [
      record,
      ...mockLearningDashboard.recent_outcomes,
    ];
    mockLearningDashboard.closed_trade_count += 1;
    mockLearningDashboard.open_trade_count = mockLearningDashboard.open_trades.length;
    mockLearningDashboard.total_pnl_inr += body.realized_pnl_inr;
    if (body.outcome === "loss") {
      mockLearningDashboard.failure_memory_count += 1;
    }
    return record;
  }
  const res = await fetch(`${API_URL}/api/v1/learning/outcomes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Record outcome failed: ${res.status} ${text}`);
  }
  return res.json() as Promise<TradeOutcomeRecord>;
}

