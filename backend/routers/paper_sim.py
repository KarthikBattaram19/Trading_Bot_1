"""HTTP API for the in-house paper simulator (separate from ICICI Direct live orders)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.paper_sim.ledger import PaperLedgerError
from backend.paper_sim.models import PaperOrderRequest
from backend.paper_sim.service import get_paper_engine

router = APIRouter(prefix="/api/v1/paper-sim", tags=["paper-sim"])


class ResetRequest(BaseModel):
    starting_capital_inr: float | None = Field(
        default=None, description="Optional virtual cash reset; defaults to config"
    )


@router.get("/health")
async def paper_sim_health():
    return get_paper_engine().health()


@router.get("/account")
async def paper_account():
    return get_paper_engine().account().model_dump(mode="json")


@router.post("/reset")
async def paper_reset(body: ResetRequest | None = None):
    engine = get_paper_engine()
    capital = body.starting_capital_inr if body else None
    try:
        return engine.reset(capital).model_dump(mode="json")
    except PaperLedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/positions")
async def paper_positions(status: str | None = Query(default="open")):
    return {
        "positions": [
            p.model_dump(mode="json") for p in get_paper_engine().positions(status=status)
        ]
    }


@router.get("/fills")
async def paper_fills(limit: int = Query(default=100, ge=1, le=500)):
    return {
        "fills": [f.model_dump(mode="json") for f in get_paper_engine().fills(limit=limit)]
    }


@router.post("/orders")
async def paper_submit_order(request: PaperOrderRequest):
    """Simulate a multi-leg fill locally. Does not call ICICI Direct place_order.

    After entry, remaining intended multi-leg opening legs may auto-complete
    without operator consent (same open-trade gates).
    """
    from backend.paper_sim.freshness import StaleMarksError

    try:
        return await get_paper_engine().submit_order(request)
    except StaleMarksError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaperLedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface feed/auth failures clearly
        raise HTTPException(status_code=502, detail=f"paper mark feed error: {exc}") from exc


@router.post("/positions/{position_id}/complete-multi-leg")
async def paper_complete_multi_leg(position_id: str):
    """Retry auto-completion of intended opening legs (no consent; same open rules)."""
    from backend.paper_sim.freshness import StaleMarksError

    try:
        return await get_paper_engine().complete_multi_leg_structure(
            position_id, force=True
        )
    except StaleMarksError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaperLedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"paper mark feed error: {exc}") from exc


@router.post("/positions/{position_id}/close")
async def paper_close_position(position_id: str):
    from backend.paper_sim.freshness import StaleMarksError

    try:
        return await get_paper_engine().close_position(position_id)
    except StaleMarksError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaperLedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"paper mark feed error: {exc}") from exc


@router.post("/marks/refresh")
async def paper_refresh_marks():
    from backend.paper_sim.freshness import StaleMarksError

    try:
        return await get_paper_engine().refresh_marks()
    except StaleMarksError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"paper mark feed error: {exc}") from exc


@router.get("/marks/status")
async def paper_marks_status():
    """Fresh-marks gate config + last evaluation (Phase 1.2 / MD-01)."""
    return get_paper_engine().marks_status()


@router.get("/news")
async def paper_news(force_refresh: bool = Query(default=False)):
    """Current MarketNewsSummary from Market_News.txt pipeline (Phase 1.3 / §8.8)."""
    from backend.services.market_news import paper_news_packet

    return paper_news_packet(force_refresh=force_refresh)


class StrategySelectRequest(BaseModel):
    """Dry-run / force SH-4 selection given quant + optional news overrides (Phase 1.4)."""

    symbol: str = Field(..., min_length=1, description="Underlying symbol, e.g. SBIN")
    iv_annualized: float = Field(..., gt=0)
    garch_forecast: float = Field(..., gt=0)
    iv_z_score: float | None = None
    days_to_earnings: int | None = None
    realized_vol_intraday: float | None = None
    garch_distorted: bool = False
    # Optional news overrides — when omitted, live Market_News packet is used
    force_news: dict | None = Field(
        default=None,
        description="Optional MarketNewsSummary-compatible overrides for dry-run",
    )
    setup_designed_for_event: bool = False
    position_open: bool = False


@router.post("/strategies/select")
async def paper_strategies_select(body: StrategySelectRequest):
    """Force or dry-run SH-4 selection with Market_News overlay (Phase 1.4)."""
    from backend.models.recommendations import MarketNewsSummary
    from backend.services.market_news import get_market_news
    from backend.services.strategy_selection import (
        QuantRegimeInputs,
        select_strategy_packet,
    )

    news = get_market_news()
    if body.force_news:
        payload = news.model_dump(mode="json")
        # Shallow-merge top-level overrides; nested items replace when provided
        for key, value in body.force_news.items():
            payload[key] = value
        news = MarketNewsSummary.model_validate(payload)

    quant = QuantRegimeInputs(
        symbol=body.symbol.upper(),
        iv_annualized=body.iv_annualized,
        garch_forecast=body.garch_forecast,
        iv_z_score=body.iv_z_score,
        days_to_earnings=body.days_to_earnings,
        realized_vol_intraday=body.realized_vol_intraday,
        garch_distorted=body.garch_distorted,
    )
    return select_strategy_packet(
        quant,
        news,
        setup_designed_for_event=body.setup_designed_for_event,
        position_open=body.position_open,
    )


class SignalEvaluateRequest(BaseModel):
    """Evaluate a candidate vs GARCH / IV z + SH-4 + news + retail gates (Phase 1.5)."""

    symbol: str = Field(..., min_length=1)
    und_price: float = Field(..., gt=0)
    option_iv_annual: float = Field(..., gt=0)
    price_history: list[float] | None = None
    log_returns: list[float] | None = None
    intraday_iv_series: list[float] | None = None
    garch_forecast_annual: float | None = Field(default=None, gt=0)
    iv_z_score: float | None = None
    garch_distorted: bool | None = None
    days_to_earnings: int | None = None
    realized_vol_intraday: float | None = None
    atm_premium_inr: float = Field(default=100.0, ge=0)
    volume: int = Field(default=10_000, ge=0)
    open_interest: int = Field(default=15_000, ge=0)
    spread_pct: float = Field(default=1.0, ge=0)
    dte: int = Field(default=20, ge=0)
    includes_underlying: bool = Field(
        default=False,
        description="When true, reject as a stock/underlying hard-lock violation",
    )
    force_news: dict | None = None
    setup_designed_for_event: bool = False
    position_open: bool = False


@router.get("/signals")
async def paper_signals(
    underlying: str = Query(..., description="e.g. SBIN, RELIANCE"),
    und_price: float | None = Query(default=None, gt=0),
    option_iv_annual: float | None = Query(default=None, gt=0),
    includes_underlying: bool = Query(
        default=False,
        description="When true, marks the request as including stock/underlying legs",
    ),
):
    """GARCH, IV, IV z-score, news flags, SH-4 recommendation (Phase 1.5)."""
    from backend.services.signals import signals_for_underlying

    return signals_for_underlying(
        underlying,
        und_price=und_price,
        option_iv_annual=option_iv_annual,
        includes_underlying=includes_underlying,
    )


@router.post("/signals/evaluate")
async def paper_signals_evaluate(body: SignalEvaluateRequest):
    """Evaluate candidate vs playbook + news gates under the options-only hard lock."""
    from backend.models.recommendations import MarketNewsSummary
    from backend.services.market_news import get_market_news
    from backend.services.signals import SignalComputeInputs, evaluate_candidate

    news = get_market_news()
    if body.force_news:
        payload = news.model_dump(mode="json")
        for key, value in body.force_news.items():
            payload[key] = value
        news = MarketNewsSummary.model_validate(payload)

    inp = SignalComputeInputs(
        symbol=body.symbol,
        und_price=body.und_price,
        option_iv_annual=body.option_iv_annual,
        price_history=body.price_history,
        log_returns=body.log_returns,
        intraday_iv_series=body.intraday_iv_series,
        garch_forecast_annual=body.garch_forecast_annual,
        iv_z_score=body.iv_z_score,
        garch_distorted=body.garch_distorted,
        days_to_earnings=body.days_to_earnings,
        realized_vol_intraday=body.realized_vol_intraday,
        atm_premium_inr=body.atm_premium_inr,
        volume=body.volume,
        open_interest=body.open_interest,
        spread_pct=body.spread_pct,
        dte=body.dte,
        includes_underlying=body.includes_underlying,
    )
    return evaluate_candidate(
        inp,
        news=news,
        setup_designed_for_event=body.setup_designed_for_event,
        position_open=body.position_open,
    )


@router.get("/chain")
async def paper_option_chain(
    underlying: str = Query(..., description="e.g. NIFTY, SBIN"),
    expiry: str | None = Query(default=None),
    include_ltp: bool = Query(default=False),
    max_contracts: int = Query(default=80, ge=1, le=300),
):
    try:
        return await get_paper_engine().option_chain(
            underlying=underlying,
            expiry=expiry,
            include_ltp=include_ltp,
            max_contracts=max_contracts,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"paper chain feed error: {exc}") from exc


class AutomationStartRequest(BaseModel):
    """Optional overrides when starting the γ–θ loop (Phase 1.6)."""

    tick_sec: float | None = Field(default=None, ge=1.0)
    use_half_breakeven: bool | None = None
    rehedge_method: str | None = Field(
        default=None,
        description="increase_hedge | reduce_options | adjust_call_put_mix",
    )


@router.post("/automation/start")
async def paper_automation_start(body: AutomationStartRequest | None = None):
    """Start signal + γ–θ re-hedge (+ news kill) loop — mechanical; no LLM."""
    engine = get_paper_engine()
    if body:
        if body.tick_sec is not None:
            engine.config.automation_tick_sec = float(body.tick_sec)
        if body.use_half_breakeven is not None:
            engine.config.use_half_breakeven = bool(body.use_half_breakeven)
        if body.rehedge_method is not None:
            method = body.rehedge_method.strip().lower()
            if method not in {
                "increase_hedge",
                "reduce_options",
                "adjust_call_put_mix",
            }:
                raise HTTPException(
                    status_code=400,
                    detail=f"invalid rehedge_method: {body.rehedge_method}",
                )
            engine.config.rehedge_method = method  # type: ignore[assignment]
    return await engine.automation.start()


@router.post("/automation/stop")
async def paper_automation_stop():
    return await get_paper_engine().automation.stop()


@router.get("/automation/status")
async def paper_automation_status():
    return get_paper_engine().automation.status()


@router.post("/automation/tick")
async def paper_automation_tick():
    """Run one automation cycle (tests / manual; no LLM)."""
    from backend.paper_sim.freshness import StaleMarksError

    try:
        return await get_paper_engine().automation.tick()
    except StaleMarksError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaperLedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
