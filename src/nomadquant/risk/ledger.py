"""Internal $100 virtual ledger. Independent of Alpaca paper equity.

``InternalLedger`` is a plain snapshot: cash plus holdings. Nothing in this
module reads a broker account or submits an order. ``RiskEngine.evaluate``
never mutates the ledger instance it is given; it reads a ``snapshot()`` copy
instead, so callers can safely reuse their ledger object across evaluations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from math import isfinite

from nomadquant.risk.policy import ALLOWED_SYMBOLS


class LedgerInvalid(ValueError):
    """The ledger snapshot fails a hard validity check."""


@dataclass
class InternalLedger:
    """A point-in-time snapshot of the internal paper ledger.

    ``capital_usd`` is always the fixed internal capital base ($100). It is
    not Alpaca account equity and is never read from a broker.
    """

    cash_usd: Decimal
    holdings: dict[str, Decimal] = field(default_factory=dict)
    capital_usd: Decimal = Decimal("100")
    reserved_cash_usd: Decimal = Decimal("0")

    def snapshot(self) -> InternalLedger:
        """Return an independent copy. Mutating the copy never affects self."""
        return InternalLedger(
            cash_usd=self.cash_usd,
            holdings=dict(self.holdings),
            capital_usd=self.capital_usd,
            reserved_cash_usd=self.reserved_cash_usd,
        )

    def holding(self, symbol: str) -> Decimal:
        return self.holdings.get(symbol.upper(), Decimal("0"))

    def available_cash_usd(self) -> Decimal:
        return self.cash_usd - self.reserved_cash_usd

    def symbol_exposure_usd(self, symbol: str, price: Decimal) -> Decimal:
        """Current modeled market value of one symbol's holding."""
        return self.holding(symbol) * price

    def require_prices_for_holdings(self, prices: dict[str, Decimal]) -> tuple[bool, str]:
        """Return (ok, reason). Unpriced nonzero holdings are never treated as zero."""
        missing: list[str] = []
        for symbol, quantity in self.holdings.items():
            if quantity == 0:
                continue
            key = symbol.upper()
            price = prices.get(key)
            if price is None or price <= 0 or not _finite(price):
                missing.append(key)
        if missing:
            return (
                False,
                "Missing or invalid prices for held positions: " + ", ".join(sorted(missing)),
            )
        return (True, "All nonzero holdings have valid prices.")

    def total_exposure_usd(self, prices: dict[str, Decimal]) -> Decimal:
        """Sum of position market values. Raises if any nonzero holding lacks a price."""
        ok, reason = self.require_prices_for_holdings(prices)
        if not ok:
            raise LedgerInvalid(reason)
        total = Decimal("0")
        for symbol, quantity in self.holdings.items():
            if quantity == 0:
                continue
            total += quantity * prices[symbol.upper()]
        return total

    def validate(self, *, allowed_symbols: frozenset[str] = ALLOWED_SYMBOLS) -> None:
        """Fail closed on leverage, negatives, NaN, or unsupported positions."""
        if self.capital_usd != Decimal("100"):
            raise LedgerInvalid(
                f"capital_usd must be exactly 100 (internal research capital); "
                f"got {self.capital_usd}."
            )
        if not _finite_nonneg(self.cash_usd):
            raise LedgerInvalid(f"cash_usd must be finite and nonnegative; got {self.cash_usd}.")
        if not _finite_nonneg(self.reserved_cash_usd):
            raise LedgerInvalid(
                f"reserved_cash_usd must be finite and nonnegative; got {self.reserved_cash_usd}."
            )
        if self.reserved_cash_usd > self.cash_usd:
            raise LedgerInvalid(
                f"reserved_cash_usd {self.reserved_cash_usd} exceeds cash_usd {self.cash_usd}."
            )
        for symbol, quantity in self.holdings.items():
            key = symbol.upper()
            if key not in allowed_symbols:
                raise LedgerInvalid(f"Unsupported holding {key!r}.")
            if not _finite_nonneg(quantity):
                raise LedgerInvalid(f"Holding {key} must be finite and nonnegative.")
        # Long-only cash portfolio: cash + reserved cannot imply borrowed funds.
        if self.available_cash_usd() < 0:
            raise LedgerInvalid("Available cash would be negative (no margin).")

    @classmethod
    def starting(cls, capital_usd: Decimal = Decimal("100")) -> InternalLedger:
        """A fresh ledger: all cash, no holdings."""
        if capital_usd != Decimal("100"):
            raise LedgerInvalid("Starting capital must be exactly 100.")
        return cls(
            cash_usd=capital_usd,
            holdings={},
            capital_usd=capital_usd,
            reserved_cash_usd=Decimal("0"),
        )


def _finite(value: Decimal) -> bool:
    try:
        return value.is_finite() and isfinite(float(value))
    except (InvalidOperation, OverflowError, ValueError):
        return False


def _finite_nonneg(value: Decimal) -> bool:
    return _finite(value) and value >= 0
