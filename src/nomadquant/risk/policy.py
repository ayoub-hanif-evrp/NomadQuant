"""Deterministic risk policy for the internal $100 ledger.

These defaults are conservative starting points for Phase 5A. They are NOT
empirically optimized, NOT backtested, and must be reviewed before any real
capital is ever involved. The engine treats the policy as plain data: every
evaluation records ``policy_version`` and ``policy_hash`` so a verdict can be
reproduced later against the exact limits that produced it.

Nothing in this module imports a broker client or submits orders.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

POLICY_VERSION = "1.0.0"

# Phase 5A domain: cash-only, long-only, fractional US ETFs. No leverage,
# shorts, options, or margin are modeled anywhere in this package.
ALLOWED_SYMBOLS: frozenset[str] = frozenset({"SPY", "QQQ"})


@dataclass(frozen=True)
class RiskPolicy:
    """Immutable risk limits evaluated against the internal ledger.

    Every USD figure is measured against ``capital_usd`` (the internal $100
    paper ledger), never against Alpaca account equity or buying power.
    Defaults below are deliberately conservative placeholders, not tuned
    parameters:

    - ``capital_usd``: fixed internal capital base. Mirrors
      ``Settings.initial_virtual_capital_usd``; always 100.
    - ``allowed_symbols``: the only tradeable domain (SPY, QQQ).
    - ``max_total_exposure``: cap on (total position value / capital_usd).
      1.0 means fully invested is allowed, but no leverage beyond capital.
    - ``max_symbol_exposure``: same cap, applied per symbol.
    - ``max_single_transaction_usd``: cap on one proposal's notional value.
    - ``min_cash_reserve_usd``: cash that must remain after a hypothetical
      buy, so the ledger is never modeled as fully drained.
    - ``max_daily_modeled_loss_fraction``: cap on the modeled cost of a single
      proposal (spread + commission) as a fraction of capital_usd. This is a
      simple cost-based proxy, not a value-at-risk model.
    - ``max_price_age``: a price quote older than this relative to the
      proposal's ``as_of`` is treated as insufficient data.
    - ``max_qty_decimals``: maximum fractional-share precision accepted.
    - ``spread_bps`` / ``commission_usd``: simple, deliberately pessimistic
      cost model used only to size the above limits. Not a real cost model.
    - ``emergency_halt``: when true, every proposal is rejected regardless of
      any other field. A manual kill switch.
    """

    version: str = POLICY_VERSION
    capital_usd: Decimal = Decimal("100")
    allowed_symbols: frozenset[str] = ALLOWED_SYMBOLS
    max_total_exposure: Decimal = Decimal("1.0")
    max_symbol_exposure: Decimal = Decimal("1.0")
    max_single_transaction_usd: Decimal = Decimal("50")
    min_cash_reserve_usd: Decimal = Decimal("5")
    max_daily_modeled_loss_fraction: Decimal = Decimal("0.25")
    max_price_age: timedelta = timedelta(hours=48)
    max_qty_decimals: int = 6
    spread_bps: Decimal = Decimal("1")
    commission_usd: Decimal = Decimal("0")
    emergency_halt: bool = False

    def policy_hash(self) -> str:
        """Stable content hash, independent of field declaration order."""
        payload = {
            "version": self.version,
            "capital_usd": str(self.capital_usd),
            "allowed_symbols": sorted(self.allowed_symbols),
            "max_total_exposure": str(self.max_total_exposure),
            "max_symbol_exposure": str(self.max_symbol_exposure),
            "max_single_transaction_usd": str(self.max_single_transaction_usd),
            "min_cash_reserve_usd": str(self.min_cash_reserve_usd),
            "max_daily_modeled_loss_fraction": str(self.max_daily_modeled_loss_fraction),
            "max_price_age_seconds": self.max_price_age.total_seconds(),
            "max_qty_decimals": self.max_qty_decimals,
            "spread_bps": str(self.spread_bps),
            "commission_usd": str(self.commission_usd),
            "emergency_halt": self.emergency_halt,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, object]:
        """JSON-friendly rendering for CLI status output."""
        return {
            "version": self.version,
            "capital_usd": str(self.capital_usd),
            "allowed_symbols": sorted(self.allowed_symbols),
            "max_total_exposure": str(self.max_total_exposure),
            "max_symbol_exposure": str(self.max_symbol_exposure),
            "max_single_transaction_usd": str(self.max_single_transaction_usd),
            "min_cash_reserve_usd": str(self.min_cash_reserve_usd),
            "max_daily_modeled_loss_fraction": str(self.max_daily_modeled_loss_fraction),
            "max_price_age": str(self.max_price_age),
            "max_qty_decimals": self.max_qty_decimals,
            "spread_bps": str(self.spread_bps),
            "commission_usd": str(self.commission_usd),
            "emergency_halt": self.emergency_halt,
            "policy_hash": self.policy_hash(),
        }
