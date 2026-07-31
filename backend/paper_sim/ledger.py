"""Virtual cash + multi-leg position ledger for paper trading."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.paper_sim.config import PaperSimConfig
from backend.paper_sim.fill_model import compute_fill_price, leg_notional
from backend.paper_sim.models import (
    PaperAccountSnapshot,
    PaperFill,
    PaperIntendedLeg,
    PaperLegPosition,
    PaperPosition,
    PaperSide,
)


class PaperLedgerError(ValueError):
    """Raised when a paper trade violates capital or ledger rules."""


class PaperLedger:
    def __init__(self, config: PaperSimConfig) -> None:
        self.config = config
        self.cash = float(config.total_capital_inr)
        self.starting_capital = float(config.total_capital_inr)
        self.realized_pnl = 0.0
        self.positions: dict[str, PaperPosition] = {}
        self.fills: list[PaperFill] = []
        self._updated_at = datetime.now(timezone.utc)

    def reset(self, starting_capital: float | None = None) -> None:
        capital = float(starting_capital if starting_capital is not None else self.config.total_capital_inr)
        self.cash = capital
        self.starting_capital = capital
        self.realized_pnl = 0.0
        self.positions.clear()
        self.fills.clear()
        self._touch()

    def _touch(self) -> None:
        self._updated_at = datetime.now(timezone.utc)

    def _fill_legs(
        self,
        *,
        legs: list[dict],
        slippage_bps: float,
        order_id: str,
        enforce_trade_cap: bool,
        max_trade_investment_inr: float | None = None,
    ) -> tuple[list[PaperFill], list[PaperLegPosition], float, float]:
        """Price legs, enforce per-leg / cash caps; optionally trade investment cap."""
        if not legs:
            raise PaperLedgerError("order has no legs")

        fills: list[PaperFill] = []
        leg_positions: list[PaperLegPosition] = []
        total_debit = 0.0
        total_credit = 0.0
        trade_cap = (
            float(max_trade_investment_inr)
            if max_trade_investment_inr is not None
            else float(self.config.max_trade_investment_inr)
        )

        for raw in legs:
            side = raw["side"] if isinstance(raw["side"], PaperSide) else PaperSide(raw["side"])
            qty = int(raw["quantity"])
            mark = float(raw["mark_ltp"])
            fill_price = compute_fill_price(mark, side, slippage_bps)
            notional = leg_notional(fill_price, qty)

            if notional > self.config.max_leg_investment_inr:
                raise PaperLedgerError(
                    f"leg {raw['symbol']} notional {notional:.2f} exceeds "
                    f"max_leg_investment {self.config.max_leg_investment_inr:.2f}"
                )

            if side == PaperSide.buy:
                total_debit += notional
            else:
                total_credit += notional

            fill = PaperFill(
                fill_id=f"fill_{uuid4().hex[:10]}",
                order_id=order_id,
                symbol=str(raw["symbol"]),
                exchange=str(raw["exchange"]),
                symbol_token=str(raw["symbol_token"]),
                side=side,
                quantity=qty,
                mark_ltp=mark,
                fill_price=fill_price,
                slippage_bps=slippage_bps,
                notional_inr=notional,
                filled_at=datetime.now(timezone.utc),
            )
            fills.append(fill)
            leg_positions.append(
                PaperLegPosition(
                    symbol=fill.symbol,
                    exchange=fill.exchange,
                    symbol_token=fill.symbol_token,
                    side=side,
                    quantity=qty,
                    avg_price=fill_price,
                    mark_ltp=mark,
                    unrealized_pnl=0.0,
                    lotsize=int(raw.get("lotsize") or 1),
                )
            )

        if enforce_trade_cap:
            net_investment = max(
                total_debit - total_credit,
                total_debit * 0.1 if total_debit else abs(total_credit) * 0.2,
            )
            if net_investment > trade_cap:
                raise PaperLedgerError(
                    f"trade investment {net_investment:.2f} exceeds "
                    f"max_trade_investment {trade_cap:.2f}"
                )

        cash_impact = total_credit - total_debit
        if self.cash + cash_impact < 0:
            raise PaperLedgerError(
                f"insufficient paper cash: have {self.cash:.2f}, need {-cash_impact:.2f}"
            )

        return fills, leg_positions, total_debit, total_credit

    def open_position(
        self,
        *,
        strategy_tag: str | None,
        underlying: str | None,
        note: str | None,
        legs: list[dict],
        slippage_bps: float,
        order_id: str | None = None,
        hedge_point_price: float | None = None,
        rehedge_method: str | None = None,
        intended_legs: list[PaperIntendedLeg] | None = None,
        auto_complete_multi_leg: bool = True,
        structure_complete: bool = True,
    ) -> tuple[PaperPosition, list[PaperFill]]:
        """
        Open a multi-leg paper position.

        Each item in ``legs`` must include:
        symbol, exchange, symbol_token, side (PaperSide), quantity, mark_ltp, lotsize
        """
        order_id = order_id or f"paper_{uuid4().hex[:12]}"
        fills, leg_positions, _debit, _credit = self._fill_legs(
            legs=legs,
            slippage_bps=slippage_bps,
            order_id=order_id,
            enforce_trade_cap=True,
        )

        total_debit = sum(f.notional_inr for f in fills if f.side == PaperSide.buy)
        total_credit = sum(f.notional_inr for f in fills if f.side == PaperSide.sell)
        self.cash += total_credit - total_debit
        for fill in fills:
            self.fills.append(fill)

        opening_investment = max(
            total_debit - total_credit,
            total_debit * 0.1 if total_debit else abs(total_credit) * 0.2,
        )
        method = rehedge_method or getattr(self.config, "rehedge_method", "increase_hedge")
        planned = list(intended_legs or [])
        position = PaperPosition(
            position_id=f"pos_{uuid4().hex[:12]}",
            strategy_tag=strategy_tag,
            underlying=underlying,
            status="open",
            opened_at=datetime.now(timezone.utc),
            legs=leg_positions,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            note=note,
            intended_legs=planned,
            structure_complete=bool(structure_complete),
            opening_investment_inr=float(opening_investment),
            auto_complete_multi_leg=bool(auto_complete_multi_leg),
            hedge_point_price=float(hedge_point_price) if hedge_point_price else None,
            breakeven_paid_count=0,
            rehedge_method=method,  # type: ignore[arg-type]
        )
        self.positions[position.position_id] = position
        self._touch()
        return position, fills

    def add_opening_legs(
        self,
        position_id: str,
        *,
        legs: list[dict],
        slippage_bps: float,
        order_id: str | None = None,
        mark_structure_complete: bool | None = None,
    ) -> tuple[PaperPosition, list[PaperFill]]:
        """
        Append remaining *opening* legs to an incomplete multi-leg structure.

        Uses the same per-leg / cash / cumulative max_trade_investment rules as
        ``open_position`` (not hedge exemptions). Does not bump breakeven_paid_count.
        """
        position = self.positions.get(position_id)
        if position is None:
            raise PaperLedgerError(f"unknown position_id={position_id}")
        if position.status != "open":
            raise PaperLedgerError(f"position {position_id} is already closed")

        order_id = order_id or f"paper_ml_{uuid4().hex[:10]}"
        remaining_cap = max(
            0.0,
            float(self.config.max_trade_investment_inr)
            - float(position.opening_investment_inr or 0.0),
        )
        fills, new_legs, total_debit, total_credit = self._fill_legs(
            legs=legs,
            slippage_bps=slippage_bps,
            order_id=order_id,
            enforce_trade_cap=True,
            max_trade_investment_inr=remaining_cap,
        )

        incremental = max(
            total_debit - total_credit,
            total_debit * 0.1 if total_debit else abs(total_credit) * 0.2,
        )
        absolute_cap = float(self.config.max_trade_investment_inr)
        if position.opening_investment_inr + incremental > absolute_cap + 1e-6:
            raise PaperLedgerError(
                f"trade investment {position.opening_investment_inr + incremental:.2f} "
                f"exceeds max_trade_investment {absolute_cap:.2f}"
            )

        self.cash += total_credit - total_debit
        for fill in fills:
            self.fills.append(fill)

        for new_leg in new_legs:
            merged = False
            for existing in position.legs:
                if (
                    existing.symbol_token == new_leg.symbol_token
                    and existing.side == new_leg.side
                ):
                    total_qty = existing.quantity + new_leg.quantity
                    existing.avg_price = (
                        existing.avg_price * existing.quantity
                        + new_leg.avg_price * new_leg.quantity
                    ) / total_qty
                    existing.quantity = total_qty
                    existing.mark_ltp = new_leg.mark_ltp
                    merged = True
                    break
            if not merged:
                position.legs.append(new_leg)

        position.opening_investment_inr = float(position.opening_investment_inr) + float(
            incremental
        )
        if mark_structure_complete is not None:
            position.structure_complete = bool(mark_structure_complete)
        self._touch()
        return position, fills

    def apply_rehedge_legs(
        self,
        position_id: str,
        *,
        legs: list[dict],
        slippage_bps: float,
        hedge_point_price: float,
        gamma_theta_breakeven_pct: float | None = None,
        total_delta: float | None = None,
        total_gamma: float | None = None,
        total_theta: float | None = None,
        total_vega: float | None = None,
        rehedge_method: str | None = None,
        order_id: str | None = None,
    ) -> tuple[PaperPosition, list[PaperFill]]:
        """Append hedge legs to an open position and roll Part J hedge state (PS-05 caps)."""
        position = self.positions.get(position_id)
        if position is None:
            raise PaperLedgerError(f"unknown position_id={position_id}")
        if position.status != "open":
            raise PaperLedgerError(f"position {position_id} is already closed")

        order_id = order_id or f"paper_hedge_{uuid4().hex[:10]}"
        fills, new_legs, _d, _c = self._fill_legs(
            legs=legs,
            slippage_bps=slippage_bps,
            order_id=order_id,
            enforce_trade_cap=True,
        )

        total_debit = sum(f.notional_inr for f in fills if f.side == PaperSide.buy)
        total_credit = sum(f.notional_inr for f in fills if f.side == PaperSide.sell)
        self.cash += total_credit - total_debit
        for fill in fills:
            self.fills.append(fill)

        # Merge same-symbol same-side legs; otherwise append.
        for new_leg in new_legs:
            merged = False
            for existing in position.legs:
                if (
                    existing.symbol_token == new_leg.symbol_token
                    and existing.side == new_leg.side
                ):
                    total_qty = existing.quantity + new_leg.quantity
                    existing.avg_price = (
                        existing.avg_price * existing.quantity
                        + new_leg.avg_price * new_leg.quantity
                    ) / total_qty
                    existing.quantity = total_qty
                    existing.mark_ltp = new_leg.mark_ltp
                    merged = True
                    break
            if not merged:
                position.legs.append(new_leg)

        position.hedge_point_price = float(hedge_point_price)
        position.breakeven_paid_count = int(position.breakeven_paid_count or 0) + 1
        position.last_rehedge_at = datetime.now(timezone.utc)
        if gamma_theta_breakeven_pct is not None:
            position.gamma_theta_breakeven_pct = float(gamma_theta_breakeven_pct)
        if total_delta is not None:
            position.total_delta = float(total_delta)
        if total_gamma is not None:
            position.total_gamma = float(total_gamma)
        if total_theta is not None:
            position.total_theta = float(total_theta)
        if total_vega is not None:
            position.total_vega = float(total_vega)
        if rehedge_method:
            position.rehedge_method = rehedge_method  # type: ignore[assignment]
        self._touch()
        return position, fills

    def update_hedge_state(
        self,
        position_id: str,
        *,
        hedge_point_price: float | None = None,
        gamma_theta_breakeven_pct: float | None = None,
        total_delta: float | None = None,
        total_gamma: float | None = None,
        total_theta: float | None = None,
        total_vega: float | None = None,
        rehedge_method: str | None = None,
    ) -> PaperPosition:
        position = self.positions.get(position_id)
        if position is None:
            raise PaperLedgerError(f"unknown position_id={position_id}")
        if hedge_point_price is not None:
            position.hedge_point_price = float(hedge_point_price)
        if gamma_theta_breakeven_pct is not None:
            position.gamma_theta_breakeven_pct = float(gamma_theta_breakeven_pct)
        if total_delta is not None:
            position.total_delta = float(total_delta)
        if total_gamma is not None:
            position.total_gamma = float(total_gamma)
        if total_theta is not None:
            position.total_theta = float(total_theta)
        if total_vega is not None:
            position.total_vega = float(total_vega)
        if rehedge_method:
            position.rehedge_method = rehedge_method  # type: ignore[assignment]
        self._touch()
        return position

    def reduce_option_legs(
        self,
        position_id: str,
        *,
        reduce_by_lots: int,
        marks: dict[str, float],
        slippage_bps: float,
        hedge_point_price: float,
        gamma_theta_breakeven_pct: float | None = None,
        total_delta: float | None = None,
        total_gamma: float | None = None,
        total_theta: float | None = None,
        order_id: str | None = None,
    ) -> tuple[PaperPosition, list[PaperFill]]:
        """Partial close of option legs (``reduce_options`` method / PS-05 fallback)."""
        position = self.positions.get(position_id)
        if position is None:
            raise PaperLedgerError(f"unknown position_id={position_id}")
        if position.status != "open":
            raise PaperLedgerError(f"position {position_id} is already closed")
        if reduce_by_lots < 1:
            raise PaperLedgerError("reduce_by_lots must be >= 1")

        order_id = order_id or f"paper_reduce_{uuid4().hex[:10]}"
        fills: list[PaperFill] = []
        cash_delta = 0.0
        realized = 0.0
        remaining_legs: list[PaperLegPosition] = []

        for leg in position.legs:
            is_option = leg.exchange.upper() == "NFO" or leg.symbol.upper().endswith(
                ("CE", "PE")
            )
            if not is_option:
                remaining_legs.append(leg)
                continue

            lot = max(int(leg.lotsize or 1), 1)
            cut = min(leg.quantity, reduce_by_lots * lot)
            if cut <= 0:
                remaining_legs.append(leg)
                continue

            mark = marks.get(leg.symbol_token) or marks.get(leg.symbol)
            if mark is None or mark <= 0:
                raise PaperLedgerError(f"missing mark for {leg.symbol}")

            close_side = PaperSide.sell if leg.side == PaperSide.buy else PaperSide.buy
            fill_price = compute_fill_price(float(mark), close_side, slippage_bps)
            notional = leg_notional(fill_price, cut)

            if leg.side == PaperSide.buy:
                leg_pnl = (fill_price - leg.avg_price) * cut
                cash_delta += fill_price * cut
            else:
                leg_pnl = (leg.avg_price - fill_price) * cut
                cash_delta -= fill_price * cut

            realized += leg_pnl
            fill = PaperFill(
                fill_id=f"fill_{uuid4().hex[:10]}",
                order_id=order_id,
                symbol=leg.symbol,
                exchange=leg.exchange,
                symbol_token=leg.symbol_token,
                side=close_side,
                quantity=cut,
                mark_ltp=float(mark),
                fill_price=fill_price,
                slippage_bps=slippage_bps,
                notional_inr=notional,
                filled_at=datetime.now(timezone.utc),
            )
            fills.append(fill)
            self.fills.append(fill)

            left = leg.quantity - cut
            if left > 0:
                leg.quantity = left
                remaining_legs.append(leg)

        if not fills:
            raise PaperLedgerError("no option legs available to reduce")

        self.cash += cash_delta
        self.realized_pnl += realized
        position.realized_pnl = float(position.realized_pnl or 0.0) + realized
        position.legs = remaining_legs
        position.hedge_point_price = float(hedge_point_price)
        position.breakeven_paid_count = int(position.breakeven_paid_count or 0) + 1
        position.last_rehedge_at = datetime.now(timezone.utc)
        position.rehedge_method = "reduce_options"
        if gamma_theta_breakeven_pct is not None:
            position.gamma_theta_breakeven_pct = float(gamma_theta_breakeven_pct)
        if total_delta is not None:
            position.total_delta = float(total_delta)
        if total_gamma is not None:
            position.total_gamma = float(total_gamma)
        if total_theta is not None:
            position.total_theta = float(total_theta)

        if not position.legs:
            position.status = "closed"
            position.closed_at = datetime.now(timezone.utc)
            position.unrealized_pnl = 0.0

        self._touch()
        return position, fills

    def close_position(
        self,
        position_id: str,
        marks: dict[str, float],
        slippage_bps: float,
    ) -> tuple[PaperPosition, list[PaperFill], float]:
        position = self.positions.get(position_id)
        if position is None:
            raise PaperLedgerError(f"unknown position_id={position_id}")
        if position.status != "open":
            raise PaperLedgerError(f"position {position_id} is already closed")

        order_id = f"paper_close_{uuid4().hex[:10]}"
        fills: list[PaperFill] = []
        pnl = 0.0
        cash_delta = 0.0

        for leg in position.legs:
            mark = marks.get(leg.symbol_token) or marks.get(leg.symbol)
            if mark is None or mark <= 0:
                raise PaperLedgerError(f"missing mark for {leg.symbol}")

            # Closing side is opposite of opening side
            close_side = PaperSide.sell if leg.side == PaperSide.buy else PaperSide.buy
            fill_price = compute_fill_price(float(mark), close_side, slippage_bps)
            notional = leg_notional(fill_price, leg.quantity)

            if leg.side == PaperSide.buy:
                # Long: sell to close → receive fill, PnL = (exit - entry) * qty
                leg_pnl = (fill_price - leg.avg_price) * leg.quantity
                cash_delta += fill_price * leg.quantity
            else:
                # Short: buy to close → pay fill, PnL = (entry - exit) * qty
                leg_pnl = (leg.avg_price - fill_price) * leg.quantity
                cash_delta -= fill_price * leg.quantity

            pnl += leg_pnl
            fill = PaperFill(
                fill_id=f"fill_{uuid4().hex[:10]}",
                order_id=order_id,
                symbol=leg.symbol,
                exchange=leg.exchange,
                symbol_token=leg.symbol_token,
                side=close_side,
                quantity=leg.quantity,
                mark_ltp=float(mark),
                fill_price=fill_price,
                slippage_bps=slippage_bps,
                notional_inr=notional,
                filled_at=datetime.now(timezone.utc),
            )
            fills.append(fill)
            self.fills.append(fill)
            leg.mark_ltp = float(mark)
            leg.unrealized_pnl = 0.0

        self.cash += cash_delta
        self.realized_pnl += pnl
        position.realized_pnl = pnl
        position.unrealized_pnl = 0.0
        position.status = "closed"
        position.closed_at = datetime.now(timezone.utc)
        self._touch()
        return position, fills, pnl

    def apply_marks(self, marks: dict[str, float]) -> None:
        for position in self.positions.values():
            if position.status != "open":
                continue
            upnl = 0.0
            for leg in position.legs:
                mark = marks.get(leg.symbol_token) or marks.get(leg.symbol)
                if mark is None or mark <= 0:
                    continue
                leg.mark_ltp = float(mark)
                if leg.side == PaperSide.buy:
                    leg.unrealized_pnl = (float(mark) - leg.avg_price) * leg.quantity
                else:
                    leg.unrealized_pnl = (leg.avg_price - float(mark)) * leg.quantity
                upnl += leg.unrealized_pnl
            position.unrealized_pnl = upnl
        self._touch()

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions.values() if p.status == "open")

    def snapshot(self) -> PaperAccountSnapshot:
        open_positions = [p for p in self.positions.values() if p.status == "open"]
        open_count = len(open_positions)
        upnl = self.unrealized_pnl
        reserved = sum(float(p.opening_investment_inr or 0.0) for p in open_positions)
        return PaperAccountSnapshot(
            cash_inr=round(self.cash, 2),
            starting_capital_inr=round(self.starting_capital, 2),
            reserved_margin_inr=round(reserved, 2),
            equity_inr=round(self.cash + upnl, 2),
            realized_pnl=round(self.realized_pnl, 2),
            unrealized_pnl=round(upnl, 2),
            open_positions=open_count,
            max_trade_investment_inr=self.config.max_trade_investment_inr,
            max_leg_investment_inr=self.config.max_leg_investment_inr,
            mark_provider=self.config.mark_provider,
            updated_at=self._updated_at,
        )

    def list_positions(self, *, status: str | None = None) -> list[PaperPosition]:
        rows = list(self.positions.values())
        if status:
            rows = [p for p in rows if p.status == status]
        return sorted(rows, key=lambda p: p.opened_at, reverse=True)
