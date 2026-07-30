"""Virtual cash + multi-leg position ledger for paper trading."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.paper_sim.config import PaperSimConfig
from backend.paper_sim.fill_model import compute_fill_price, leg_notional
from backend.paper_sim.models import (
    PaperAccountSnapshot,
    PaperFill,
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

    def open_position(
        self,
        *,
        strategy_tag: str | None,
        underlying: str | None,
        note: str | None,
        legs: list[dict],
        slippage_bps: float,
        order_id: str | None = None,
    ) -> tuple[PaperPosition, list[PaperFill]]:
        """
        Open a multi-leg paper position.

        Each item in ``legs`` must include:
        symbol, exchange, symbol_token, side (PaperSide), quantity, mark_ltp, lotsize
        """
        if not legs:
            raise PaperLedgerError("order has no legs")

        order_id = order_id or f"paper_{uuid4().hex[:12]}"
        fills: list[PaperFill] = []
        leg_positions: list[PaperLegPosition] = []
        total_debit = 0.0
        total_credit = 0.0

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
                # Credit premium; reserve a fraction of notional as simple margin proxy
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

        # Net capital deployed at entry ≈ debit − credit (premium structures)
        net_investment = max(total_debit - total_credit, total_debit * 0.1 if total_debit else abs(total_credit) * 0.2)
        if net_investment > self.config.max_trade_investment_inr:
            raise PaperLedgerError(
                f"trade investment {net_investment:.2f} exceeds "
                f"max_trade_investment {self.config.max_trade_investment_inr:.2f}"
            )

        cash_impact = total_credit - total_debit
        if self.cash + cash_impact < 0:
            raise PaperLedgerError(
                f"insufficient paper cash: have {self.cash:.2f}, need {-cash_impact:.2f}"
            )

        self.cash += cash_impact
        for fill in fills:
            self.fills.append(fill)

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
        )
        self.positions[position.position_id] = position
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
        open_count = sum(1 for p in self.positions.values() if p.status == "open")
        upnl = self.unrealized_pnl
        return PaperAccountSnapshot(
            cash_inr=round(self.cash, 2),
            starting_capital_inr=round(self.starting_capital, 2),
            reserved_margin_inr=0.0,
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
