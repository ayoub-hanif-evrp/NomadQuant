"""Position-aware research path. It never creates a broker fill."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from nomadquant.daily.engine import primary_candidate

COST = Decimal("0.0001")


def walk_forward(
    prices: dict[str, dict[date, Decimal]],
    sessions: list[date],
    *,
    folds: int = 3,
) -> dict[str, object]:
    usable = [day for day in sessions if day in (prices.get("SPY") or {})]
    if len(usable) < 220 or folds < 2:
        return {"label": "historical_research", "status": "insufficient_history", "folds": []}
    span = usable[200:]
    width = max(1, len(span) // folds)
    reports: list[dict[str, str]] = []
    for index in range(folds):
        window = span[index * width : (index + 1) * width]
        held = Decimal("0")
        equity = Decimal("1")
        buys = 0
        for cursor, day in enumerate(window[:-1]):
            choice = primary_candidate(
                {"SPY": prices["SPY"], "QQQ": prices.get("QQQ", {})}, day, {"SPY": held}
            )
            nxt = prices["SPY"].get(window[cursor + 1])
            today = prices["SPY"][day]
            if nxt is None or today <= 0:
                continue
            change = nxt / today - Decimal("1")
            action = None if choice is None else choice["action"]
            if action == "BUY" and held == 0 and choice is not None and choice["symbol"] == "SPY":
                equity *= Decimal("1") - COST
                held = Decimal("1")
                buys += 1
            elif action == "SELL" and held > 0:
                equity *= Decimal("1") + change
                equity *= Decimal("1") - COST
                held = Decimal("0")
                continue
            if held > 0:
                equity *= Decimal("1") + change
        reports.append(
            {
                "fold": str(index + 1),
                "hypothetical_return": format(equity - Decimal("1"), "f"),
                "buy_days": str(buys),
                "ending_position": format(held, "f"),
                "label": "hypothetical_not_broker",
            }
        )
    return {"label": "historical_research", "status": "completed", "folds": reports}
