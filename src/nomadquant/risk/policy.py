"""Deterministic risk policy for the internal $100 ledger.

Defaults are conservative placeholders, NOT empirically optimized. Every
evaluation records ``policy_version`` and ``policy_hash`` for reproducibility.
Nothing here imports a broker client or submits orders.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

POLICY_VERSION = "1.1.0"

ALLOWED_SYMBOLS: frozenset[str] = frozenset({"SPY", "QQQ"})


@dataclass(frozen=True)
class RiskPolicy:
    """Immutable risk limits evaluated against the internal ledger.

    Loss limits are separated on purpose:

    - ``max_transaction_cost_fraction`` — spread+commission budget for one proposal
    - ``max_realized_daily_loss_fraction`` — realized P&L day loss vs capital
    - ``max_unrealized_drawdown_fraction`` — equity drawdown from peak

    A transaction-cost check is never presented as a portfolio circuit breaker.
    """

    version: str = POLICY_VERSION
    capital_usd: Decimal = Decimal("100")
    allowed_symbols: frozenset[str] = ALLOWED_SYMBOLS
    max_total_exposure: Decimal = Decimal("1.0")
    max_symbol_exposure: Decimal = Decimal("1.0")
    max_single_transaction_usd: Decimal = Decimal("50")
    min_cash_reserve_usd: Decimal = Decimal("5")
    max_transaction_cost_fraction: Decimal = Decimal("0.25")
    max_realized_daily_loss_fraction: Decimal = Decimal("0.10")
    max_unrealized_drawdown_fraction: Decimal = Decimal("0.25")
    max_price_age: timedelta = timedelta(hours=48)
    max_qty_decimals: int = 6
    spread_bps: Decimal = Decimal("1")
    commission_usd: Decimal = Decimal("0")
    emergency_halt: bool = False

    def validate(self) -> None:
        if self.capital_usd != Decimal("100"):
            raise ValueError("capital_usd must be exactly 100.")
        if self.commission_usd < 0:
            raise ValueError("commission_usd cannot be negative.")
        if self.spread_bps < 0:
            raise ValueError("spread_bps cannot be negative.")
        if self.max_qty_decimals < 0:
            raise ValueError("max_qty_decimals cannot be negative.")
        for name, value in (
            ("max_total_exposure", self.max_total_exposure),
            ("max_symbol_exposure", self.max_symbol_exposure),
            ("max_transaction_cost_fraction", self.max_transaction_cost_fraction),
            ("max_realized_daily_loss_fraction", self.max_realized_daily_loss_fraction),
            ("max_unrealized_drawdown_fraction", self.max_unrealized_drawdown_fraction),
        ):
            if value < 0 or not value.is_finite():
                raise ValueError(f"{name} must be finite and nonnegative.")
        if self.max_single_transaction_usd < 0 or self.min_cash_reserve_usd < 0:
            raise ValueError("USD limits must be nonnegative.")
        if self.max_price_age.total_seconds() <= 0:
            raise ValueError("max_price_age must be positive.")

    def policy_hash(self) -> str:
        payload = {
            "version": self.version,
            "capital_usd": str(self.capital_usd),
            "allowed_symbols": sorted(self.allowed_symbols),
            "max_total_exposure": str(self.max_total_exposure),
            "max_symbol_exposure": str(self.max_symbol_exposure),
            "max_single_transaction_usd": str(self.max_single_transaction_usd),
            "min_cash_reserve_usd": str(self.min_cash_reserve_usd),
            "max_transaction_cost_fraction": str(self.max_transaction_cost_fraction),
            "max_realized_daily_loss_fraction": str(self.max_realized_daily_loss_fraction),
            "max_unrealized_drawdown_fraction": str(self.max_unrealized_drawdown_fraction),
            "max_price_age_seconds": self.max_price_age.total_seconds(),
            "max_qty_decimals": self.max_qty_decimals,
            "spread_bps": str(self.spread_bps),
            "commission_usd": str(self.commission_usd),
            "emergency_halt": self.emergency_halt,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "capital_usd": str(self.capital_usd),
            "allowed_symbols": sorted(self.allowed_symbols),
            "max_total_exposure": str(self.max_total_exposure),
            "max_symbol_exposure": str(self.max_symbol_exposure),
            "max_single_transaction_usd": str(self.max_single_transaction_usd),
            "min_cash_reserve_usd": str(self.min_cash_reserve_usd),
            "max_transaction_cost_fraction": str(self.max_transaction_cost_fraction),
            "max_realized_daily_loss_fraction": str(self.max_realized_daily_loss_fraction),
            "max_unrealized_drawdown_fraction": str(self.max_unrealized_drawdown_fraction),
            "max_price_age": str(self.max_price_age),
            "max_qty_decimals": self.max_qty_decimals,
            "spread_bps": str(self.spread_bps),
            "commission_usd": str(self.commission_usd),
            "emergency_halt": self.emergency_halt,
            "policy_hash": self.policy_hash(),
        }


# Back-compat alias used by older tests/docs that referred to cost proxy as
# "max_daily_modeled_loss_fraction". Prefer the explicit cost field above.
def legacy_cost_fraction(policy: RiskPolicy) -> Decimal:
    return policy.max_transaction_cost_fraction
