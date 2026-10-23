"""Deterministic daily signals. HOLD is a normal result."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from nomadquant.daily.indicators import realized_vol, reversal_snapshot, sma, trailing_return
from nomadquant.daily.registry import REVERSAL, TREND, StrategySpec

Prices = dict[str, dict[date, Decimal]]


def _close(closes: dict[date, Decimal], as_of: date) -> Decimal | None:
    rows = [(day, price) for day, price in closes.items() if day <= as_of and price > 0]
    if not rows:
        return None
    return max(rows)[1]


def trend_target(closes: dict[date, Decimal], as_of: date) -> str:
    """Desired exposure, independent of what is already held."""
    average = sma(closes, as_of, 200)
    close = _close(closes, as_of)
    vol = realized_vol(closes, as_of, 20)
    if average is None or close is None or vol is None:
        return "unavailable"
    if close > average and vol <= Decimal("0.02"):
        return "long"
    if close <= average:
        return "cash"
    return "cash"


def trend_action(closes: dict[date, Decimal], as_of: date, held: Decimal = Decimal("0")) -> str:
    """Translate the target into an order. An existing long is not bought again."""
    target = trend_target(closes, as_of)
    if target == "unavailable":
        return "HOLD"
    if target == "long":
        return "HOLD" if held > 0 else "BUY"
    return "SELL" if held > 0 else "HOLD"


def reversal_action(closes: dict[date, Decimal], as_of: date, held: Decimal = Decimal("0")) -> str:
    if held > 0 or trend_target(closes, as_of) == "long":
        return "HOLD"
    average = sma(closes, as_of, 200)
    close = _close(closes, as_of)
    vol = realized_vol(closes, as_of, 20)
    move = trailing_return(closes, as_of, 5)
    snapshot = reversal_snapshot(closes, as_of)
    dispersion = snapshot["dispersion"]
    if (
        average is None
        or close is None
        or vol is None
        or move is None
        or dispersion is None
        or close <= average
        or vol > Decimal("0.025")
    ):
        return "HOLD"
    threshold = Decimal(dispersion) * Decimal("1.5")
    if move <= -threshold:
        return "BUY"
    return "HOLD"


def candidates(
    prices: Prices,
    as_of: date,
    holdings: dict[str, Decimal] | None = None,
) -> list[dict[str, str]]:
    """One candidate per symbol and strategy. Holding a target long emits HOLD."""
    found: list[dict[str, str]] = []
    book = holdings or {}
    for symbol in ("SPY", "QQQ"):
        closes = prices.get(symbol) or {}
        held = book.get(symbol, Decimal("0"))
        for spec, action_of in (
            (TREND, trend_action),
            (REVERSAL, reversal_action),
        ):
            action = action_of(closes, as_of, held)
            found.append(_row(spec, symbol, action, False))
    for preferred in ("SELL", "BUY"):
        for row in found:
            if row["action"] == preferred:
                row["primary"] = "true"
                return found
    return found


def _row(spec: StrategySpec, symbol: str, action: str, chosen: bool) -> dict[str, str]:
    return {
        "strategy_id": spec.strategy_id,
        "version": spec.version,
        "symbol": symbol,
        "action": action,
        "notional_usd": format(spec.notional_cap, "f") if action == "BUY" else "0",
        "primary": "true" if chosen else "false",
        "evidence_class": "historical_indicator",
    }


def primary_candidate(
    prices: Prices,
    as_of: date,
    holdings: dict[str, Decimal] | None = None,
) -> dict[str, str] | None:
    for row in candidates(prices, as_of, holdings):
        if row["primary"] == "true" and row["action"] in {"BUY", "SELL"}:
            return row
    return None
