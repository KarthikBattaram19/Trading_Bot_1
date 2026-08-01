import type {
  PaperAccountSnapshot,
  PaperAutomationStatus,
  PaperPosition,
} from "@/types/paper-sim";

function todayAt(h: number, m: number, s = 0): string {
  const d = new Date();
  d.setHours(h, m, s, 0);
  return d.toISOString();
}

export const mockOpenPositions: PaperPosition[] = [
  {
    position_id: "pos_001",
    underlying: "RELIANCE",
    strategy_tag: "LONG_VEGA",
    status: "open",
    opened_at: todayAt(9, 48),
    legs: [
      {
        symbol: "RELIANCE",
        exchange: "NSE",
        symbol_token: "2885",
        side: "buy",
        quantity: 250,
        avg_price: 1420,
        mark_ltp: 1436.8,
        unrealized_pnl: 4200,
      },
    ],
    realized_pnl: 0,
    unrealized_pnl: 4200,
    note: "Gamma scaling active. Waiting for VIX confirmation > 15 to unhedge delta.",
    structure_complete: true,
    total_delta: 0.02,
    total_gamma: 0.11,
    total_vega: 0.42,
    total_theta: -85,
    breakeven_paid_count: 1,
    rehedge_method: "increase_hedge",
  },
  {
    position_id: "pos_002",
    underlying: "BANKNIFTY",
    strategy_tag: "SHORT_STRANGLE",
    status: "open",
    opened_at: todayAt(10, 15),
    legs: [
      {
        symbol: "BANKNIFTY 28DEC 48000P",
        exchange: "NFO",
        symbol_token: "99901",
        side: "sell",
        quantity: 15,
        avg_price: 185,
        mark_ltp: 156.7,
        unrealized_pnl: 4250,
      },
    ],
    realized_pnl: 0,
    unrealized_pnl: 4250,
    note: "Theta decay collection. Monitoring for tail risk break below 47800.",
    structure_complete: true,
    total_delta: -0.12,
    total_gamma: -0.05,
    total_vega: -22.1,
    total_theta: 18.5,
    breakeven_paid_count: 0,
    rehedge_method: "increase_hedge",
  },
];

export const mockClosedPositions: PaperPosition[] = [
  {
    position_id: "cls_001",
    underlying: "FINNIFTY",
    strategy_tag: "INTRADAY_MOMENTUM",
    status: "closed",
    opened_at: todayAt(9, 20),
    closed_at: todayAt(11, 30),
    legs: [
      {
        symbol: "FINNIFTY 19DEC 21200C",
        exchange: "NFO",
        symbol_token: "99902",
        side: "buy",
        quantity: 40,
        avg_price: 95,
        mark_ltp: 65,
        unrealized_pnl: 0,
      },
    ],
    realized_pnl: -1200,
    unrealized_pnl: 0,
    note: "Hit time exit (15:15)",
    structure_complete: true,
  },
  {
    position_id: "cls_002",
    underlying: "NIFTY",
    strategy_tag: "SHORT_GAMMA",
    status: "closed",
    opened_at: todayAt(10, 5),
    closed_at: todayAt(14, 5),
    legs: [
      {
        symbol: "NIFTY 21DEC 21400P",
        exchange: "NFO",
        symbol_token: "99903",
        side: "sell",
        quantity: 50,
        avg_price: 112,
        mark_ltp: 44,
        unrealized_pnl: 0,
      },
    ],
    realized_pnl: 3400,
    unrealized_pnl: 0,
    note: "Target profit reached",
    structure_complete: true,
  },
];

export const mockPaperAccount: PaperAccountSnapshot = {
  cash_inr: 850_000,
  starting_capital_inr: 1_000_000,
  reserved_margin_inr: 120_000,
  equity_inr: 1_008_450,
  realized_pnl: 2200,
  unrealized_pnl: 8450,
  open_positions: mockOpenPositions.length,
  max_trade_investment_inr: 100_000,
  max_leg_investment_inr: 50_000,
  mark_provider: "icici_direct",
  updated_at: new Date().toISOString(),
};

export const mockAutomationStatus: PaperAutomationStatus = {
  state: "running",
  running: true,
  llm_in_path: false,
  ticks: 42,
  hedges: 2,
  flattens: 0,
  skips: 5,
  last_actions: [
    {
      action: "rehedge",
      method: "increase_hedge",
      reason: "Delta > 0.3",
      position_id: "pos_001",
      underlying: "NIFTY",
      note: "DELTA_NEUTRAL_HEDGE",
      realized_pnl: 0,
      at: todayAt(11, 2, 45),
    },
    {
      action: "rehedge",
      method: "reduce_options",
      reason: "VIX Spike Detected",
      position_id: "pos_002",
      underlying: "BANKNIFTY",
      note: "VEGA_EXPOSURE_REDUCE",
      realized_pnl: -150,
      at: todayAt(10, 45, 12),
    },
    {
      action: "rehedge",
      method: "increase_hedge",
      reason: "Strategy Bootstrap",
      position_id: "pos_001",
      underlying: "NIFTY",
      note: "INITIAL_HEDGE_ENTRY",
      realized_pnl: 0,
      at: todayAt(9, 35),
    },
  ],
};
