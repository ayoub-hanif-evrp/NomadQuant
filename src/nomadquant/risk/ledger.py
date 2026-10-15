"""Internal $100 virtual ledger. Independent of Alpaca paper equity.

``InternalLedger`` is a plain snapshot: cash plus holdings. Nothing in this
module reads a broker account or submits an order. ``RiskEngine.evaluate``
never mutates the ledger instance it is given; it reads a ``snapshot()`` copy
instead, so callers can safely reuse their ledger object across evaluations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class InternalLedger:
    """A point-in-time snapshot of the internal paper ledger.

    ``capital_usd`` records the fixed internal capital base (always 100, per
    ``Settings.initial_virtual_capital_usd``) used for exposure-fraction
    limits. It is not Alpaca account equity and is never read from a broker.
    """

    cash_usd: Decimal
    holdings: dict[str, Decimal] = field(default_factory=dict)
    capital_usd: Decimal = Decimal("100")

    def snapshot(self) -> InternalLedger:
        """Return an independent copy. Mutating the copy never affects self."""
        return InternalLedger(
            cash_usd=self.cash_usd,
            holdings=dict(self.holdings),
            capital_usd=self.capital_usd,
        )

    def holding(self, symbol: str) -> Decimal:
        return self.holdings.get(symbol.upper(), Decimal("0"))

    def symbol_exposure_usd(self, symbol: str, price: Decimal) -> Decimal:
        """Current modeled market value of one symbol's holding."""
        return self.holding(symbol) * price

    def total_exposure_usd(self, prices: dict[str, Decimal]) -> Decimal:
        """Current modeled market value of all holdings with a known price.

        A holding whose symbol is missing from ``prices`` is skipped rather
        than guessed; callers should supply a price for every held symbol.
        """
        total = Decimal("0")
        for symbol, quantity in self.holdings.items():
            price = prices.get(symbol.upper())
            if price is not None:
                total += quantity * price
        return total

    @classmethod
    def starting(cls, capital_usd: Decimal = Decimal("100")) -> InternalLedger:
        """A fresh ledger: all cash, no holdings."""
        return cls(cash_usd=capital_usd, holdings={}, capital_usd=capital_usd)
