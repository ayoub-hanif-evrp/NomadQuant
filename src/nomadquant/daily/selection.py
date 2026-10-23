"""Conservative portfolio choice. One equity bucket when SPY and QQQ move together."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from nomadquant.daily.indicators import realized_vol

Prices = dict[str, dict[date, Decimal]]
OVERLAP_LIMIT = Decimal("0.80")
MIN_PAIRS = 60


def equity_correlation(prices: Prices, as_of: date) -> Decimal | None:
    """Pearson correlation of aligned SPY and QQQ daily returns.

    A missing or short overlap is unknown, not zero. Unknown is not diversification.
    """
    spy = prices.get("SPY") or {}
    qqq = prices.get("QQQ") or {}
    days = sorted(
        day for day in spy if day <= as_of and day in qqq and spy[day] > 0 and qqq[day] > 0
    )
    if len(days) < MIN_PAIRS + 1:
        return None
    left: list[Decimal] = []
    right: list[Decimal] = []
    for previous, current in zip(days, days[1:], strict=False):
        left.append(spy[current] / spy[previous] - Decimal("1"))
        right.append(qqq[current] / qqq[previous] - Decimal("1"))
    count = Decimal(len(left))
    mean_left = sum(left, Decimal("0")) / count
    mean_right = sum(right, Decimal("0")) / count
    paired = sum(
        (one - mean_left) * (two - mean_right) for one, two in zip(left, right, strict=False)
    )
    scale_left = sum(((one - mean_left) ** 2 for one in left), Decimal("0")).sqrt()
    scale_right = sum(((two - mean_right) ** 2 for two in right), Decimal("0")).sqrt()
    if scale_left == 0 or scale_right == 0:
        return None
    return paired / (scale_left * scale_right)


def assign_primary(
    rows: list[dict[str, str]],
    prices: Prices,
    as_of: date,
    holdings: dict[str, Decimal],
) -> list[dict[str, str]]:
    """Rank exits ahead of new buys. Do not treat a second ETF as a new risk budget."""
    correlation = equity_correlation(prices, as_of)
    crowded = correlation is None or correlation >= OVERLAP_LIMIT
    held = {symbol for symbol, quantity in holdings.items() if quantity > 0}
    text = "" if correlation is None else format(correlation, "f")
    for row in rows:
        row["equity_correlation"] = text
        row["primary"] = "false"
        row.setdefault("rank_reason", "")
    buys = [row for row in rows if row["action"] == "BUY"]
    if crowded and held:
        for row in buys:
            if row["symbol"] not in held:
                _hold(row, "overlapping_equity_exposure")
    elif crowded and len(buys) > 1:
        ordered = sorted(buys, key=lambda row: _buy_rank(row, prices, as_of))
        ordered[0]["rank_reason"] = "single_equity_bucket"
        for row in ordered[1:]:
            _hold(row, "overlapping_equity_exposure")
    for action, reason in (("SELL", "risk_reducing_exit"), ("BUY", "new_exposure")):
        for row in rows:
            if row["action"] != action:
                continue
            row["primary"] = "true"
            if not row["rank_reason"]:
                row["rank_reason"] = reason
            return rows
    return rows


def _hold(row: dict[str, str], reason: str) -> None:
    row["action"] = "HOLD"
    row["notional_usd"] = "0"
    row["rank_reason"] = reason


def _buy_rank(row: dict[str, str], prices: Prices, as_of: date) -> tuple[Decimal, int, int]:
    vol = realized_vol(prices.get(row["symbol"]) or {}, as_of, 20)
    return (
        Decimal("9") if vol is None else vol,
        0 if row["symbol"] == "SPY" else 1,
        0 if "trend" in row["strategy_id"] else 1,
    )
