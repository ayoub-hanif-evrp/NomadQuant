"""Long-only cash accounting for simulated portfolios."""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal

from nomadquant.finance.accounting import Book, MissingMark, apply_fill
from nomadquant.finance.execution import attribute_costs, execution_price
from nomadquant.research.models import CostModel, SimulatedTrade

_ZERO = Decimal("0")


@dataclass
class Portfolio:
    cash: Decimal
    positions: dict[str, Decimal] = field(default_factory=dict)
    costs: CostModel = field(default_factory=CostModel)
    cost_basis: dict[str, Decimal] = field(default_factory=dict)
    realized_pnl: Decimal = _ZERO
    attributed_costs: Decimal = _ZERO

    def quantity(self, symbol: str) -> Decimal:
        return self.positions.get(symbol, _ZERO)

    def market_value(self, prices: dict[str, Decimal]) -> Decimal:
        total = self.cash
        for symbol, qty in self.positions.items():
            if qty == 0:
                continue
            price = prices.get(symbol)
            if price is None or price <= 0:
                raise MissingMark(symbol)
            total += qty * price
        return total

    def exposure(self, prices: dict[str, Decimal]) -> Decimal:
        equity = self.market_value(prices)
        if equity <= 0:
            return _ZERO
        invested = equity - self.cash
        return invested / equity

    def snapshot(self, prices: dict[str, Decimal]) -> dict[str, str]:
        return {
            "cash": str(self.cash),
            "equity": str(self.market_value(prices)),
            "exposure": str(self.exposure(prices)),
            "positions": ",".join(
                f"{symbol}:{qty}" for symbol, qty in sorted(self.positions.items()) if qty > 0
            ),
        }

    def rebalance_to_weight(
        self,
        *,
        symbol: str,
        target_weight: Decimal,
        price: Decimal,
        session_date: date,
        reason: str,
    ) -> SimulatedTrade | None:
        if price <= 0:
            return None
        prices = {symbol: price}
        equity = self.market_value(prices)
        if equity <= 0:
            return None
        target_value = equity * target_weight
        current_value = self.quantity(symbol) * price
        delta_value = target_value - current_value
        if abs(delta_value) < self.costs.min_notional_usd:
            return None
        if delta_value > 0:
            return self._buy(symbol, delta_value, price, session_date, reason)
        return self._sell(symbol, -delta_value, price, session_date, reason)

    def _buy(
        self,
        symbol: str,
        notional: Decimal,
        price: Decimal,
        session_date: date,
        reason: str,
    ) -> SimulatedTrade | None:
        fill_price = self._fill_price(price, buy=True)
        commission = self.costs.commission_usd
        budget = self.cash - commission
        if budget < self.costs.min_notional_usd:
            return None
        spend = min(notional, budget)
        quantity = (spend / fill_price).quantize(
            Decimal(10) ** -self.costs.quantity_precision, rounding=ROUND_DOWN
        )
        if quantity <= 0:
            return None
        total = quantity * fill_price + commission
        if total > self.cash:
            quantity = ((self.cash - commission) / fill_price).quantize(
                Decimal(10) ** -self.costs.quantity_precision, rounding=ROUND_DOWN
            )
            if quantity <= 0:
                return None
            total = quantity * fill_price + commission
        if total > self.cash:
            return None
        book, bought = apply_fill(
            self._book(),
            symbol=symbol,
            side="buy",
            quantity=quantity,
            mid=price,
            costs=self.costs,
        )
        self._adopt(book)
        costs = {
            "commission": bought.commission,
            "spread": bought.spread_cost,
            "slippage": bought.slippage_cost,
        }
        return SimulatedTrade(
            session_date=session_date,
            symbol=symbol,
            side="buy",
            quantity=quantity,
            price=bought.fill_price,
            notional=quantity * bought.fill_price,
            commission=costs["commission"],
            spread_cost=costs["spread"],
            slippage_cost=costs["slippage"],
            reason=reason,
        )

    def _sell(
        self,
        symbol: str,
        notional: Decimal,
        price: Decimal,
        session_date: date,
        reason: str,
    ) -> SimulatedTrade | None:
        held = self.quantity(symbol)
        if held <= 0:
            return None
        fill = self._fill_price(price, buy=False)
        quantity = min(
            held,
            (notional / fill).quantize(
                Decimal(10) ** -self.costs.quantity_precision, rounding=ROUND_DOWN
            ),
        )
        if quantity <= 0:
            return None
        book, fill_result = apply_fill(
            self._book(),
            symbol=symbol,
            side="sell",
            quantity=quantity,
            mid=price,
            costs=self.costs,
        )
        self._adopt(book)
        costs = {
            "commission": fill_result.commission,
            "spread": fill_result.spread_cost,
            "slippage": fill_result.slippage_cost,
        }
        proceeds = fill_result.notional
        return SimulatedTrade(
            session_date=session_date,
            symbol=symbol,
            side="sell",
            quantity=quantity,
            price=fill_result.fill_price,
            notional=proceeds,
            commission=costs["commission"],
            spread_cost=costs["spread"],
            slippage_cost=costs["slippage"],
            reason=reason,
        )

    def _book(self) -> Book:
        return Book(
            cash=self.cash,
            holdings=dict(self.positions),
            cost_basis=dict(self.cost_basis),
            realized_pnl=self.realized_pnl,
            attributed_costs=self.attributed_costs,
        )

    def _adopt(self, book: Book) -> None:
        self.cash = book.cash
        self.positions = dict(book.holdings)
        self.cost_basis = dict(book.cost_basis)
        self.realized_pnl = book.realized_pnl
        self.attributed_costs = book.attributed_costs

    def _fill_price(self, mid: Decimal, *, buy: bool) -> Decimal:
        return execution_price(mid, self.costs, side="buy" if buy else "sell")

    def _attribution(self, mid: Decimal, quantity: Decimal) -> dict[str, Decimal]:
        """Explain fill-versus-mid cost. Cash is charged only the fill and commission."""
        return attribute_costs(mid, quantity, self.costs)
