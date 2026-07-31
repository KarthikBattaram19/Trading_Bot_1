import type { RecommendationResponse } from "@/types/recommendations";

const now = new Date().toISOString();

export const mockRecommendations: RecommendationResponse = {
  "generated_at": now,
  "feed_as_of": now,
  "feed_sources": [
    {
      "source_id": "icici_direct",
      "source_name": "ICICI Direct Breeze API",
      "status": "active",
      "capabilities": [
        "quotes",
        "ltp",
        "historical",
        "option_chain"
      ],
      "last_fetch_at": now,
      "health": "stale",
      "detail": "Credentials present - call POST /api/v1/config/integrations/broker/test"
    },
    {
      "source_id": "market_news",
      "source_name": "Market_News (India curation)",
      "status": "stub",
      "capabilities": [
        "news_sentiment",
        "event_flags"
      ],
      "last_fetch_at": now,
      "health": "stale",
      "detail": "Curated per Market_News.txt - live ingest pending (Architecture 8.8)"
    }
  ],
  "market_news": {
    "headline_count": 6,
    "dominant_sentiment": "Neutral",
    "earnings_mentions": 2,
    "macro_risk_flags": [
      "Using simulated news — wire Market_News.txt ingest for live feed"
    ],
    "interpretation": "Mock news layer active. Sentiment will come from curated India sources listed in Market_News.txt (Architecture §8.8).",
    "items": [
      {
        "title": "NIFTY options see intraday IV flush on quiet open",
        "summary": "ATM weekly options printed IV 2.1σ below session mean.",
        "source": "Simulated Feed",
        "time_published": "20260705T093000",
        "sentiment_label": "Neutral",
        "sentiment_score": 0.02,
        "tickers": [
          "NIFTY"
        ],
        "topics": [
          "financial_markets"
        ],
        "relevance_to_trade": "Supports vega scalping candidate"
      },
      {
        "title": "Major IT name reports earnings tomorrow",
        "summary": "Implied move elevated; term structure stable at entry window.",
        "source": "Simulated Feed",
        "time_published": "20260705T080000",
        "sentiment_label": "Somewhat-Bullish",
        "sentiment_score": 0.18,
        "tickers": [
          "INFY"
        ],
        "topics": [
          "earnings"
        ],
        "relevance_to_trade": "Gamma earnings_gap_mode candidate"
      }
    ]
  },
  "universe_scanned": 213,
  "candidates_passing_gates": 6,
  "analysis_notes": [
    "Scanned 213 instruments from feed-bound universe (G11–G12).",
    "Universe source: ICICI Direct FONSEScripMaster (icici_direct_fonsescripmaster) — all NSE F&O underlyings with auto G12 bindings.",
    "6 passed all retail gates (T1–T16, I21).",
    "Confidence floor: only candidates with confidence ≥ 85% are recommended.",
    "Strategy selection follows Trading_Strategies.md Table SH-4.",
    "Parameter gates sourced from Trading_Parameters.md Parts G, H, I, T.",
    "Each recommendation includes a complete P1 insight packet for operator review.",
    "Continual learning: failure memory + module weights applied (§12).",
    "5 candidate(s) scored but were excluded for confidence < 85% (best excluded: 83%).",
    "Failure-memory matches on 4 candidate(s) — confidence penalized −0.10 where similar losses exist.",
    "News flags: Using simulated news — wire Market_News.txt ingest for live feed"
  ],
  "recommendations": [
    {
      "rank": 1,
      "underlying_symbol": "INFY",
      "score": 0.918,
      "confidence": 0.85,
      "strategy": {
        "selected_strategy": "gamma_scalping",
        "entry_mode": "earnings_gap_mode",
        "scenario_tag": "Scenario A: Earnings Gap",
        "cross_strategy_matrix_ref": "Table SH-4: Earnings gap → Gamma scalping",
        "primary_signal": "days_to_earnings=1; Scenario E: und_price ₹1680.00 > 1000 INR — switch to options-only (T11 skipped)",
        "rejected_strategies": [
          "simple_volatility — plain long-vega through event (SH-4 Avoid)",
          "stock_hedge — T11 spot cap"
        ],
        "news_impact": "Earnings in 1d — news confirms event risk"
      },
      "parameters": {
        "und_price": 1680.0,
        "iv_annualized": 0.29,
        "garch_forecast": 0.03792204297317363,
        "iv_z_score": -1.8,
        "days_to_earnings": 1,
        "atm_premium_inr": 210.0,
        "volume": 15200,
        "open_interest": 28000,
        "spread_pct": 1.1,
        "dte": 25,
        "realized_vol_intraday": 0.015,
        "garch_distorted": false
      },
      "parameter_gates": [
        {
          "gate_id": "T11",
          "label": "Underlying price cap N/A (options-only)",
          "passed": true,
          "detail": "₹1680.00 (options-only — T11 N/A)",
          "parameter_ref": "Trading_Parameters.md Part T — T11"
        },
        {
          "gate_id": "T1",
          "label": "ATM premium < 300 INR",
          "passed": true,
          "detail": "₹210.00",
          "parameter_ref": "Trading_Parameters.md Part T — T1"
        },
        {
          "gate_id": "T13",
          "label": "Volume ≥ 1000",
          "passed": true,
          "detail": "15200",
          "parameter_ref": "Trading_Parameters.md Part T — T13"
        },
        {
          "gate_id": "T14",
          "label": "Open interest ≥ 10000",
          "passed": true,
          "detail": "28000",
          "parameter_ref": "Trading_Parameters.md Part T — T14"
        },
        {
          "gate_id": "T15",
          "label": "Spread ≤ 2.0% of mid",
          "passed": true,
          "detail": "1.10%",
          "parameter_ref": "Trading_Parameters.md Part T — T15"
        },
        {
          "gate_id": "L3.3",
          "label": "DTE ≥ 10",
          "passed": true,
          "detail": "25 days",
          "parameter_ref": "Trading_Parameters.md Part L — L3.3"
        }
      ],
      "market_summary": "INFY spot ₹1680.00; IV 29.0% vs GARCH 3.8% (rich vol). Scenario: Scenario A: Earnings Gap. Intraday IV z=-1.80. Earnings in 1d. Intraday RV=1.5%.",
      "entry_rationale": "days_to_earnings=1; Scenario E: und_price ₹1680.00 > 1000 INR — switch to options-only (T11 skipped)",
      "complete_logic": [
        "1. Feed bind: underlying_symbol=INFY, und_price=₹1680.00 (A4/A5)",
        "2. Universe filter T11: options-only — no underlying price cap (N/A at ₹1680.00)",
        "3. Liquidity T13–T15: vol=15200, OI=28000, spread=1.10%",
        "4. GARCH(1,1) forecast σ_annual=3.79% (H10); mark IV=29.00% (G4)",
        "5. Intraday IV z-score=-1.80 (N4.4–N4.5)",
        "6. Earnings calendar: DTE_event=1 (G6, M2.2)",
        "7. Strategy matrix (Table SH-4: Earnings gap → Gamma scalping): → gamma_scalping [earnings_gap_mode]",
        "8. Primary signal: days_to_earnings=1; Scenario E: und_price ₹1680.00 > 1000 INR — switch to options-only (T11 skipped)",
        "9. All retail gates T1–T16 + DTE pass — eligible for ranking",
        "10. Alternatives rejected: simple_volatility — plain long-vega through event (SH-4 Avoid); stock_hedge — T11 spot cap",
        "11. News overlay: Earnings in 1d — news confirms event risk",
        "12. Learning: Failure memory hit: 1 similar loss(es). Top match INFY/gamma_scalping (sim=99%, PnL ₹-3,100). Confidence −0.10 per §12.6."
      ],
      "score_breakdown": {
        "base": 0.5,
        "strategy_boost": 0.3,
        "liquidity_boost": 0.14,
        "spread_penalty": 0.022,
        "failure_memory_penalty": 0.1,
        "module_weight_factor": 1.0,
        "total": 0.918,
        "components": [
          "Base eligibility 0.50",
          "Earnings-gap mode boost +0.30",
          "OI liquidity boost +0.14",
          "Spread penalty −0.02 (1.10% mid)",
          "Total score 0.918 (capped at 0.99)",
          "Failure-memory confidence penalty −0.10 (1 similar loss(es) — §12.6)"
        ]
      },
      "hedge": {
        "method": "Vega-neutral long gamma (earnings_gap_mode)",
        "greek_targets": "Δ≈0 · V≈0 · Γ+ · Θ−",
        "structure_note": "Near/far expiry same-strike; four-leg options-only (no stock) — T11 N/A"
      },
      "economics": {
        "margin_estimate_inr": 16800.0,
        "max_trade_budget_inr": 100000.0,
        "atm_premium_inr": 210.0,
        "estimated_slippage_pct": 0.55,
        "net_edge_note": "IV−GARCH edge -25.2%; premium ₹210 within T1 cap; est. slippage ~0.55% of mid from spread."
      },
      "exit_plan": "Close after earnings gap (M6). Re-neutralize delta/vega at breakeven.",
      "event_risks": [
        "Earnings in 1 day(s)"
      ],
      "failure_modes": [
        "Quiet market — theta dominates",
        "Term-structure distortion post-entry",
        "Post-gap Greek drift"
      ],
      "why_this_rank": "Rank #1 — sole eligible candidate (score 0.92).",
      "alternative_considered": "simple_volatility — plain long-vega through event (SH-4 Avoid)",
      "insight_checklist": [
        "P1.1 Strategy: gamma_scalping / earnings_gap_mode",
        "P1.2 Instrument: INFY @ ₹1680.00",
        "P1.3 Market condition: summarized",
        "P1.4 Entry rationale: primary signal set",
        "P1.5 Hedge construction: method + Greek targets",
        "P1.6 Size & margin: within INR 1,00,000 retail cap",
        "P1.7 Exit plan: stop / target / time",
        "P1.8 Event risks: 1 item(s)",
        "P1.9 Failure modes: 3 scenario bullet(s)",
        "Gates: 6/6 pass",
        "Matrix: Table SH-4: Earnings gap → Gamma scalping"
      ],
      "learning": {
        "failure_matches": [
          {
            "failure_id": "fm_seed_infy_gamma",
            "similarity": 0.99,
            "summary": "INFY earnings gap was muted; theta dominated overnight gamma structure.",
            "loss_pnl_inr": -3100.0,
            "lesson": "Earnings-gap gamma needs an implied-move floor; skip when options imply <1.5% move or news tone is already priced.",
            "strategy": "gamma_scalping",
            "underlying_symbol": "INFY",
            "closed_at": now
          }
        ],
        "confidence_penalty": 0.1,
        "confidence_before": 0.95,
        "confidence_after": 0.85,
        "module_win_rate": undefined,
        "module_trade_count": 0,
        "module_expectancy_inr": undefined,
        "learning_note": "Failure memory hit: 1 similar loss(es). Top match INFY/gamma_scalping (sim=99%, PnL ₹-3,100). Confidence −0.10 per §12.6."
      }
    }
  ]
};
