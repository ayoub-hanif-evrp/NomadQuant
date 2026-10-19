"""Observed-quote shadow fills. Separate from delayed daily-open research.

A fill may use only a quote that was already known at the decision time.
Missing, stale, crossed, or after-hours quotes become WAIT or NO_FILL.
Nothing here submits a broker order or writes a SIP bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any, Literal

from nomadquant.finance.execution import execution_price
from nomadquant.research.models import CostModel
from nomadquant.risk.policy import RiskPolicy

EXECUTION_OBSERVED_QUOTE = "OBSERVED_QUOTE_SHADOW"
_BPS = Decimal("10000")
_CLOCK_SKEW = timedelta(seconds=2)


@dataclass(frozen=True)
class QuoteObservation:
    symbol: str
    feed: Literal["iex", "sip"]
    bid: Decimal
    ask: Decimal
    market_timestamp: datetime
    retrieved_at: datetime
    source: str


def simulate_observed_fill(
    quote: QuoteObservation | None,
    *,
    side: Literal["buy", "sell"],
    decision_time: datetime,
    market_open: bool,
    cash: Decimal,
    held_quantity: Decimal,
    costs: CostModel,
    policy: RiskPolicy | None = None,
    estimated_mid: Decimal | None = None,
) -> dict[str, Any]:
    """Return a simulated fill or an explicit skip. Never invents a price."""
    active = policy or RiskPolicy()
    active.validate()
    base: dict[str, Any] = {
        "execution_model": EXECUTION_OBSERVED_QUOTE,
        "side": side,
        "symbol": None if quote is None else quote.symbol,
        "feed": None if quote is None else quote.feed,
        "broker_orders": False,
        "used_by_registered_strategy": False,
        "estimated_mid": None if estimated_mid is None else str(estimated_mid),
        "observed_price": None,
        "quantity": "0",
        "status": "NO_FILL",
        "reason": "",
    }
    if quote is None:
        return {**base, "status": "WAIT", "reason": "no_quote_captured"}
    if quote.feed not in {"iex", "sip"}:
        return {**base, "reason": "unknown_feed"}
    if quote.retrieved_at + _CLOCK_SKEW < quote.market_timestamp:
        return {**base, "reason": "retrieved_before_market_timestamp"}
    # A market timestamp from the past is not enough. The quote must have been
    # retrieved before the decision, or it was not available yet.
    if quote.retrieved_at > decision_time:
        return {**base, "reason": "quote_retrieved_after_decision"}
    if quote.market_timestamp > decision_time:
        return {**base, "reason": "quote_known_only_after_decision"}
    age = decision_time - quote.market_timestamp
    if age > active.max_price_age:
        return {**base, "status": "WAIT", "reason": "quote_older_than_policy"}
    if not market_open:
        return {**base, "reason": "market_closed_stale_quote_refused"}
    if (
        not quote.bid.is_finite()
        or not quote.ask.is_finite()
        or quote.bid <= 0
        or quote.ask <= 0
        or quote.bid > quote.ask
    ):
        return {**base, "reason": "bid_ask_unusable"}

    # Buy pays the ask, then full adverse slippage. Sell receives the bid, then slippage.
    # The spread is already inside the quote, so spread_bps is not added again.
    touch = quote.ask if side == "buy" else quote.bid
    slipped = CostModel(
        commission_usd=costs.commission_usd,
        spread_bps=Decimal("0"),
        slippage_bps=costs.slippage_bps,
        min_notional_usd=costs.min_notional_usd,
        quantity_precision=costs.quantity_precision,
    )
    price = execution_price(touch, slipped, side=side)
    if not price.is_finite() or price <= 0:
        return {**base, "reason": "nonfinite_execution_price"}

    budget = min(
        cash - active.min_cash_reserve_usd,
        active.max_single_transaction_usd,
    )
    if side == "buy":
        if budget < costs.min_notional_usd:
            return {**base, "observed_price": str(price), "reason": "below_cash_reserve_or_cap"}
        unit = price + costs.commission_usd
        raw = (budget / unit) if unit > 0 else Decimal("0")
        quantity = raw.quantize(Decimal(10) ** -costs.quantity_precision, rounding=ROUND_DOWN)
        notional = quantity * price + costs.commission_usd
        if quantity <= 0 or notional < costs.min_notional_usd or notional > cash:
            return {**base, "observed_price": str(price), "reason": "sized_quantity_rejected"}
    else:
        if held_quantity <= 0:
            return {**base, "observed_price": str(price), "reason": "no_holding"}
        quantity = held_quantity.quantize(
            Decimal(10) ** -costs.quantity_precision, rounding=ROUND_DOWN
        )
        if quantity <= 0 or quantity * price < costs.min_notional_usd:
            return {**base, "observed_price": str(price), "reason": "sized_quantity_rejected"}
        notional = quantity * price

    half_spread = (quote.ask - quote.bid) / Decimal("2")
    return {
        **base,
        "status": "SIMULATED_FILL",
        "reason": "observed_quote_accepted",
        "observed_price": str(price),
        "quantity": str(quantity),
        "notional": str(notional),
        "touch_price": str(touch),
        "quoted_spread": str(quote.ask - quote.bid),
        "attributed_half_spread": str(quantity * half_spread),
        "slippage_bps": str(costs.slippage_bps),
        "commission_usd": str(costs.commission_usd),
        "market_timestamp": quote.market_timestamp.isoformat(),
        "retrieved_at": quote.retrieved_at.isoformat(),
        "source": quote.source,
        "price_age_seconds": int(age.total_seconds()),
        "max_single_transaction_usd": str(active.max_single_transaction_usd),
        "min_cash_reserve_usd": str(active.min_cash_reserve_usd),
        "difference_vs_estimate": None if estimated_mid is None else str(price - estimated_mid),
    }


def quote_from_snapshot(
    symbol: str, raw: dict[str, Any], *, retrieved_at: datetime
) -> QuoteObservation | None:
    """Read Alpaca latestQuote. Returns None when bid/ask are absent."""
    quote = raw.get("latestQuote")
    if not isinstance(quote, dict):
        return None
    bid = _decimal(quote.get("bp"))
    ask = _decimal(quote.get("ap"))
    stamp = _time(quote.get("t"))
    if bid is None or ask is None or stamp is None:
        return None
    return QuoteObservation(
        symbol=symbol.upper(),
        feed="iex",
        bid=bid,
        ask=ask,
        market_timestamp=stamp,
        retrieved_at=retrieved_at,
        source="alpaca_snapshot_latest_quote",
    )


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    return number if number.is_finite() else None


def _time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None
