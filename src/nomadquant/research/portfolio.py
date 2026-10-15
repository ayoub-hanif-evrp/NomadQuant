"""Long-only cash accounting for simulated portfolios."""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal

from nomadquant.research.models import CostModel, SimulatedTrade

_ZERO = Decimal("0")


@dataclass
class Portfolio:
    cash: Decimal
    positions: dict[str, Decimal] = field(default_factory=dict)
    costs: CostModel = field(default_factory=CostModel)

    def quantity(self, symbol: str) -> Decimal:
        return self.positions.get(symbol, _ZERO)

    def market_value(self, prices: dict[str, Decimal]) -> Decimal:
        total = self.cash
        for symbol, qty in self.positions.items():
            total += qty * prices.get(symbol, _ZERO)
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
        fill = self._fill_price(price, buy=True)
        affordable = self.cash
        if affordable < self.costs.min_notional_usd:
            return None
        spend = min(notional, affordable)
        quantity = (spend / fill).quantize(
            Decimal(10) ** -self.costs.quantity_precision, rounding=ROUND_DOWN
        )
        if quantity <= 0:
            return None
        costs = self._trade_costs(quantity * fill)
        total = quantity * fill + costs["total"]
        if total > self.cash:
            quantity = ((self.cash - costs["total"]) / fill).quantize(
                Decimal(10) ** -self.costs.quantity_precision, rounding=ROUND_DOWN
            )
            if quantity <= 0:
                return None
            costs = self._trade_costs(quantity * fill)
            total = quantity * fill + costs["total"]
        if total > self.cash:
            return None
        self.cash -= total
        self.positions[symbol] = self.quantity(symbol) + quantity
        return SimulatedTrade(
            session_date=session_date,
            symbol=symbol,
            side="buy",
            quantity=quantity,
            price=fill,
            notional=quantity * fill,
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
        proceeds = quantity * fill
        costs = self._trade_costs(proceeds)
        self.cash += proceeds - costs["total"]
        remaining = held - quantity
        if remaining == 0:
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = remaining
        if self.cash < 0:
            raise RuntimeError("Cash became negative during a simulated sell.")
        return SimulatedTrade(
            session_date=session_date,
            symbol=symbol,
            side="sell",
            quantity=quantity,
            price=fill,
            notional=proceeds,
            commission=costs["commission"],
            spread_cost=costs["spread"],
            slippage_cost=costs["slippage"],
            reason=reason,
        )

    def _fill_price(self, mid: Decimal, *, buy: bool) -> Decimal:
        half_spread = mid * (self.costs.spread_bps / Decimal("10000")) / Decimal("2")
        slip = mid * (self.costs.slippage_bps / Decimal("10000"))
        return mid + half_spread + slip if buy else mid - half_spread - slip

    def _trade_costs(self, notional: Decimal) -> dict[str, Decimal]:
        commission = self.costs.commission_usd
        spread = notional * (self.costs.spread_bps / Decimal("10000"))
        slippage = notional * (self.costs.slippage_bps / Decimal("10000"))
        return {
            "commission": commission,
            "spread": spread,
            "slippage": slippage,
            "total": commission + spread + slippage,
        }
